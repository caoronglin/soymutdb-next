// SoyMutDB Admin — Tauri v2 entry point
//
// Three-tier isolation:
//   - Web/public portal: SSG HTML in apps/web/dist/ (pure static, served by Nginx)
//   - API: FastAPI (apps/api) on server, port 8000
//   - Admin (this): native desktop app via Tauri.
//     - Loads the React admin SPA built to ../dist via the custom-asset protocol
//     - Proxies API calls to 127.0.0.1:8000 (intranet/localhost only per CSP)
//     - Provides native file-system access for bulk imports via Tauri commands
//     - No browser tab required: single native window
//
// The admin app NEVER exposes an HTTP listener. All network calls go through
// the Tauri IPC/HTTP client directly to the backend, eliminating the need for
// a separate admin browser window and reducing attack surface.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use tauri::Manager;
use tokio::sync::OnceCell;

// ---------------------------------------------------------------------------
// App state
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
struct AppState {
    api_base: String,
}

impl AppState {
    fn new() -> Self {
        // The admin expects a local FastAPI instance. In production deployments
        // this is reached via SSH tunnel or intranet. The CSP restricts connect
        // to localhost/127.0.0.1 only.
        let api_base = std::env::var("SOYMUTDB_API_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:8000".to_string());
        Self { api_base }
    }
}

static HTTP_CLIENT: OnceCell<reqwest::Client> = OnceCell::const_new();

async fn http_client() -> &'static reqwest::Client {
    HTTP_CLIENT
        .get_or_init(|| async {
            reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(30))
                .build()
                .expect("failed to build reqwest client")
        })
        .await
}

// ---------------------------------------------------------------------------
// Tauri commands (invoked from React via @tauri-apps/api/core invoke())
// ---------------------------------------------------------------------------

#[derive(Serialize)]
struct HealthResponse {
    ok: bool,
    latency_ms: u128,
    api_base: String,
}

#[tauri::command]
async fn api_health(state: tauri::State<'_, AppState>) -> Result<HealthResponse, String> {
    let start = std::time::Instant::now();
    let client = http_client().await;
    let url = format!("{}/api/v1/health", state.api_base);
    let ok = client
        .get(&url)
        .send()
        .await
        .map(|r| r.status().is_success())
        .unwrap_or(false);
    Ok(HealthResponse {
        ok,
        latency_ms: start.elapsed().as_millis(),
        api_base: state.api_base.clone(),
    })
}

#[tauri::command]
async fn api_proxy(
    state: tauri::State<'_, AppState>,
    path: String,
    method: Option<String>,
    body: Option<String>,
) -> Result<String, String> {
    let method = method.unwrap_or_else(|| "GET".to_string()).to_uppercase();
    let client = http_client().await;
    let url = format!(
        "{}/{}",
        state.api_base.trim_end_matches('/'),
        path.trim_start_matches('/')
    );

    let mut req = match method.as_str() {
        "POST" => client.post(&url),
        "PUT" => client.put(&url),
        "PATCH" => client.patch(&url),
        "DELETE" => client.delete(&url),
        _ => client.get(&url),
    };

    if let Some(b) = body {
        req = req.header("Content-Type", "application/json").body(b);
    }

    let resp = req.send().await.map_err(|e| format!("request failed: {e}"))?;
    let text = resp.text().await.map_err(|e| format!("read failed: {e}"))?;
    Ok(text)
}

#[derive(Serialize, Deserialize, Debug)]
struct ImportResult {
    file: String,
    records: u64,
    error: Option<String>,
}

#[tauri::command]
async fn import_variants_csv(
    state: tauri::State<'_, AppState>,
    file_path: String,
) -> Result<ImportResult, String> {
    let path = PathBuf::from(&file_path);
    if !path.exists() {
        return Err(format!("file not found: {file_path}"));
    }
    let content = tokio::fs::read_to_string(&path)
        .await
        .map_err(|e| format!("read failed: {e}"))?;

    let client = http_client().await;
    let url = format!("{}/api/v1/admin/imports/variants", state.api_base);
    let resp = client
        .post(&url)
        .header("Content-Type", "text/csv")
        .body(content)
        .send()
        .await
        .map_err(|e| format!("upload failed: {e}"))?;

    let records = resp
        .json::<serde_json::Value>()
        .await
        .ok()
        .and_then(|v| v.get("records_imported").and_then(|x| x.as_u64()))
        .unwrap_or(0);

    Ok(ImportResult {
        file: path.file_name().unwrap_or_default().to_string_lossy().to_string(),
        records,
        error: None,
    })
}

#[tauri::command]
fn get_app_info(app: tauri::AppHandle) -> serde_json::Value {
    serde_json::json!({
        "name": app.package_info().name.to_string(),
        "version": app.package_info().version.to_string(),
        "os": std::env::consts::OS,
        "arch": std::env::consts::ARCH,
    })
}

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .setup(|app| {
            app.manage(AppState::new());

            #[cfg(debug_assertions)]
            {
                let window = app.get_webview_window("main").unwrap();
                window.open_devtools();
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            api_health,
            api_proxy,
            import_variants_csv,
            get_app_info,
        ])
        .run(tauri::generate_context!())
        .expect("error while running SoyMutDB Admin");
}

fn main() {
    run()
}
