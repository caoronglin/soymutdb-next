//! SoyMutDB Core — Rust hotpath service.
//!
//! Internal service bound to 127.0.0.1:8001 (NOT public). Nginx routes
//! select endpoints here after benchmark evidence demonstrates the Python
//! path is the bottleneck.
//!
//! Three responsibilities, each independently benchmark-gated:
//!   1. Widget rendering — cached, sanitized HTML fragments via Tera templates
//!      (target: P95 < 5ms on warm cache vs Python's ~40ms)
//!   2. Search aggregation — parallel fan-out to NCBI/UniProt/Ensembl with
//!      circuit breaker, per-source timeout, normalized rendering
//!   3. Analytics ingestion — high-throughput tracking pixel endpoint,
//!      batched ClickHouse writes
//!
//! All routes return `text/html; charset=utf-8` for widgets/search, matching
//! the Python API contract. Frontend code does not need to know which layer
//! served the response.
//!
//! Safety:
//!   - Bound to 127.0.0.1 only (no external bind)
//!   - All HTML is sanitized with `ammonia` (Rust port of bleach semantics)
//!   - Redis cache with TTL, stampede protection via single-flight
//!   - Per-source circuit breaker for external HTTP calls
//!   - Graceful shutdown on SIGTERM/SIGINT

pub mod analytics;
pub mod cache;
pub mod config;
pub mod error;
pub mod search;
pub mod server;
pub mod widgets;

pub use config::Config;
pub use error::CoreError;
