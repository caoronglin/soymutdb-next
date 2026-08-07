//! Axum server wiring.

use std::net::SocketAddr;
use std::sync::Arc;

use axum::routing::get;
use axum::Router;
use tower_http::compression::CompressionLayer;
use tower_http::trace::TraceLayer;

use crate::analytics::{spawn_writer, AnalyticsState, track};
use crate::cache::Cache;
use crate::config::Config;
use crate::search::{search, SearchState};
use crate::widgets::{render_widget, WidgetState};

/// Combined app state for Axum extractors.
#[derive(Clone)]
pub struct AppState {
    pub widget: WidgetState,
    pub search: SearchState,
    pub analytics: Arc<AnalyticsState>,
}

// Axum 0.7 FromRef impls so each handler can extract its own state slice.
impl axum::extract::FromRef<AppState> for WidgetState {
    fn from_ref(s: &AppState) -> Self { s.widget.clone() }
}
impl axum::extract::FromRef<AppState> for SearchState {
    fn from_ref(s: &AppState) -> Self { s.search.clone() }
}
impl axum::extract::FromRef<AppState> for Arc<AnalyticsState> {
    fn from_ref(s: &AppState) -> Self { s.analytics.clone() }
}

pub async fn serve(config: Config) -> anyhow::Result<()> {
    let cache = Arc::new(Cache::new(&config).await);
    let widget = WidgetState::new(cache.clone()).await;
    let search_state = SearchState::new(cache.clone(), config.clone());

    let (analytics, analytics_rx) = AnalyticsState::new();
    let analytics = Arc::new(analytics);
    spawn_writer(analytics_rx, config.clickhouse_url.clone());

    let state = AppState { widget, search: search_state, analytics };

    let app = Router::new()
        .route("/health", get(health))
        .route("/widget/{name}", get(render_widget))
        .route("/search", get(search))
        .route("/track.gif", get(track))
        .layer(CompressionLayer::new().gzip(true).br(true))
        .layer(TraceLayer::new_for_http())
        .with_state(state);

    let addr: SocketAddr = config.bind;
    tracing::info!("soymutdb-core listening on {addr}");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .with_graceful_shutdown(shutdown_signal())
    .await?;
    Ok(())
}

async fn health() -> &'static str { "ok" }

async fn shutdown_signal() {
    let ctrl_c = async {
        tokio::signal::ctrl_c().await.expect("failed to install Ctrl+C handler");
    };
    #[cfg(unix)]
    let terminate = async {
        tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .expect("failed to install SIGTERM handler")
            .recv().await;
    };
    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();
    tokio::select! { _ = ctrl_c => {}, _ = terminate => {} }
    tracing::info!("shutdown signal received");
}
