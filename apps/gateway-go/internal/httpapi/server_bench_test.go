package httpapi

import (
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"soymutdb.local/gateway/internal/apiproxy"
	"soymutdb.local/gateway/internal/stats"
)

var errUnavailable = errors.New("database unavailable")

var benchmarkPayload = stats.Homepage{
	TotalVariants:   1_284_930,
	SNPCount:        1_102_551,
	IndelCount:      141_207,
	SVCount:         12_004,
	GeneCount:       56_044,
	MutantLineCount: 3_812,
	ReleaseCount:    7,
	AssemblyCount:   2,
	SeedAccessions:  1_902,
	LastReleaseDate: strptr("2026-01-02T03:04:05.123456Z"),
	LastReleaseName: strptr("v2026.01"),
}

func strptr(value string) *string { return &value }

func benchmarkRoute(b *testing.B, path string, source StatsSource) {
	b.Helper()
	handler := newBenchmarkHandler(b, source, "")
	request := httptest.NewRequest(http.MethodGet, path, nil)
	recorder := httptest.NewRecorder()
	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		recorder.Body.Reset()
		handler.ServeHTTP(recorder, request)
	}
}

func BenchmarkHomepageResponse(b *testing.B) {
	benchmarkRoute(b, "/api/v1/stats/homepage", fakeSource{payload: benchmarkPayload})
}

func BenchmarkHealthResponse(b *testing.B) {
	benchmarkRoute(b, "/healthz", fakeSource{})
}

func BenchmarkHomepageUnavailableResponse(b *testing.B) {
	benchmarkRoute(b, "/api/v1/stats/homepage", fakeSource{err: errUnavailable})
}

// benchmarkArtifact builds a document, a ~64 KiB hashed chunk (the shape of an
// umi async chunk) and a font. The directory is per benchmark because
// b.TempDir is removed when each benchmark ends.
func benchmarkArtifact(b *testing.B) string {
	b.Helper()
	dir := b.TempDir()
	files := map[string]string{
		"index.html":             adminIndex,
		"assets/app.abc12345.js": strings.Repeat(`console.log("soymutdb admin console chunk");`+"\n", 1500),
		"fonts/harmony.woff2":    "wOF2",
	}
	for name, content := range files {
		target := filepath.Join(dir, filepath.FromSlash(name))
		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			b.Fatalf("mkdir: %v", err)
		}
		if err := os.WriteFile(target, []byte(content), 0o644); err != nil {
			b.Fatalf("write: %v", err)
		}
	}
	return dir
}

func newBenchmarkHandler(b *testing.B, source StatsSource, upstreamURL string) http.Handler {
	b.Helper()
	if upstreamURL == "" {
		upstreamURL = "http://127.0.0.1:1"
	}
	parsed, err := url.Parse(upstreamURL)
	if err != nil {
		b.Fatalf("parse upstream: %v", err)
	}
	server, err := New(Config{
		Stats:        source,
		QueryTimeout: time.Second,
		StaticDir:    benchmarkArtifact(b),
		Upstream:     &apiproxy.Options{Upstream: parsed, Timeout: 5 * time.Second},
	})
	if err != nil {
		b.Fatalf("New: %v", err)
	}
	return server.Handler()
}

func benchmarkStatic(b *testing.B, path string, acceptEncoding string) {
	b.Helper()
	handler := newBenchmarkHandler(b, fakeSource{}, "")
	request := httptest.NewRequest(http.MethodGet, path, nil)
	if acceptEncoding != "" {
		request.Header.Set("Accept-Encoding", acceptEncoding)
	}
	recorder := httptest.NewRecorder()
	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		recorder.Body.Reset()
		// Headers are response state too: a Content-Encoding left over from the
		// previous iteration would make the next one look pre-encoded.
		clear(recorder.Header())
		handler.ServeHTTP(recorder, request)
	}
	b.StopTimer()
	b.ReportMetric(float64(recorder.Body.Len()), "wire-bytes")
}

func BenchmarkStaticDocument(b *testing.B) {
	benchmarkStatic(b, "/", "")
}

func BenchmarkStaticDocumentGzip(b *testing.B) {
	benchmarkStatic(b, "/", "gzip")
}

func BenchmarkStaticChunk(b *testing.B) {
	benchmarkStatic(b, "/assets/app.abc12345.js", "")
}

func BenchmarkStaticChunkGzip(b *testing.B) {
	benchmarkStatic(b, "/assets/app.abc12345.js", "gzip")
}

// BenchmarkProxyPath measures the forward and return trip through the proxy
// with a live loopback upstream, which is the shape of a real /api/* call.
func BenchmarkProxyPath(b *testing.B) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"public_id":"SM-0001","assembly":"v5","release":"2026.01"}`)
	}))
	defer upstream.Close()

	handler := newBenchmarkHandler(b, fakeSource{}, upstream.URL)
	request := httptest.NewRequest(http.MethodGet, "/api/v1/mutants/SM-0001", nil)
	request.Header.Set("Accept-Encoding", "identity")
	recorder := httptest.NewRecorder()
	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		recorder.Body.Reset()
		handler.ServeHTTP(recorder, request)
	}
}
