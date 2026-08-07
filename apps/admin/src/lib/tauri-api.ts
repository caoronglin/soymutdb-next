/**
 * Tauri-aware API client for the Admin console.
 *
 * Three-tier isolation:
 *   - Web/public portal (apps/web):     pure static, NO admin access
 *   - Web Admin (localhost):           Nginx allowlist on /admin/, fetches API via fetch()
 *   - Tauri Desktop (native):          native window, uses Tauri invoke() IPC
 *
 * Auto-detects runtime: checks for window.__TAURI_INTERNALS__. If running in
 * Tauri, uses invoke() for backend calls and Tauri plugins for file dialogs.
 * In browser mode, uses plain fetch() against http://127.0.0.1:8000.
 *
 * Tauri packages are optionalDependencies and imported lazily so the web
 * build works without installing the @tauri-apps/* npm packages or Rust toolchain.
 */

// Runtime detection — Tauri injects __TAURI_INTERNALS__ on the window object
const isTauri = typeof window !== 'undefined' && !!(window as any).__TAURI_INTERNALS__;

export function isDesktopMode(): boolean {
  return isTauri;
}

function apiBaseUrl(): string {
  return (import.meta as any).env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
}

/**
 * Generic admin API request. Routes through Tauri IPC in desktop mode, fetch otherwise.
 */
export async function adminFetch<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  if (isTauri) {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const method = (options.method || 'GET').toUpperCase();
      let body: string | undefined;
      if (options.body && typeof options.body === 'string') {
        body = options.body;
      } else if (options.body) {
        body = JSON.stringify(options.body);
      }
      const text = await invoke<string>('api_proxy', {
        path: path.startsWith('/') ? path.slice(1) : path,
        method,
        body,
      });
      try {
        return JSON.parse(text) as T;
      } catch {
        return text as unknown as T;
      }
    } catch (e) {
      // Fall through to fetch if Tauri invoke fails
      console.warn('[tauri-api] invoke failed, falling back to fetch:', e);
    }
  }

  // Browser mode
  const url = `${apiBaseUrl()}${path.startsWith('/') ? path : `/${path}`}`;
  const res = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    throw new Error(`Admin API ${res.status}: ${await res.text().catch(() => res.statusText)}`);
  }
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return res.json();
  return res.text() as unknown as T;
}

/** Open a file dialog and return the selected path (desktop) or filename (web). */
export async function pickCsvFile(): Promise<string | null> {
  if (isTauri) {
    try {
      const { open } = await import('@tauri-apps/plugin-dialog');
      const selected = await open({
        multiple: false,
        filters: [{ name: 'CSV', extensions: ['csv'] }],
      });
      return typeof selected === 'string' ? selected : null;
    } catch (e) {
      console.warn('[tauri-api] dialog failed:', e);
    }
  }
  // Browser fallback
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.csv,text/csv';
    input.onchange = () => {
      const f = input.files?.[0];
      if (f) {
        const reader = new FileReader();
        reader.onload = () => {
          (window as any).__soymutdb_pending_csv = reader.result as string;
          (window as any).__soymutdb_pending_csv_name = f.name;
          resolve(f.name);
        };
        reader.readAsText(f);
      } else resolve(null);
    };
    input.click();
  });
}

/** Open external URL in system browser (desktop) or new tab (web). */
export async function openExternal(url: string): Promise<void> {
  if (isTauri) {
    try {
      const { open: openShell } = await import('@tauri-apps/plugin-shell');
      await openShell(url);
      return;
    } catch (e) {
      console.warn('[tauri-api] shell open failed:', e);
    }
  }
  window.open(url, '_blank', 'noopener,noreferrer');
}

/** Backend health check. */
export async function checkHealth(): Promise<{ ok: boolean; latency_ms: number; api_base: string }> {
  if (isTauri) {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      return await invoke('api_health');
    } catch {
      // fall through
    }
  }
  const start = performance.now();
  try {
    const res = await fetch(`${apiBaseUrl()}/api/v1/health`, { method: 'GET' });
    return { ok: res.ok, latency_ms: Math.round(performance.now() - start), api_base: apiBaseUrl() };
  } catch {
    return { ok: false, latency_ms: Math.round(performance.now() - start), api_base: apiBaseUrl() };
  }
}

/** Runtime app info. */
export async function getAppInfo(): Promise<Record<string, string>> {
  if (isTauri) {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      return await invoke('get_app_info');
    } catch {
      // fall through
    }
  }
  return {
    name: '@soymutdb/admin',
    version: '2.0.0',
    mode: 'web',
    os: (navigator as any).userAgentData?.platform || navigator.platform,
  };
}
