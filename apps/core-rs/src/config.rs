//! Configuration for the Rust hotpath service.
//!
//! All settings are read from environment variables so the binary can run in
//! any deployment without a config file. Defaults are tuned for local dev.

use std::net::SocketAddr;

#[derive(Debug, Clone)]
pub struct Config {
    /// Bind address. Always localhost by default — Nginx reverse-proxies here.
    pub bind: SocketAddr,
    /// Redis for widget/search cache.
    pub redis_url: String,
    /// ClickHouse for analytics (optional).
    pub clickhouse_url: Option<String>,
    /// Per-source HTTP timeout for external search adapters (ms).
    pub source_timeout_ms: u64,
    /// Circuit breaker failure threshold before tripping.
    pub cb_failure_threshold: u32,
    /// Circuit breaker reset timeout (seconds).
    pub cb_reset_secs: u64,
    /// Default widget cache TTL (seconds).
    pub widget_cache_ttl: u64,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            bind: ([127, 0, 0, 1], 8001).into(),
            redis_url: std::env::var("REDIS_URL")
                .unwrap_or_else(|_| "redis://127.0.0.1:6379".to_string()),
            clickhouse_url: std::env::var("CLICKHOUSE_URL").ok(),
            source_timeout_ms: 5000,
            cb_failure_threshold: 5,
            cb_reset_secs: 30,
            widget_cache_ttl: 300,
        }
    }
}

impl Config {
    pub fn from_env() -> Self {
        let mut cfg = Self::default();
        if let Ok(bind) = std::env::var("CORE_BIND") {
            if let Ok(addr) = bind.parse() {
                cfg.bind = addr;
            }
        }
        if let Ok(ms) = std::env::var("SOURCE_TIMEOUT_MS") {
            if let Ok(v) = ms.parse() {
                cfg.source_timeout_ms = v;
            }
        }
        if let Ok(ttl) = std::env::var("WIDGET_CACHE_TTL") {
            if let Ok(v) = ttl.parse() {
                cfg.widget_cache_ttl = v;
            }
        }
        cfg
    }
}
