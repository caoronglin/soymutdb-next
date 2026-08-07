//! Error types for the core service.

use axum::{http::StatusCode, response::IntoResponse, Json};
use serde_json::json;

#[derive(Debug, thiserror::Error)]
pub enum CoreError {
    #[error("not found: {0}")]
    NotFound(String),

    #[error("upstream error: {0}")]
    Upstream(String),

    #[error("cache error: {0}")]
    Cache(String),

    #[error("template error: {0}")]
    Template(String),

    #[error("bad request: {0}")]
    BadRequest(String),

    #[error("internal error: {0}")]
    Internal(String),
}

impl IntoResponse for CoreError {
    fn into_response(self) -> axum::response::Response {
        let (status, msg) = match &self {
            CoreError::NotFound(m) => (StatusCode::NOT_FOUND, m.clone()),
            CoreError::BadRequest(m) => (StatusCode::BAD_REQUEST, m.clone()),
            CoreError::Upstream(m) => (StatusCode::BAD_GATEWAY, m.clone()),
            _ => (StatusCode::INTERNAL_SERVER_ERROR, self.to_string()),
        };
        let body = Json(json!({ "error": msg }));
        (status, [("content-type", "application/json")], body).into_response()
    }
}

pub type Result<T> = std::result::Result<T, CoreError>;
