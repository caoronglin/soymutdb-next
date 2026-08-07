//! Widget rendering — Tera templates + ammonia HTML sanitization.
//!
//! Mirrors the Python API contract: GET /widget/{name} returns sanitized HTML.
//! Widget definitions are loaded from templates/ and rendered with JSON params.

use std::collections::{HashMap, hash_map::DefaultHasher};
use std::hash::{Hash, Hasher};
use std::sync::Arc;

use axum::extract::{Path, Query, State};
use axum::http::header;
use axum::response::{Html, IntoResponse};
use serde::Deserialize;
use tera::{Context, Tera};

use crate::cache::Cache;
use crate::error::{CoreError, Result};

#[derive(Clone)]
pub struct WidgetState {
    pub tera: Arc<Tera>,
    pub cache: Arc<Cache>,
}

#[derive(Debug, Deserialize)]
pub struct WidgetParams {
    pub params: Option<String>,
}

/// Allowed HTML tags/attributes for widget output (ammonia whitelist).
/// Mirrors bleach.clean() defaults plus semantic scientific markup.
fn clean_html(raw: &str) -> String {
    ammonia::Builder::default()
        .add_tags([
            "section", "article", "header", "footer", "nav", "figure", "figcaption",
            "main", "aside", "details", "summary", "data", "time", "mark",
            "dl", "dt", "dd",
        ])
        .add_generic_attributes(["id", "class", "role", "aria-label", "aria-hidden", "data-widget"])
        .add_tag_attributes("a", ["href", "rel", "target"])
        .add_tag_attributes("img", ["src", "alt", "width", "height", "loading"])
        .add_tag_attributes("table", ["data-sortable"])
        .add_tag_attributes("th", ["scope", "aria-sort"])
        .clean(raw)
        .to_string()
}

fn load_templates() -> Tera {
    // Load templates from the Python widget templates directory at startup.
    // In production the templates are shared; if unavailable fall back to minimal built-ins.
    let mut tera = Tera::default();
    let template_paths = [
        "/home/claude-user/apps/api/app/widgets/templates/**/*.html",
        "../apps/api/app/widgets/templates/**/*.html",
        "apps/api/app/widgets/templates/**/*.html",
    ];
    let mut loaded = false;
    for pattern in &template_paths {
        if let Ok(mut t) = Tera::new(pattern) {
            t.autoescape_on(vec![".html", ".htm", ".xml"]);
            tera = t;
            loaded = true;
            tracing::info!("Loaded widget templates from {pattern}");
            break;
        }
    }
    if !loaded {
        tracing::warn!("No external widget templates found; using built-in fallback templates");
        // Register minimal fallback templates
        tera.add_raw_template("error.html", include_str!("../templates/error.html"))
            .ok();
        tera.add_raw_template("sra_run.html", include_str!("../templates/sra_run_fallback.html"))
            .ok();
    }
    tera.autoescape_on(vec![".html", ".htm", ".xml"]);
    tera
}

impl WidgetState {
    pub async fn new(cache: Arc<Cache>) -> Self {
        let tera = Arc::new(load_templates());
        Self { tera, cache }
    }

    pub fn render(&self, name: &str, params: &serde_json::Value) -> Result<String> {
        let template_name = format!("{name}.html");
        let mut ctx = Context::new();
        if let Some(obj) = params.as_object() {
            for (k, v) in obj {
                ctx.insert(k, v);
            }
        }
        let raw = self
            .tera
            .render(&template_name, &ctx)
            .map_err(|e| CoreError::Template(format!("{e:#}")))?;
        Ok(clean_html(&raw))
    }
}

/// GET /widget/:name?params={...}  —  returns sanitized HTML fragment
pub async fn render_widget(
    Path(name): Path<String>,
    Query(q): Query<WidgetParams>,
    State(state): State<WidgetState>,
) -> Result<impl IntoResponse> {
    // Validate widget name to prevent path traversal
    if !name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-') {
        return Err(CoreError::BadRequest("invalid widget name".into()));
    }

    let params: serde_json::Value = q
        .params
        .as_deref()
        .map(|s| serde_json::from_str(s).unwrap_or(serde_json::Value::Null))
        .unwrap_or(serde_json::Value::Null);

    let params_hash = {
        let mut h = std::collections::hash_map::DefaultHasher::new();
        use std::hash::{Hash, Hasher};
        params.to_string().hash(&mut h);
        h.finish()
    };
    let cache_key = format!("widget:rust:{}:{:x}", name, params_hash);

    let state_clone = state.clone();
    let name_clone = name.clone();
    let html = state
        .cache
        .get_or_populate(&cache_key, move || async move {
            state_clone.render(&name_clone, &params)
        })
        .await?;

    Ok((
        [
            (header::CONTENT_TYPE, "text/html; charset=utf-8"),
            (header::CACHE_CONTROL, "public, max-age=60"),
            (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
        ],
        Html(html),
    ))
}
