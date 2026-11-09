package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"soymutdb.local/gateway/internal/stats"
)

type fakeSource struct {
	payload stats.Homepage
	err     error
}

func (f fakeSource) Homepage(context.Context) (stats.Homepage, error) {
	return f.payload, f.err
}

func TestHomepageReturnsPythonContract(t *testing.T) {
	date := "2026-01-02T03:04:05.123456Z"
	name := "v2026.01"
	srv := New(fakeSource{payload: stats.Homepage{
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
	}}, time.Second).Handler()

	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/stats/homepage", nil))

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if got := rec.Header().Get("Content-Type"); got != "application/json" {
		t.Fatalf("content-type = %q", got)
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
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
	srv := New(fakeSource{}, time.Second).Handler()

	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/stats/homepage", nil))

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
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
	srv := New(fakeSource{err: errors.New("boom")}, time.Second).Handler()

	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/stats/homepage", nil))

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", rec.Code)
	}
	var body map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body["detail"] == "" {
		t.Fatalf("missing detail: %v", body)
	}
}

func TestHealthAndMethodRejection(t *testing.T) {
	srv := New(fakeSource{}, time.Second).Handler()

	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/healthz", nil))
	if rec.Code != http.StatusOK {
		t.Fatalf("health status = %d", rec.Code)
	}

	rec = httptest.NewRecorder()
	srv.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/api/v1/stats/homepage", nil))
	if rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("POST status = %d, want 405", rec.Code)
	}
}
