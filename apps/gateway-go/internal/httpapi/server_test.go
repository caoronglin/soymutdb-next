package httpapi

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/json"
	"errors"
	"io"
	"maps"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"soymutdb.local/gateway/internal/apiproxy"
	"soymutdb.local/gateway/internal/ratelimit"
	"soymutdb.local/gateway/internal/readmodel"
	"soymutdb.local/gateway/internal/stats"
)

type fakeSource struct {
	payload stats.Homepage
	err     error
}

func (f fakeSource) Homepage(context.Context) (stats.Homepage, error) {
	return f.payload, f.err
}

type fakeReadSource struct {
	items           []readmodel.Assembly
	chromosomes     []readmodel.Chromosome
	news            []readmodel.News
	newsPage        readmodel.NewsList
	publications    []readmodel.Publication
	staticPages     []readmodel.StaticPage
	downloadFiles   []readmodel.DownloadFile
	trackCategories []readmodel.TrackCategory
	releaseID       *int64
	active          readmodel.ActiveRelease
	err             error
	calls           int
}

func (f *fakeReadSource) Assemblies(context.Context) ([]readmodel.Assembly, error) {
	f.calls++
	return f.items, f.err
}

func (f *fakeReadSource) Chromosomes(_ context.Context, _ int64) ([]readmodel.Chromosome, error) {
	f.calls++
	if f.err != nil {
		return nil, f.err
	}
	return f.chromosomes, nil
}

func (f *fakeReadSource) ActiveRelease(context.Context) (readmodel.ActiveRelease, error) {
	f.calls++
	return f.active, f.err
}

func (f *fakeReadSource) News(context.Context, int) ([]readmodel.News, error) {
	f.calls++
	if f.err != nil {
		return nil, f.err
	}
	return f.news, nil
}

func (f *fakeReadSource) Publications(context.Context, int) ([]readmodel.Publication, error) {
	f.calls++
	if f.err != nil {
		return nil, f.err
	}
	return f.publications, nil
}

func (f *fakeReadSource) StaticPages(context.Context) ([]readmodel.StaticPage, error) {
	f.calls++
	if f.err != nil {
		return nil, f.err
	}
	return f.staticPages, nil
}

func (f *fakeReadSource) DownloadFiles(context.Context, int64, *string) ([]readmodel.DownloadFile, error) {
	f.calls++
	if f.err != nil {
		return nil, f.err
	}
	return f.downloadFiles, nil
}

func (f *fakeReadSource) TrackCategories(context.Context) ([]readmodel.TrackCategory, error) {
	f.calls++
	if f.err != nil {
		return nil, f.err
	}
	return f.trackCategories, nil
}

func (f *fakeReadSource) PublishedReleaseID(context.Context) (*int64, error) {
	f.calls++
	if f.err != nil {
		return nil, f.err
	}
	return f.releaseID, nil
}

func (f *fakeReadSource) NewsPage(_ context.Context, _ *string, _, _ int) (readmodel.NewsList, error) {
	f.calls++
	if f.err != nil {
		return readmodel.NewsList{}, f.err
	}
	return f.newsPage, nil
}

// adminIndex is larger than the compression threshold, like the real document
// (which carries the CSP meta tag and the preload links).
var adminIndex = `<!DOCTYPE html><html><head><title>SoyMutDB Admin</title>` +
	`<!--` + strings.Repeat("shell", 200) + `-->` +
	`</head><body><div id="root"></div>` +
	`<script src="/assets/app.abc12345.js" defer></script></body></html>`

// writeFile creates a fixture file, including its parent directories.
func writeFile(t *testing.T, target, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
		t.Fatalf("mkdir %s: %v", filepath.Dir(target), err)
	}
	if err := os.WriteFile(target, []byte(content), 0o644); err != nil {
		t.Fatalf("write %s: %v", target, err)
	}
}

// artifact builds a minimal admin artifact: the document, one hashed chunk and
// one font, which is enough to exercise every routing and caching rule.
func artifact(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "index.html"), adminIndex)
	writeFile(t, filepath.Join(dir, "assets", "app.abc12345.js"), strings.Repeat("console.log('admin');\n", 32))
	writeFile(t, filepath.Join(dir, "fonts", "harmony.woff2"), "wOF2")
	return dir
}

// upstream is a test Python API with the readiness endpoint the gateway probes.
func upstream(t *testing.T) *httptest.Server {
	t.Helper()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/health/ready" {
			w.WriteHeader(http.StatusOK)
			_, _ = io.WriteString(w, `{"status":"ok"}`)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("X-Upstream-Path", r.URL.Path)
		_, _ = io.WriteString(w, `{"proxied":true}`)
	}))
	t.Cleanup(server.Close)
	return server
}

type testServerOptions struct {
	source   StatsSource
	reads    ReadSource
	upstream string
	artifact string
	limiter  *ratelimit.Limiter
	timeout  time.Duration
}

func newTestHandler(t *testing.T, options testServerOptions) http.Handler {
	t.Helper()
	if options.source == nil {
		options.source = fakeSource{}
	}
	if options.upstream == "" {
		options.upstream = upstream(t).URL
	}
	if options.artifact == "" {
		options.artifact = artifact(t)
	}
	if options.timeout <= 0 {
		options.timeout = 2 * time.Second
	}
	parsed, err := url.Parse(options.upstream)
	if err != nil {
		t.Fatalf("parse upstream: %v", err)
	}
	server, err := New(Config{
		Stats:        options.source,
		Reads:        options.reads,
		QueryTimeout: time.Second,
		StaticDir:    options.artifact,
		Upstream:     &apiproxy.Options{Upstream: parsed, Timeout: options.timeout},
		RateLimit:    options.limiter,
	})
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	return server.Handler()
}

func TestRouting(t *testing.T) {
	handler := newTestHandler(t, testServerOptions{})

	cases := []struct {
		name       string
		method     string
		path       string
		wantStatus int
		wantBody   string
	}{
		{name: "health", method: http.MethodGet, path: "/healthz", wantStatus: http.StatusOK, wantBody: `"status":"ok"`},
		{name: "root document", method: http.MethodGet, path: "/", wantStatus: http.StatusOK, wantBody: "SoyMutDB Admin"},
		{name: "spa route", method: http.MethodGet, path: "/releases/7/variants", wantStatus: http.StatusOK, wantBody: "SoyMutDB Admin"},
		{name: "missing asset is 404", method: http.MethodGet, path: "/assets/gone.js", wantStatus: http.StatusNotFound, wantBody: `"detail":"Not Found"`},
		{name: "hashed asset", method: http.MethodGet, path: "/assets/app.abc12345.js", wantStatus: http.StatusOK, wantBody: "console.log"},
		{name: "stats is answered locally", method: http.MethodGet, path: "/api/v1/stats/homepage", wantStatus: http.StatusOK, wantBody: `"total_variants"`},
		{name: "api is proxied", method: http.MethodGet, path: "/api/v1/mutants", wantStatus: http.StatusOK, wantBody: `{"proxied":true}`},
		{name: "static rejects post", method: http.MethodPost, path: "/", wantStatus: http.StatusMethodNotAllowed},
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
		})
	}
}

// TestStatsRouteIsNotProxied pins the parity contract: the aggregate stays in
// the gateway, and only the rest of /api/* is forwarded.
func TestStatsRouteIsNotProxied(t *testing.T) {
	requests := make(chan string, 8)
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests <- r.URL.Path
		w.WriteHeader(http.StatusOK)
	}))
	defer api.Close()

	handler := newTestHandler(t, testServerOptions{upstream: api.URL})

	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/v1/stats/homepage", nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d", recorder.Code)
	}
	var payload map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("stats body is not JSON: %v", err)
	}
	if _, ok := payload["total_variants"]; !ok {
		t.Fatalf("stats body = %v", payload)
	}

	select {
	case path := <-requests:
		t.Fatalf("the stats route was proxied to %q", path)
	default:
	}
}

func TestCompressionOnArtifactAndProxy(t *testing.T) {
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/health/ready" {
			w.WriteHeader(http.StatusOK)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"items":["`+strings.Repeat("variant", 512)+`"]}`)
	}))
	defer api.Close()
	handler := newTestHandler(t, testServerOptions{upstream: api.URL})

	cases := []struct {
		name         string
		path         string
		accept       string
		wantEncoding string
		wantVary     bool
	}{
		{name: "document gzip", path: "/", accept: "gzip", wantEncoding: "gzip", wantVary: true},
		{name: "document identity", path: "/", accept: "", wantEncoding: "", wantVary: true},
		{name: "brotli only falls back to identity", path: "/", accept: "br", wantEncoding: "", wantVary: true},
		{name: "proxied json gzip", path: "/api/v1/mutants", accept: "gzip", wantEncoding: "gzip", wantVary: true},
		{name: "woff2 is not compressed", path: "/fonts/harmony.woff2", accept: "gzip", wantEncoding: "", wantVary: false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			request := httptest.NewRequest(http.MethodGet, tc.path, nil)
			if tc.accept != "" {
				request.Header.Set("Accept-Encoding", tc.accept)
			}
			recorder := httptest.NewRecorder()
			handler.ServeHTTP(recorder, request)

			if got := recorder.Header().Get("Content-Encoding"); got != tc.wantEncoding {
				t.Fatalf("content-encoding = %q, want %q", got, tc.wantEncoding)
			}
			if got := strings.Contains(recorder.Header().Get("Vary"), "Accept-Encoding"); got != tc.wantVary {
				t.Fatalf("vary = %q, want Accept-Encoding = %v", recorder.Header().Get("Vary"), tc.wantVary)
			}
			if tc.wantEncoding != "gzip" {
				return
			}
			reader, err := gzip.NewReader(bytes.NewReader(recorder.Body.Bytes()))
			if err != nil {
				t.Fatalf("gzip reader: %v", err)
			}
			if _, err := io.ReadAll(reader); err != nil {
				t.Fatalf("decode gzip body: %v", err)
			}
		})
	}
}

func TestProxiedResponsesAreStreamed(t *testing.T) {
	release := make(chan struct{})
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/health/ready" {
			w.WriteHeader(http.StatusOK)
			return
		}
		w.Header().Set("Content-Type", "text/plain")
		_, _ = io.WriteString(w, "first\n")
		w.(http.Flusher).Flush()
		<-release
		_, _ = io.WriteString(w, "second\n")
	}))
	defer api.Close()

	gateway := httptest.NewServer(newTestHandler(t, testServerOptions{upstream: api.URL}))
	defer gateway.Close()

	request, err := http.NewRequest(http.MethodGet, gateway.URL+"/api/v1/stream", nil)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	request.Header.Set("Accept-Encoding", "identity")
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatalf("do: %v", err)
	}
	defer func() { _ = response.Body.Close() }()

	first := make([]byte, len("first\n"))
	done := make(chan error, 1)
	go func() {
		_, err := io.ReadFull(response.Body, first)
		done <- err
	}()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("read first chunk: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("the first chunk was buffered until the upstream finished")
	}
	if string(first) != "first\n" {
		t.Fatalf("first chunk = %q", first)
	}
	close(release)
	rest, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatalf("read rest: %v", err)
	}
	if string(rest) != "second\n" {
		t.Fatalf("rest = %q", rest)
	}
}

func TestRateLimitOnlyAppliesToTheProxiedAPI(t *testing.T) {
	limiter, err := ratelimit.New(5, 1, 8)
	if err != nil {
		t.Fatalf("limiter: %v", err)
	}
	handler := newTestHandler(t, testServerOptions{limiter: limiter})

	for attempt, want := range []int{http.StatusOK, http.StatusTooManyRequests} {
		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/v1/mutants", nil))
		if recorder.Code != want {
			t.Fatalf("api attempt %d status = %d, want %d", attempt, recorder.Code, want)
		}
		if want == http.StatusTooManyRequests {
			if recorder.Header().Get("Retry-After") == "" {
				t.Fatal("429 without Retry-After")
			}
			var decoded map[string]string
			if err := json.Unmarshal(recorder.Body.Bytes(), &decoded); err != nil {
				t.Fatalf("429 body: %v", err)
			}
			if decoded["detail"] != "Too Many Requests" {
				t.Fatalf("429 detail = %q", decoded["detail"])
			}
		}
	}

	// Static assets keep being served while the API bucket is empty: one page
	// load fetches dozens of hashed files.
	for _, path := range []string{"/", "/assets/app.abc12345.js"} {
		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, path, nil))
		if recorder.Code != http.StatusOK {
			t.Fatalf("%s status = %d, want 200", path, recorder.Code)
		}
	}
}

func TestReadiness(t *testing.T) {
	t.Run("ready", func(t *testing.T) {
		handler := newTestHandler(t, testServerOptions{})
		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/readyz", nil))

		if recorder.Code != http.StatusOK {
			t.Fatalf("status = %d, want 200", recorder.Code)
		}
		var report readyReport
		if err := json.Unmarshal(recorder.Body.Bytes(), &report); err != nil {
			t.Fatalf("decode: %v", err)
		}
		if report.Status != "ready" {
			t.Fatalf("status = %q", report.Status)
		}
		if report.Checks["admin_artifact"] != "ok" || report.Checks["api_upstream"] != "ok" {
			t.Fatalf("checks = %v", report.Checks)
		}
	})

	t.Run("upstream unhealthy", func(t *testing.T) {
		api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(http.StatusServiceUnavailable)
		}))
		defer api.Close()

		handler := newTestHandler(t, testServerOptions{upstream: api.URL})
		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/readyz", nil))

		if recorder.Code != http.StatusServiceUnavailable {
			t.Fatalf("status = %d, want 503", recorder.Code)
		}
		var report readyReport
		if err := json.Unmarshal(recorder.Body.Bytes(), &report); err != nil {
			t.Fatalf("decode: %v", err)
		}
		if report.Status != "unready" || report.Checks["api_upstream"] == "ok" {
			t.Fatalf("report = %+v", report)
		}
		// The answer describes an outcome, never the upstream location.
		upstreamHost := strings.TrimPrefix(api.URL, "http://")
		if strings.Contains(recorder.Body.String(), upstreamHost) {
			t.Fatalf("readiness body leaked the upstream address: %q", recorder.Body.String())
		}
	})

	t.Run("artifact missing", func(t *testing.T) {
		dir := artifact(t)
		handler := newTestHandler(t, testServerOptions{artifact: dir})
		if err := os.Remove(filepath.Join(dir, "index.html")); err != nil {
			t.Fatalf("remove index: %v", err)
		}

		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/readyz", nil))
		if recorder.Code != http.StatusServiceUnavailable {
			t.Fatalf("status = %d, want 503", recorder.Code)
		}
		var report readyReport
		if err := json.Unmarshal(recorder.Body.Bytes(), &report); err != nil {
			t.Fatalf("decode: %v", err)
		}
		if report.Checks["admin_artifact"] != "missing" {
			t.Fatalf("checks = %v", report.Checks)
		}
	})

	t.Run("post is rejected", func(t *testing.T) {
		handler := newTestHandler(t, testServerOptions{})
		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodPost, "/readyz", nil))
		if recorder.Code != http.StatusMethodNotAllowed {
			t.Fatalf("status = %d, want 405", recorder.Code)
		}
	})
}

func TestProxyFailureIsMapped(t *testing.T) {
	api := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	upstreamURL := api.URL
	api.Close()

	handler := newTestHandler(t, testServerOptions{upstream: upstreamURL})
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/v1/mutants", nil))

	if recorder.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502", recorder.Code)
	}
	var decoded map[string]string
	if err := json.Unmarshal(recorder.Body.Bytes(), &decoded); err != nil {
		t.Fatalf("502 body: %v", err)
	}
	if decoded["detail"] != "Bad Gateway" {
		t.Fatalf("detail = %q", decoded["detail"])
	}
}

func TestHomepageReturnsPythonContract(t *testing.T) {
	date := "2026-01-02T03:04:05.123456Z"
	name := "v2026.01"
	handler := newTestHandler(t, testServerOptions{source: fakeSource{payload: stats.Homepage{
		TotalVariants:   5,
		SNPCount:        2,
		IndelCount:      1,
		SVCount:         1,
		GeneCount:       2,
		MutantLineCount: 2,
		ReleaseCount:    1,
		AssemblyCount:   1,
		SeedAccessions:  1,
		LastReleaseDate: &date,
		LastReleaseName: &name,
	}}})

	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/v1/stats/homepage", nil))

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", recorder.Code)
	}
	if got := recorder.Header().Get("Content-Type"); got != "application/json" {
		t.Fatalf("content-type = %q", got)
	}
	var body map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	wantKeys := []string{
		"total_variants", "snp_count", "indel_count", "sv_count", "gene_count",
		"mutant_line_count", "release_count", "assembly_count", "seed_accessions",
		"last_release_date", "last_release_name",
	}
	if len(body) != len(wantKeys) {
		t.Fatalf("keys = %v, want %v", body, wantKeys)
	}
	for _, key := range wantKeys {
		if _, ok := body[key]; !ok {
			t.Fatalf("missing key %q in %v", key, body)
		}
	}
	if body["last_release_date"] != date || body["last_release_name"] != name {
		t.Fatalf("release metadata = %v / %v", body["last_release_date"], body["last_release_name"])
	}
}

func TestHomepageZeroAggregateKeepsNullDates(t *testing.T) {
	handler := newTestHandler(t, testServerOptions{})

	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/v1/stats/homepage", nil))

	var body map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body["last_release_date"] != nil || body["last_release_name"] != nil {
		t.Fatalf("zero aggregate must keep null release metadata, got %v", body)
	}
	if body["total_variants"] != float64(0) {
		t.Fatalf("total_variants = %v", body["total_variants"])
	}
}

func TestHomepageDatabaseErrorIs503Detail(t *testing.T) {
	handler := newTestHandler(t, testServerOptions{source: fakeSource{err: errors.New("boom")}})

	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/v1/stats/homepage", nil))

	if recorder.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", recorder.Code)
	}
	var body map[string]string
	if err := json.Unmarshal(recorder.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body["detail"] == "" {
		t.Fatalf("missing detail: %v", body)
	}
}

// TestCachedBodiesMatchDocumentedShapes pins the answers that are rendered
// once at construction: they must stay the bytes the handlers used to encode.
func TestCachedBodiesMatchDocumentedShapes(t *testing.T) {
	parsed, err := url.Parse("http://127.0.0.1:8010")
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	server, err := New(Config{
		Stats:        fakeSource{},
		QueryTimeout: time.Second,
		StaticDir:    artifact(t),
		Upstream:     &apiproxy.Options{Upstream: parsed, Timeout: time.Second},
	})
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	cases := []struct {
		name string
		body []byte
		want map[string]string
	}{
		{
			name: "health",
			body: server.healthBody,
			want: map[string]string{"status": "ok", "service": "soymutdb-gateway"},
		},
		{
			name: "method not allowed",
			body: server.methodNotAllowedBody,
			want: map[string]string{"detail": "Method Not Allowed"},
		},
		{
			name: "homepage unavailable",
			body: server.unavailableBody,
			want: map[string]string{"detail": "Homepage statistics are unavailable"},
		},
	}
	for _, tc := range cases {
		var got map[string]string
		if err := json.Unmarshal(tc.body, &got); err != nil {
			t.Fatalf("%s body is not JSON: %v", tc.name, err)
		}
		if !maps.Equal(got, tc.want) {
			t.Fatalf("%s body = %v, want %v", tc.name, got, tc.want)
		}
		if !bytes.HasSuffix(tc.body, []byte("\n")) {
			t.Fatalf("%s body lost the encoder's trailing newline: %q", tc.name, tc.body)
		}
	}
}

func TestHealthAndMethodRejection(t *testing.T) {
	handler := newTestHandler(t, testServerOptions{})

	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/healthz", nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("health status = %d", recorder.Code)
	}

	recorder = httptest.NewRecorder()
	handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodPost, "/api/v1/stats/homepage", nil))
	if recorder.Code != http.StatusMethodNotAllowed {
		t.Fatalf("POST status = %d, want 405", recorder.Code)
	}
}

// The assembly route is served locally from PostgreSQL, not forwarded. These
// tests pin the routing boundary, the method check, and the fail-closed answer
// when the store cannot read: a query failure must never look like "nothing is
// published" (which is a legitimate empty list).
func TestAssembliesRoute(t *testing.T) {
	reads := &fakeReadSource{items: []readmodel.Assembly{
		{ID: "1", Name: "Gmax_880_v6.0", Species: "Glycine max", Version: "v6.0"},
	}}
	handler := newTestHandler(t, testServerOptions{reads: reads})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/genes/assemblies", nil)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, req)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body %s", response.Code, response.Body.String())
	}
	if reads.calls != 1 {
		t.Fatalf("local store called %d times, want 1", reads.calls)
	}
	var items []readmodel.Assembly
	if err := json.Unmarshal(response.Body.Bytes(), &items); err != nil {
		t.Fatalf("decode response: %v; body %s", err, response.Body.String())
	}
	if len(items) != 1 || items[0].Name != "Gmax_880_v6.0" {
		t.Fatalf("unexpected payload: %+v", items)
	}
}

func TestAssembliesRouteRejectsWrites(t *testing.T) {
	reads := &fakeReadSource{}
	handler := newTestHandler(t, testServerOptions{reads: reads})

	for _, method := range []string{http.MethodPost, http.MethodPut, http.MethodDelete} {
		req := httptest.NewRequest(method, "/api/v1/genes/assemblies", nil)
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, req)
		if response.Code != http.StatusMethodNotAllowed {
			t.Fatalf("%s: status = %d, want 405", method, response.Code)
		}
	}
	if reads.calls != 0 {
		t.Fatalf("a rejected method must not touch the database (%d calls)", reads.calls)
	}
}

func TestAssembliesRouteFailsClosedOnQueryError(t *testing.T) {
	reads := &fakeReadSource{err: errors.New("database unavailable")}
	handler := newTestHandler(t, testServerOptions{reads: reads})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/genes/assemblies", nil)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, req)

	if response.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503; body %s", response.Code, response.Body.String())
	}
	if strings.Contains(response.Body.String(), "database unavailable") {
		t.Fatal("the response leaked the store error")
	}
}

// The chromosome route answers 404 for an assembly that is not in the
// published release. An empty list would say "that assembly exists and has no
// chromosomes", which is a claim the data never made.
func TestAssemblyChromosomesRoute(t *testing.T) {
	reads := &fakeReadSource{chromosomes: []readmodel.Chromosome{
		{ID: "1", AssemblyID: "1", Name: "Gm01", Length: 59600650, Order: 1},
	}}
	handler := newTestHandler(t, testServerOptions{reads: reads})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/genes/assemblies/1/chromosomes", nil)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, req)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body %s", response.Code, response.Body.String())
	}
	var items []readmodel.Chromosome
	if err := json.Unmarshal(response.Body.Bytes(), &items); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(items) != 1 || items[0].Name != "Gm01" || items[0].Length != 59600650 {
		t.Fatalf("unexpected payload: %+v", items)
	}
}

func TestAssemblyChromosomesRouteRefusesUnknownAssembly(t *testing.T) {
	reads := &fakeReadSource{err: readmodel.ErrAssemblyNotInScope}
	handler := newTestHandler(t, testServerOptions{reads: reads})

	for _, path := range []string{
		"/api/v1/genes/assemblies/999/chromosomes",
		"/api/v1/genes/assemblies/abc/chromosomes",
		"/api/v1/genes/assemblies/0/chromosomes",
	} {
		req := httptest.NewRequest(http.MethodGet, path, nil)
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, req)
		if response.Code != http.StatusNotFound {
			t.Fatalf("%s: status = %d, want 404", path, response.Code)
		}
	}
}

func TestActiveReleaseRoute(t *testing.T) {
	reads := &fakeReadSource{active: readmodel.ActiveRelease{}}
	handler := newTestHandler(t, testServerOptions{reads: reads})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/releases/active", nil)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, req)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", response.Code)
	}
	var payload readmodel.ActiveRelease
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if payload.ReleaseID != nil || payload.Version != nil {
		t.Fatalf("no published release must answer the empty object, got %+v", payload)
	}
}

// The news route serves the published articles. The limit is clamped to the
// range the Python query parameter allows, so the two services cannot answer
// different ranges for the same request.
func TestNewsRoute(t *testing.T) {
	reads := &fakeReadSource{news: []readmodel.News{
		{ID: "1", TitleEN: "Release notes", Slug: "release-notes", IsPublished: true},
	}}
	handler := newTestHandler(t, testServerOptions{reads: reads})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/content/news", nil)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, req)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body %s", response.Code, response.Body.String())
	}
	var items []readmodel.News
	if err := json.Unmarshal(response.Body.Bytes(), &items); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(items) != 1 || items[0].Slug != "release-notes" {
		t.Fatalf("unexpected payload: %+v", items)
	}
}

func TestNewsRouteRejectsAnOutOfRangeLimit(t *testing.T) {
	reads := &fakeReadSource{}
	handler := newTestHandler(t, testServerOptions{reads: reads})

	for _, limit := range []string{"0", "101", "abc"} {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/content/news?limit="+limit, nil)
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, req)
		if response.Code != http.StatusNotFound {
			t.Fatalf("limit=%s: status = %d, want 404", limit, response.Code)
		}
	}
	if reads.calls != 0 {
		t.Fatalf("a rejected limit must not touch the database (%d calls)", reads.calls)
	}
}

// The paginated route answers the envelope, not the plain array the
// /content/news compatibility route serves. The two shapes must not drift
// into each other.
func TestNewsPageRoute(t *testing.T) {
	reads := &fakeReadSource{newsPage: readmodel.NewsList{
		Items:    []readmodel.NewsSummary{{ID: "1", Slug: "release-notes", Status: "published"}},
		Total:    7,
		Page:     2,
		PageSize: 20,
	}}
	handler := newTestHandler(t, testServerOptions{reads: reads})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/news?page=2", nil)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, req)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body %s", response.Code, response.Body.String())
	}
	var payload readmodel.NewsList
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if payload.Total != 7 || payload.Page != 2 || payload.PageSize != 20 {
		t.Fatalf("unexpected envelope: %+v", payload)
	}
	if len(payload.Items) != 1 || payload.Items[0].Slug != "release-notes" {
		t.Fatalf("unexpected items: %+v", payload.Items)
	}
}

func TestNewsPageRouteRejectsOutOfRangeParameters(t *testing.T) {
	reads := &fakeReadSource{}
	handler := newTestHandler(t, testServerOptions{reads: reads})

	for _, query := range []string{"page=0", "page=abc", "page_size=0", "page_size=201"} {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/news?"+query, nil)
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, req)
		if response.Code != http.StatusNotFound {
			t.Fatalf("%s: status = %d, want 404", query, response.Code)
		}
	}
	if reads.calls != 0 {
		t.Fatalf("a rejected parameter must not touch the database (%d calls)", reads.calls)
	}
}

// The fixed response bodies are literals so the package cannot panic while
// rendering them. This pins that they still equal what encoding the equivalent
// map would produce, byte for byte: if a literal is edited, this fails rather
// than the two drifting apart.
func TestFixedBodiesMatchEncoding(t *testing.T) {
	cases := []struct {
		name    string
		body    []byte
		payload map[string]string
	}{
		{"health", healthBody, map[string]string{"status": "ok", "service": "soymutdb-gateway"}},
		{"method not allowed", methodNotAllowedBody, map[string]string{"detail": "Method Not Allowed"}},
		{"unavailable", unavailableBody, map[string]string{"detail": "Homepage statistics are unavailable"}},
		{"not found", notFoundBody, map[string]string{"detail": "Not Found"}},
	}
	for _, tc := range cases {
		encoded, err := json.Marshal(tc.payload)
		if err != nil {
			t.Fatalf("%s: marshal: %v", tc.name, err)
		}
		want := append(encoded, '\n')
		if !bytes.Equal(tc.body, want) {
			t.Fatalf("%s: body %q does not match the encoded map %q", tc.name, tc.body, want)
		}
	}
}

// The content routes answer the admin-authored public content. Each one is
// checked for the method guard and, where it takes a parameter, for the
// parameter range: an out-of-range value must not reach the database.
func TestContentRoutes(t *testing.T) {
	releaseID := int64(7)
	reads := &fakeReadSource{
		publications:    []readmodel.Publication{{Title: "A paper", Authors: "An author", DOI: strPtr("10.1/x")}},
		staticPages:     []readmodel.StaticPage{{ID: "1", Slug: "about", TitleEN: "About", ContentEN: "text"}},
		downloadFiles:   []readmodel.DownloadFile{{ID: "1", Name: "file.txt", FileURL: "https://example.org/f"}},
		trackCategories: []readmodel.TrackCategory{{ID: 1, Name: "sequence", DisplayOrder: 1}},
		releaseID:       &releaseID,
	}
	handler := newTestHandler(t, testServerOptions{reads: reads})

	for path, want := range map[string]string{
		"/api/v1/content/publications": "A paper",
		"/api/v1/content/pages":        "About",
		"/api/v1/content/downloads":    "file.txt",
		"/api/v1/tracks/categories":    "sequence",
	} {
		req := httptest.NewRequest(http.MethodGet, path, nil)
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, req)
		if response.Code != http.StatusOK {
			t.Fatalf("%s: status = %d, want 200; body %s", path, response.Code, response.Body.String())
		}
		if !strings.Contains(response.Body.String(), want) {
			t.Fatalf("%s: body %s does not carry %q", path, response.Body.String(), want)
		}
	}
}

func TestContentRoutesRejectWrites(t *testing.T) {
	reads := &fakeReadSource{}
	handler := newTestHandler(t, testServerOptions{reads: reads})

	for _, path := range []string{
		"/api/v1/content/publications",
		"/api/v1/content/pages",
		"/api/v1/content/downloads",
		"/api/v1/tracks/categories",
	} {
		req := httptest.NewRequest(http.MethodPost, path, nil)
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, req)
		if response.Code != http.StatusMethodNotAllowed {
			t.Fatalf("%s: status = %d, want 405", path, response.Code)
		}
	}
	if reads.calls != 0 {
		t.Fatalf("a rejected method must not touch the database (%d calls)", reads.calls)
	}
}

func strPtr(value string) *string { return &value }
