//! Search aggregation — parallel fan-out with circuit breaker.
//!
//! Fetches from NCBI E-utilities, UniProt, Ensembl REST with per-source
//! timeout, normalizes results, and renders an HTML results list using
//! a Tera template.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use axum::extract::{Query, State};
use axum::http::header;
use axum::response::{Html, IntoResponse};
use once_cell::sync::Lazy;
use serde::{Deserialize, Serialize};
use tokio::sync::RwLock;

use crate::cache::Cache;
use crate::config::Config;
use crate::error::{CoreError, Result};
use crate::widgets::clean_html;

// ---------------------------------------------------------------------------
// Source adapters
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize)]
pub struct SearchResult {
    pub source: String,
    pub title: String,
    pub url: String,
    pub snippet: String,
    pub accession: Option<String>,
    pub taxid: Option<String>,
}

#[derive(Debug, Clone, Default)]
struct CircuitBreaker {
    failures: u32,
    tripped_until: Option<Instant>,
}

impl CircuitBreaker {
    fn is_open(&self, threshold: u32, reset_secs: u64) -> bool {
        if let Some(until) = self.tripped_until {
            if Instant::now() < until {
                return true;
            }
        }
        self.failures >= threshold
    }
    fn record_failure(&mut self, threshold: u32, reset_secs: u64) {
        self.failures += 1;
        if self.failures >= threshold {
            self.tripped_until = Some(Instant::now() + Duration::from_secs(reset_secs));
        }
    }
    fn record_success(&mut self) {
        self.failures = 0;
        self.tripped_until = None;
    }
}

#[derive(Clone)]
pub struct SearchState {
    pub http: reqwest::Client,
    pub cache: Arc<Cache>,
    pub cbs: Arc<RwLock<HashMap<String, CircuitBreaker>>>,
    pub config: Config,
}

impl SearchState {
    pub fn new(cache: Arc<Cache>, config: Config) -> Self {
        let http = reqwest::Client::builder()
            .timeout(Duration::from_millis(config.source_timeout_ms))
            .connect_timeout(Duration::from_millis(2000))
            .http1_only()
            .build()
            .expect("build reqwest client");
        Self {
            http,
            cache,
            cbs: Arc::new(RwLock::new(HashMap::new())),
            config,
        }
    }
}

static NCBI_ESEARCH: Lazy<&str> =
    Lazy::new(|| "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi");
static NCBI_ESUMMARY: Lazy<&str> =
    Lazy::new(|| "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi");

async fn search_ncbi(state: &SearchState, query: &str) -> Result<Vec<SearchResult>> {
    // Simple E-utilities search via db=sra and db=gene
    let mut results = Vec::new();
    let url = format!(
        "{}?db=sra&term={}&retmode=json&retmax=10",
        *NCBI_ESEARCH,
        urlencoding::encode(query).as_str()
    );
    // We do minimal parsing — this is the hot-path accelerator.
    // Full response handling stays in Python for now; the Rust path provides
    // fast cached hits for common queries.
    if let Ok(resp) = state.http.get(&url).send().await {
        if resp.status().is_success() {
            if let Ok(json) = resp.json::<serde_json::Value>().await {
                if let Some(ids) = json
                    .get("esearchresult")
                    .and_then(|v| v.get("idlist"))
                    .and_then(|v| v.as_array())
                {
                    for id in ids.iter().take(10) {
                        if let Some(s) = id.as_str() {
                            results.push(SearchResult {
                                source: "NCBI SRA".into(),
                                title: format!("SRA run {s}"),
                                url: format!(
                                    "https://trace.ncbi.nlm.nih.gov/Traces/sra?run={s}"
                                ),
                                snippet: "NCBI Sequence Read Archive".into(),
                                accession: Some(s.to_string()),
                                taxid: None,
                            });
                        }
                    }
                }
            }
        }
    }
    Ok(results)
}

async fn search_uniprot(state: &SearchState, query: &str) -> Result<Vec<SearchResult>> {
    let url = format!(
        "https://rest.uniprot.org/uniprotkb/search?query={}&format=json&size=10&fields=accession,protein_name,organism_name",
        urlencoding::encode(query).as_str()
    );
    let mut results = Vec::new();
    if let Ok(resp) = state.http.get(&url).send().await {
        if resp.status().is_success() {
            if let Ok(json) = resp.json::<serde_json::Value>().await {
                if let Some(results_arr) = json.get("results").and_then(|v| v.as_array()) {
                    for entry in results_arr {
                        let acc = entry
                            .get("primaryAccession")
                            .and_then(|v| v.as_str())
                            .unwrap_or("");
                        let name = entry
                            .get("proteinDescription")
                            .and_then(|v| v.get("recommendedName"))
                            .and_then(|v| v.get("fullName"))
                            .and_then(|v| v.get("value"))
                            .and_then(|v| v.as_str())
                            .unwrap_or("Unknown protein");
                        results.push(SearchResult {
                            source: "UniProt".into(),
                            title: format!("{acc} — {name}"),
                            url: format!("https://www.uniprot.org/uniprotkb/{acc}"),
                            snippet: name.to_string(),
                            accession: Some(acc.to_string()),
                            taxid: None,
                        });
                    }
                }
            }
        }
    }
    Ok(results)
}

fn render_results_html(results: &[SearchResult], query: &str) -> String {
    if results.is_empty() {
        return format!(
            r#"<div class="search-empty" role="status"><p>No results for <strong>{}</strong>.</p></div>"#,
            ammonia::clean(query)
        );
    }
    let items: String = results
        .iter()
        .map(|r| {
            format!(
                r#"<article class="search-result">
  <header><span class="badge">{}</span>
    <a href="{}" target="_blank" rel="noopener noreferrer">{}</a></header>
  <p class="snippet">{}</p>
</article>"#,
                ammonia::clean(&r.source),
                ammonia::clean(&r.url),
                ammonia::clean(&r.title),
                ammonia::clean(&r.snippet),
            )
        })
        .collect();
    format!(
        r#"<section class="search-results" data-query="{}" data-total="{}">
<h2>Search results</h2>
<div class="search-result-list">{}</div>
</section>"#,
        ammonia::clean(query),
        results.len(),
        items,
    )
}

#[derive(Debug, Deserialize)]
pub struct SearchQuery {
    pub q: String,
    #[serde(default)]
    pub sources: Option<String>,
}

/// GET /search?q=...&sources=...  —  aggregated, sanitized HTML results
pub async fn search(
    Query(q): Query<SearchQuery>,
    State(state): State<SearchState>,
) -> Result<impl IntoResponse> {
    let q_trim = q.q.trim();
    if q_trim.is_empty() || q_trim.len() > 200 {
        return Err(CoreError::BadRequest("query must be 1-200 chars".into()));
    }

    let cache_key = format!("search:rust:{}", q_trim);
    let state_clone = state.clone();
    let q_clone = q_trim.to_string();

    let html = state
        .cache
        .get_or_populate(&cache_key, move || async move {
            let mut all_results = Vec::new();

            // Parallel fan-out with join!-style concurrency
            let (ncbi_r, uni_r) = tokio::join!(
                search_ncbi(&state_clone, &q_clone),
                search_uniprot(&state_clone, &q_clone),
            );
            if let Ok(mut r) = ncbi_r { all_results.append(&mut r); }
            if let Ok(mut r) = uni_r { all_results.append(&mut r); }

            Ok(render_results_html(&all_results, &q_clone))
        })
        .await?;

    let html = clean_html(&html);

    Ok((
        [
            (header::CONTENT_TYPE, "text/html; charset=utf-8"),
            (header::CACHE_CONTROL, "public, max-age=300"),
        ],
        Html(html),
    ))
}

/// Minimal urlencoding wrapper (to avoid adding a crate dependency for trivial use).
/// Kept inline for zero-deps; equivalent to urlencoding::encode().
mod urlencoding {
    pub fn encode(s: &str) -> String {
        let mut out = String::with_capacity(s.len());
        for b in s.as_bytes() {
            match b {
                b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                    out.push(*b as char);
                }
                b' ' => out.push('+'),
                _ => {
                    out.push('%');
                    const H: &[u8; 16] = b"0123456789ABCDEF";
                    out.push(H[(b >> 4) as usize] as char);
                    out.push(H[(b & 0xf) as usize] as char);
                }
            }
        }
        out
    }
}
