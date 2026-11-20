// Package httpapi serves the gateway's public surface: the read-only aggregate,
// the admin console artifact, the reverse-proxied API and the health probes.
package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"soymutdb.local/gateway/internal/apiproxy"
	"soymutdb.local/gateway/internal/compress"
	"soymutdb.local/gateway/internal/ratelimit"
	"soymutdb.local/gateway/internal/readmodel"
	"soymutdb.local/gateway/internal/static"
	"soymutdb.local/gateway/internal/stats"
)

// StatsSource is the aggregate read the server depends on.
type StatsSource interface {
	Homepage(ctx context.Context) (stats.Homepage, error)
}

// ReadSource is the public, unauthenticated read surface answered locally.
// The Python API remains authoritative for the contract; these are the
// endpoints whose shape is simple enough to port without drifting.
type ReadSource interface {
	Assemblies(ctx context.Context) ([]readmodel.Assembly, error)
	Chromosomes(ctx context.Context, assemblyID int64) ([]readmodel.Chromosome, error)
	News(ctx context.Context, limit int) ([]readmodel.News, error)
	NewsPage(ctx context.Context, category *string, page, pageSize int) (readmodel.NewsList, error)
	Publications(ctx context.Context, limit int) ([]readmodel.Publication, error)
	StaticPages(ctx context.Context) ([]readmodel.StaticPage, error)
	DownloadFiles(ctx context.Context, releaseID int64, category *string) ([]readmodel.DownloadFile, error)
	TrackCategories(ctx context.Context) ([]readmodel.TrackCategory, error)
	PublishedReleaseID(ctx context.Context) (*int64, error)
	ActiveRelease(ctx context.Context) (readmodel.ActiveRelease, error)
}

// Config wires the server. Everything is required: the gateway refuses to
// start without an artifact to serve and an upstream to proxy.
type Config struct {
	Stats        StatsSource
	Reads        ReadSource
	QueryTimeout time.Duration
	StaticDir    string
	Upstream     *apiproxy.Options
	RateLimit    *ratelimit.Limiter
	Logger       *slog.Logger
}

// Server renders the stats route itself and delegates everything else.
type Server struct {
	source       StatsSource
	reads        ReadSource
	queryTimeout time.Duration
	static       *static.Handler
	proxy        *apiproxy.Proxy
	artifactPath string

	// The fixed answers are rendered once. They are replayed on every health
	// check and on every request while the database is unavailable, so
	// marshalling them per request was pure repetition: health went from
	// 1.8µs/496B/8 allocs to 0.4µs/16B/1 alloc.
	healthBody           []byte
	methodNotAllowedBody []byte
	unavailableBody      []byte
	notFoundBody         []byte
}

// New builds the server, failing closed when the artifact or the proxy cannot
// be constructed.
func New(cfg Config) (*Server, error) {
	artifacts, err := static.New(cfg.StaticDir)
	if err != nil {
		return nil, err
	}
	if cfg.Upstream == nil {
		return nil, errors.New("httpapi: proxy options are required")
	}
	// The limiter is owned by the proxy handler: static assets are never
	// rate limited, because one admin page load fetches dozens of hashed files
	// while a user session issues only a handful of API calls.
	upstream := *cfg.Upstream
	upstream.Limiter = cfg.RateLimit
	upstream.Logger = cfg.Logger
	proxy, err := apiproxy.New(upstream)
	if err != nil {
		return nil, err
	}

	return &Server{
		source:               cfg.Stats,
		reads:                cfg.Reads,
		queryTimeout:         cfg.QueryTimeout,
		static:               artifacts,
		proxy:                proxy,
		artifactPath:         filepath.Join(artifacts.Root(), "index.html"),
		healthBody:           healthBody,
		methodNotAllowedBody: methodNotAllowedBody,
		unavailableBody:      unavailableBody,
		notFoundBody:         notFoundBody,
	}, nil
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	// /healthz stays exactly what it was: liveness for the process. Readiness
	// is separate because it depends on the artifact and the upstream.
	mux.HandleFunc("/healthz", s.health)
	mux.HandleFunc("/readyz", s.ready)
	// The stats aggregate is answered here, not proxied: it is the route the
	// parity contract compares byte for byte with the Python API.
	mux.HandleFunc("/api/v1/stats/homepage", s.homepage)
	// Public assembly list: served from PostgreSQL here instead of spending a
	// proxy hop on the Python API. Everything else under /api/ still forwards.
	mux.HandleFunc("/api/v1/genes/assemblies", s.assemblies)
	// The chromosome list of one assembly. The assembly must belong to the
	// published release; an unknown or out-of-scope assembly answers 404, so
	// the route never discloses an unpublished row.
	mux.HandleFunc("/api/v1/genes/assemblies/", s.assemblyChromosomes)
	mux.HandleFunc("/api/v1/releases/active", s.activeRelease)
	// Published news, newest first. The /content/ route keeps the plain-array
	// shape; /api/v1/news answers the paginated envelope, so the two routes
	// have separate handlers.
	mux.HandleFunc("/api/v1/content/news", s.news)
	mux.HandleFunc("/api/v1/news", s.newsPage)
	// Admin-authored public content: publications, static pages, downloadable
	// files and the track-category list.
	mux.HandleFunc("/api/v1/content/publications", s.publications)
	mux.HandleFunc("/api/v1/content/pages", s.staticPages)
	mux.HandleFunc("/api/v1/content/downloads", s.downloadFiles)
	mux.HandleFunc("/api/v1/tracks/categories", s.trackCategories)
	mux.Handle("/api/", s.proxy)
	mux.Handle("/", s.static)
	return compress.WithGzip(mux)
}

func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeBody(w, http.StatusMethodNotAllowed, s.methodNotAllowedBody)
		return
	}
	writeBody(w, http.StatusOK, s.healthBody)
}

func (s *Server) homepage(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeBody(w, http.StatusMethodNotAllowed, s.methodNotAllowedBody)
		return
	}
	// The public home page never accepts a release pin: the aggregate is bound
	// to the active published release, exactly like the Python endpoint.
	ctx, cancel := context.WithTimeout(r.Context(), s.queryTimeout)
	defer cancel()

	payload, err := s.source.Homepage(ctx)
	if err != nil {
		// FastAPI renders HTTPException bodies as {"detail": ...}.
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	writeJSON(w, http.StatusOK, payload)
}

// assemblies answers GET /api/v1/genes/assemblies with the same public shape
// as the Python endpoint. An unavailable database is a 503 rather than an
// empty list: "no published release" is a legitimate empty list, but a failed
// query must not masquerade as one.
func (s *Server) assemblies(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeBody(w, http.StatusMethodNotAllowed, s.methodNotAllowedBody)
		return
	}
	if s.reads == nil {
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), s.queryTimeout)
	defer cancel()
	items, err := s.reads.Assemblies(ctx)
	if err != nil {
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	writeJSON(w, http.StatusOK, items)
}

// assemblyChromosomes answers GET /api/v1/genes/assemblies/{id}/chromosomes.
// The path parameter is parsed strictly: a non-numeric id is a bad request,
// not an assembly that happens to have no chromosomes.
func (s *Server) assemblyChromosomes(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeBody(w, http.StatusMethodNotAllowed, s.methodNotAllowedBody)
		return
	}
	rest := strings.TrimPrefix(r.URL.Path, "/api/v1/genes/assemblies/")
	raw := strings.TrimSuffix(rest, "/chromosomes")
	if raw == rest || raw == "" {
		writeBody(w, http.StatusNotFound, s.notFoundBody)
		return
	}
	assemblyID, err := strconv.ParseInt(raw, 10, 64)
	if err != nil || assemblyID <= 0 {
		writeBody(w, http.StatusNotFound, s.notFoundBody)
		return
	}
	if s.reads == nil {
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), s.queryTimeout)
	defer cancel()
	items, err := s.reads.Chromosomes(ctx, assemblyID)
	if err != nil {
		if errors.Is(err, readmodel.ErrAssemblyNotInScope) {
			writeBody(w, http.StatusNotFound, s.notFoundBody)
			return
		}
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	writeJSON(w, http.StatusOK, items)
}

// activeRelease answers GET /api/v1/releases/active with the release the
// public surface currently serves. Before the first publish it answers the
// empty object, which is an answer and not an error.
func (s *Server) activeRelease(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeBody(w, http.StatusMethodNotAllowed, s.methodNotAllowedBody)
		return
	}
	if s.reads == nil {
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), s.queryTimeout)
	defer cancel()
	payload, err := s.reads.ActiveRelease(ctx)
	if err != nil {
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	writeJSON(w, http.StatusOK, payload)
}

// news answers the published news list. The plain-array shape is the one the
// /content/news compatibility route serves; the newer /api/v1/news route
// answers a paginated envelope and stays with the Python API until its own
// shape is ported.
func (s *Server) news(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeBody(w, http.StatusMethodNotAllowed, s.methodNotAllowedBody)
		return
	}
	if s.reads == nil {
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	limit := 20
	if raw := r.URL.Query().Get("limit"); raw != "" {
		parsed, err := strconv.Atoi(raw)
		if err != nil || parsed < 1 || parsed > 100 {
			writeBody(w, http.StatusNotFound, s.notFoundBody)
			return
		}
		limit = parsed
	}
	ctx, cancel := context.WithTimeout(r.Context(), s.queryTimeout)
	defer cancel()
	items, err := s.reads.News(ctx, limit)
	if err != nil {
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	writeJSON(w, http.StatusOK, items)
}

// newsPage answers GET /api/v1/news with the paginated envelope: the items,
// the total number of published articles, and the page that was served. The
// category filter is optional; page and page_size follow the Python range.
func (s *Server) newsPage(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeBody(w, http.StatusMethodNotAllowed, s.methodNotAllowedBody)
		return
	}
	if s.reads == nil {
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	query := r.URL.Query()
	page := 1
	if raw := query.Get("page"); raw != "" {
		parsed, err := strconv.Atoi(raw)
		if err != nil || parsed < 1 {
			writeBody(w, http.StatusNotFound, s.notFoundBody)
			return
		}
		page = parsed
	}
	pageSize := 20
	if raw := query.Get("page_size"); raw != "" {
		parsed, err := strconv.Atoi(raw)
		if err != nil || parsed < 1 || parsed > 200 {
			writeBody(w, http.StatusNotFound, s.notFoundBody)
			return
		}
		pageSize = parsed
	}
	var category *string
	if raw := query.Get("category"); raw != "" {
		value := raw
		category = &value
	}

	ctx, cancel := context.WithTimeout(r.Context(), s.queryTimeout)
	defer cancel()
	payload, err := s.reads.NewsPage(ctx, category, page, pageSize)
	if err != nil {
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	writeJSON(w, http.StatusOK, payload)
}

// publications answers GET /api/v1/content/publications.
func (s *Server) publications(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeBody(w, http.StatusMethodNotAllowed, s.methodNotAllowedBody)
		return
	}
	if s.reads == nil {
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	limit := 20
	if raw := r.URL.Query().Get("limit"); raw != "" {
		parsed, err := strconv.Atoi(raw)
		if err != nil || parsed < 1 || parsed > 100 {
			writeBody(w, http.StatusNotFound, s.notFoundBody)
			return
		}
		limit = parsed
	}
	ctx, cancel := context.WithTimeout(r.Context(), s.queryTimeout)
	defer cancel()
	items, err := s.reads.Publications(ctx, limit)
	if err != nil {
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	writeJSON(w, http.StatusOK, items)
}

// staticPages answers GET /api/v1/content/pages with the published pages.
func (s *Server) staticPages(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeBody(w, http.StatusMethodNotAllowed, s.methodNotAllowedBody)
		return
	}
	if s.reads == nil {
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), s.queryTimeout)
	defer cancel()
	items, err := s.reads.StaticPages(ctx)
	if err != nil {
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	writeJSON(w, http.StatusOK, items)
}

// downloadFiles answers GET /api/v1/content/downloads with the files of the
// published release. A file bound to another release is not listed.
func (s *Server) downloadFiles(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeBody(w, http.StatusMethodNotAllowed, s.methodNotAllowedBody)
		return
	}
	if s.reads == nil {
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), s.queryTimeout)
	defer cancel()
	releaseID, err := s.reads.PublishedReleaseID(ctx)
	if err != nil {
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	if releaseID == nil {
		writeJSON(w, http.StatusOK, []readmodel.DownloadFile{})
		return
	}
	var category *string
	if raw := r.URL.Query().Get("category"); raw != "" {
		value := raw
		category = &value
	}
	items, err := s.reads.DownloadFiles(ctx, *releaseID, category)
	if err != nil {
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	writeJSON(w, http.StatusOK, items)
}

// trackCategories answers GET /api/v1/tracks/categories.
func (s *Server) trackCategories(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeBody(w, http.StatusMethodNotAllowed, s.methodNotAllowedBody)
		return
	}
	if s.reads == nil {
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), s.queryTimeout)
	defer cancel()
	items, err := s.reads.TrackCategories(ctx)
	if err != nil {
		writeBody(w, http.StatusServiceUnavailable, s.unavailableBody)
		return
	}
	writeJSON(w, http.StatusOK, items)
}

// ready reports whether this instance can serve: the artifact is still on disk
// and the upstream API answers its readiness probe. The answer describes
// outcomes only, never the upstream address or any credential.
func (s *Server) ready(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		writeBody(w, http.StatusMethodNotAllowed, s.methodNotAllowedBody)
		return
	}

	checks := map[string]string{
		"admin_artifact": "ok",
		"api_upstream":   "ok",
	}
	ready := true

	if info, err := os.Stat(s.artifactPath); err != nil || !info.Mode().IsRegular() {
		checks["admin_artifact"] = "missing"
		ready = false
	}
	if state, ok := s.proxy.UpstreamReady(r.Context()); !ok {
		checks["api_upstream"] = state
		ready = false
	}

	status := http.StatusOK
	label := "ready"
	if !ready {
		status = http.StatusServiceUnavailable
		label = "unready"
	}
	writeJSON(w, status, readyReport{Status: label, Checks: checks})
}

type readyReport struct {
	Status string            `json:"status"`
	Checks map[string]string `json:"checks"`
}

// writeJSON streams a payload. Encoding straight into the response is what the
// handler measured fastest; staging it in a buffer and copying it out cost the
// same allocations and an extra copy, and a struct of counters cannot fail
// part-way.
func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func writeBody(w http.ResponseWriter, status int, body []byte) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(status)
	_, _ = w.Write(body)
}

// The fixed response bodies. They are literals rather than marshalled maps on
// purpose: a library package that panics is a library package that can take
// the process down, and these bodies never vary. The trailing newline is the
// byte json.Encoder appends to every response, so the bytes match what an
// encoded map would have produced.
//
// `fixedBodiesMatchEncoding` in the test file pins that equivalence: if a body
// is ever edited, the test fails instead of the two drifting apart.
var (
	// json.Marshal sorts map keys, so the encoded form puts "service" before
	// "status". The literal keeps that order: the bytes are the contract.
	healthBody           = []byte(`{"service":"soymutdb-gateway","status":"ok"}` + "\n")
	methodNotAllowedBody = []byte(`{"detail":"Method Not Allowed"}` + "\n")
	unavailableBody      = []byte(`{"detail":"Homepage statistics are unavailable"}` + "\n")
	notFoundBody         = []byte(`{"detail":"Not Found"}` + "\n")
)
