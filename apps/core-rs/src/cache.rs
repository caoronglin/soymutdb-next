//! Cache layer — Redis-backed with single-flight stampede protection.
//!
//! Design:
//!   - L1: in-process LRU (bounded to 10k entries) for fastest path
//!   - L2: Redis for multi-instance sharing
//!   - Single-flight: concurrent requests for the same key wait on the first fetch
//!   - TTL-aware: stale-while-revalidate for background refresh

use std::sync::Arc;
use std::time::{Duration, Instant};

use dashmap::DashMap;
use lru::LruCache;
use redis::AsyncCommands;
use tokio::sync::broadcast;

use crate::config::Config;
use crate::error::{CoreError, Result};

const L1_CAPACITY: usize = 10_000;

struct L1Entry {
    value: String,
    expires: Instant,
}

pub struct Cache {
    redis: Option<redis::aio::ConnectionManager>,
    l1: Arc<tokio::sync::Mutex<LruCache<String, L1Entry>>>,
    flights: Arc<DashMap<String, broadcast::Sender<Option<String>>>>,
    ttl: Duration,
}

impl Cache {
    pub async fn new(config: &Config) -> Self {
        let redis_client = redis::Client::open(config.redis_url.as_str()).ok();
        let redis = if let Some(client) = redis_client {
            client
                .get_connection_manager()
                .await
                .map_err(|e| tracing::warn!("redis connect failed: {e}, using L1 only"))
                .ok()
        } else {
            None
        };

        Self {
            redis,
            l1: Arc::new(tokio::sync::Mutex::new(LruCache::new(
                std::num::NonZeroUsize::new(L1_CAPACITY).unwrap(),
            ))),
            flights: Arc::new(DashMap::new()),
            ttl: Duration::from_secs(config.widget_cache_ttl),
        }
    }

    /// Get a cached value, or invoke `f` to populate it on miss.
    /// Single-flight: concurrent callers for the same key all wait on the first fetch.
    pub async fn get_or_populate<F, Fut>(&self, key: &str, f: F) -> Result<String>
    where
        F: FnOnce() -> Fut,
        Fut: std::future::Future<Output = Result<String>>,
    {
        // 1. L1 check
        {
            let mut l1 = self.l1.lock().await;
            if let Some(entry) = l1.get(key) {
                if entry.expires > Instant::now() {
                    return Ok(entry.value.clone());
                }
            }
        }

        // 2. L2 check
        if let Some(redis) = &self.redis {
            if let Ok(Some(v)) = redis.clone().get::<_, Option<String>>(key).await {
                let mut l1 = self.l1.lock().await;
                l1.put(
                    key.to_string(),
                    L1Entry {
                        value: v.clone(),
                        expires: Instant::now() + self.ttl,
                    },
                );
                return Ok(v);
            }
        }

        // 3. Single-flight: join existing waiters or become the fetcher
        if let Some(tx) = self.flights.get(key) {
            let mut rx = tx.subscribe();
            drop(tx);
            if let Ok(Some(v)) = rx.recv().await {
                return Ok(v);
            }
            // If the fetcher failed, fall through and try ourselves
        } else {
            let (tx, _) = broadcast::channel(1);
            self.flights.insert(key.to_string(), tx);
        }

        // We are the fetcher
        let value = match f().await {
            Ok(v) => v,
            Err(e) => {
                if let Some((_, tx)) = self.flights.remove(key) {
                    let _ = tx.send(None);
                }
                return Err(e);
            }
        };

        // Populate caches
        {
            let mut l1 = self.l1.lock().await;
            l1.put(
                key.to_string(),
                L1Entry {
                    value: value.clone(),
                    expires: Instant::now() + self.ttl,
                },
            );
        }
        if let Some(redis) = &self.redis {
            let mut r = redis.clone();
            let ttl_secs = self.ttl.as_secs() as usize;
            let _: Result<()> = r.set_ex(key, &value, ttl_secs).await.map_err(|e| {
                tracing::warn!("redis set failed: {e}");
                CoreError::Cache(e.to_string())
            });
        }

        if let Some((_, tx)) = self.flights.remove(key) {
            let _ = tx.send(Some(value.clone()));
        }

        Ok(value)
    }

    pub async fn invalidate(&self, key: &str) {
        {
            let mut l1 = self.l1.lock().await;
            l1.pop(key);
        }
        if let Some(redis) = &self.redis {
            let _: Result<()> = redis.clone().del(key).await.map_err(|e| {
                tracing::warn!("redis del failed: {e}");
                CoreError::Cache(e.to_string())
            });
        }
    }
}
