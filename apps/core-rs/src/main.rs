//! SoyMutDB Rust hotpath service binary.
//!
//! Binds to 127.0.0.1:8001 by default (internal-only, proxied by Nginx).
//! Run with --help for options.

use clap::Parser;
use soymutdb_core::{config::Config, server::serve};

#[derive(Parser, Debug)]
#[command(name = "soymutdb-core", version, about = "SoyMutDB Rust hotpath service (internal)")]
struct Cli {
    /// Bind address (default 127.0.0.1:8001)
    #[arg(long, env = "CORE_BIND")]
    bind: Option<String>,

    /// Redis URL for shared cache
    #[arg(long, env = "REDIS_URL")]
    redis_url: Option<String>,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "soymutdb_core=info,tower_http=warn".into()),
        )
        .json()
        .with_target(false)
        .init();

    let cli = Cli::parse();
    let mut config = Config::from_env();
    if let Some(b) = cli.bind {
        if let Ok(addr) = b.parse() { config.bind = addr; }
    }
    if let Some(u) = cli.redis_url { config.redis_url = u; }

    tracing::info!(?config, "starting soymutdb-core");
    serve(config).await
}
