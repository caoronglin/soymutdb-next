package static

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func writeFile(t *testing.T, target, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
		t.Fatalf("mkdir %s: %v", filepath.Dir(target), err)
	}
	if err := os.WriteFile(target, []byte(content), 0o644); err != nil {
		t.Fatalf("write %s: %v", target, err)
	}
}

const indexDocument = "<!DOCTYPE html>\n<title>SoyMutDB Admin</title>\n<div id=\"root\"></div>\n"

func fixture(t *testing.T) *Handler {
	t.Helper()
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "index.html"), indexDocument)
	writeFile(t, filepath.Join(dir, "assets", "app.abc12345.js"), "console.log('admin');")
	writeFile(t, filepath.Join(dir, "6460.90cf9d27.chunk.css"), "body{color:#333}")
	writeFile(t, filepath.Join(dir, "fonts", "harmony.woff2"), "wOF2")
	writeFile(t, filepath.Join(dir, "favicon.svg"), "<svg/>")
	writeFile(t, filepath.Join(dir, "_headers"), "/*\n  X-Test: 1\n")
	handler, err := New(dir)
	if err != nil {
		t.Fatalf("New(%s): %v", dir, err)
	}
	return handler
}

func TestRoutingRules(t *testing.T) {
	handler := fixture(t)

	cases := []struct {
		name        string
		method      string
		path        string
		wantStatus  int
		wantBody    string
		wantType    string
		wantCache   string
		doesNotWant string
	}{
		{
			name:       "root serves the document",
			method:     http.MethodGet,
			path:       "/",
			wantStatus: http.StatusOK,
			wantBody:   indexDocument,
			wantType:   "text/html; charset=utf-8",
			wantCache:  "no-cache",
		},
		{
			name:       "unknown spa route falls back to the document",
			method:     http.MethodGet,
			path:       "/releases/42",
			wantStatus: http.StatusOK,
			wantBody:   indexDocument,
			wantType:   "text/html; charset=utf-8",
			wantCache:  "no-cache",
		},
		{
			name:        "missing hashed asset is a 404, not the document",
			method:      http.MethodGet,
			path:        "/assets/does-not-exist.js",
			wantStatus:  http.StatusNotFound,
			wantBody:    `{"detail":"Not Found"}`,
			wantType:    "application/json",
			doesNotWant: "<html",
		},
		{
			name:       "missing extensionless path under assets is a 404",
			method:     http.MethodGet,
			path:       "/assets/missing",
			wantStatus: http.StatusNotFound,
		},
		{
			name:       "missing file with an extension elsewhere is a 404",
			method:     http.MethodGet,
			path:       "/preload_helper.deadbeef.js",
			wantStatus: http.StatusNotFound,
		},
		{
			name:       "hashed asset is immutable",
			method:     http.MethodGet,
			path:       "/assets/app.abc12345.js",
			wantStatus: http.StatusOK,
			wantBody:   "console.log('admin');",
			wantType:   "text/javascript; charset=utf-8",
			wantCache:  "public, max-age=31536000, immutable",
		},
		{
			name:       "root level hashed chunk is immutable too",
			method:     http.MethodGet,
			path:       "/6460.90cf9d27.chunk.css",
			wantStatus: http.StatusOK,
			wantType:   "text/css; charset=utf-8",
			wantCache:  "public, max-age=31536000, immutable",
		},
		{
			name:       "font has a short cache and a font mime type",
			method:     http.MethodGet,
			path:       "/fonts/harmony.woff2",
			wantStatus: http.StatusOK,
			wantType:   "font/woff2",
			wantCache:  "public, max-age=3600",
		},
		{
			name:       "svg gets the svg mime type",
			method:     http.MethodGet,
			path:       "/favicon.svg",
			wantStatus: http.StatusOK,
			wantType:   "image/svg+xml",
		},
		{
			name:       "explicit index request revalidates",
			method:     http.MethodGet,
			path:       "/index.html",
			wantStatus: http.StatusOK,
			wantBody:   indexDocument,
			wantCache:  "no-cache",
		},
		{
			name:       "head is allowed and bodyless",
			method:     http.MethodHead,
			path:       "/index.html",
			wantStatus: http.StatusOK,
		},
		{
			name:       "post is rejected",
			method:     http.MethodPost,
			path:       "/",
			wantStatus: http.StatusMethodNotAllowed,
			wantBody:   `{"detail":"Method Not Allowed"}`,
		},
		{
			name:        "traversal cannot escape the artifact",
			method:      http.MethodGet,
			path:        "/../../etc/passwd",
			wantStatus:  http.StatusOK,
			wantBody:    indexDocument,
			doesNotWant: "root:",
		},
		{
			name:        "nested traversal cannot escape the artifact",
			method:      http.MethodGet,
			path:        "/assets/../../../etc/passwd",
			wantStatus:  http.StatusOK,
			wantBody:    indexDocument,
			doesNotWant: "root:",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			recorder := httptest.NewRecorder()
			handler.ServeHTTP(recorder, httptest.NewRequest(tc.method, tc.path, nil))

			if recorder.Code != tc.wantStatus {
				t.Fatalf("status = %d, want %d (body %q)", recorder.Code, tc.wantStatus, recorder.Body.String())
			}
			if tc.wantBody != "" && !strings.Contains(recorder.Body.String(), tc.wantBody) {
				t.Fatalf("body = %q, want it to contain %q", recorder.Body.String(), tc.wantBody)
			}
			if tc.doesNotWant != "" && strings.Contains(recorder.Body.String(), tc.doesNotWant) {
				t.Fatalf("body = %q, must not contain %q", recorder.Body.String(), tc.doesNotWant)
			}
			if tc.wantType != "" {
				if got := recorder.Header().Get("Content-Type"); got != tc.wantType {
					t.Fatalf("content-type = %q, want %q", got, tc.wantType)
				}
			}
			if tc.wantCache != "" {
				if got := recorder.Header().Get("Cache-Control"); got != tc.wantCache {
					t.Fatalf("cache-control = %q, want %q", got, tc.wantCache)
				}
			}
			if got := recorder.Header().Get("X-Content-Type-Options"); got != "nosniff" {
				t.Fatalf("x-content-type-options = %q, want nosniff", got)
			}
			if tc.wantType == "text/html; charset=utf-8" {
				if got := recorder.Header().Get("X-Frame-Options"); got != "DENY" {
					t.Fatalf("x-frame-options = %q, want DENY", got)
				}
			}
		})
	}
}

func TestNewFailsClosedWithoutArtifact(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "absent")
	if _, err := New(missing); err == nil {
		t.Fatal("New accepted a directory that does not exist")
	}

	withoutIndex := t.TempDir()
	if _, err := New(withoutIndex); err == nil {
		t.Fatal("New accepted an artifact without index.html")
	}

	file := filepath.Join(t.TempDir(), "artifact")
	writeFile(t, file, "not a directory")
	if _, err := New(file); err == nil {
		t.Fatal("New accepted a file as the artifact root")
	}
}

func TestConditionalRequestUsesLastModified(t *testing.T) {
	handler := fixture(t)

	first := httptest.NewRecorder()
	handler.ServeHTTP(first, httptest.NewRequest(http.MethodGet, "/assets/app.abc12345.js", nil))
	modified := first.Header().Get("Last-Modified")
	if modified == "" {
		t.Fatal("missing Last-Modified")
	}

	request := httptest.NewRequest(http.MethodGet, "/assets/app.abc12345.js", nil)
	request.Header.Set("If-Modified-Since", modified)
	second := httptest.NewRecorder()
	handler.ServeHTTP(second, request)
	if second.Code != http.StatusNotModified {
		t.Fatalf("status = %d, want 304", second.Code)
	}
}

func TestRangeRequestIsServed(t *testing.T) {
	handler := fixture(t)
	request := httptest.NewRequest(http.MethodGet, "/assets/app.abc12345.js", nil)
	request.Header.Set("Range", "bytes=0-6")
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusPartialContent {
		t.Fatalf("status = %d, want 206", recorder.Code)
	}
	if got := recorder.Body.String(); got != "console" {
		t.Fatalf("body = %q, want %q", got, "console")
	}
}

func TestContentTypeTableCoversDocumentedExtensions(t *testing.T) {
	want := map[string]string{
		"/app.js":       "text/javascript; charset=utf-8",
		"/app.mjs":      "text/javascript; charset=utf-8",
		"/app.css":      "text/css; charset=utf-8",
		"/logo.svg":     "image/svg+xml",
		"/font.woff2":   "font/woff2",
		"/data.json":    "application/json",
		"/index.html":   "text/html; charset=utf-8",
		"/mystery.bin":  "application/octet-stream",
		"/no-extension": "application/octet-stream",
	}
	for path, expected := range want {
		if got := contentType(path); got != expected {
			t.Fatalf("contentType(%q) = %q, want %q", path, got, expected)
		}
	}
}
