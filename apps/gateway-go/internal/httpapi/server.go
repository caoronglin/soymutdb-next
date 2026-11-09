// Package httpapi serves the gateway's read-only public surface.
package httpapi

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"soymutdb.local/gateway/internal/stats"
)

// StatsSource is the aggregate read the server depends on.
type StatsSource interface {
	Homepage(ctx context.Context) (stats.Homepage, error)
}

// Server wires the stats source into an http.Handler.
type Server struct {
	source       StatsSource
	queryTimeout time.Duration
}

func New(source StatsSource, queryTimeout time.Duration) *Server {
	return &Server{source: source, queryTimeout: queryTimeout}
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", s.health)
	mux.HandleFunc("/api/v1/stats/homepage", s.homepage)
	return mux
}

func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeDetail(w, http.StatusMethodNotAllowed, "Method Not Allowed")
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{
		"status":  "ok",
		"service": "soymutdb-gateway",
	})
}

func (s *Server) homepage(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeDetail(w, http.StatusMethodNotAllowed, "Method Not Allowed")
		return
	}
	// The public home page never accepts a release pin: the aggregate is bound
	// to the active published release, exactly like the Python endpoint.
	ctx, cancel := context.WithTimeout(r.Context(), s.queryTimeout)
	defer cancel()

	payload, err := s.source.Homepage(ctx)
	if err != nil {
		// FastAPI renders HTTPException bodies as {"detail": ...}.
		writeDetail(w, http.StatusServiceUnavailable, "Homepage statistics are unavailable")
		return
	}
	writeJSON(w, http.StatusOK, payload)
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func writeDetail(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]string{"detail": detail})
}
