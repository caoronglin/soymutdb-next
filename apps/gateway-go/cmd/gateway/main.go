// Command gateway is the staged Go serving layer for SoyMutDB. It serves the
// read-only home-page aggregate, the built admin console artifact and the
// reverse-proxied API; writes, imports, release workflow and admin glue stay in
// Python. See docs/dev/go-gateway.md.
package main

import (
	"context"
	"database/sql"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	_ "github.com/lib/pq"

	"soymutdb.local/gateway/internal/apiproxy"
	"soymutdb.local/gateway/internal/config"
	"soymutdb.local/gateway/internal/httpapi"
	"soymutdb.local/gateway/internal/ratelimit"
	"soymutdb.local/gateway/internal/readmodel"
	"soymutdb.local/gateway/internal/stats"
)

// Server-level bounds. The header phase is bounded tightly; the body phase is
// configuration because the same listener proxies admin imports, and the write
// phase is deliberately unbounded in favour of the proxy deadline: a
// server-level write deadline would cut a streamed export download that is
// actively making progress.
const (
	readHeaderTimeout = 5 * time.Second
	idleTimeout       = 60 * time.Second
	maxHeaderBytes    = 16 << 10
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))

	cfg, err := config.Load()
	if err != nil {
		logger.Error("invalid configuration", "error", err)
		os.Exit(1)
	}

	limiter, err := ratelimit.New(cfg.RateLimitRate, cfg.RateLimitBurst, cfg.RateLimitClients)
	if err != nil {
		logger.Error("invalid rate limit configuration", "error", err)
		os.Exit(1)
	}

	db, err := sql.Open("postgres", cfg.DatabaseURL)
	if err != nil {
		logger.Error("open database", "error", err)
		os.Exit(1)
	}
	defer db.Close()
	db.SetMaxOpenConns(cfg.MaxOpenConns)
	db.SetMaxIdleConns(cfg.MaxIdleConns)
	db.SetConnMaxLifetime(30 * time.Minute)

	startupCtx, cancelStartup := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancelStartup()
	if err := db.PingContext(startupCtx); err != nil {
		logger.Error("database unreachable", "error", err)
		os.Exit(1)
	}
	store, err := stats.NewStore(startupCtx, db)
	if err != nil {
		logger.Error("prepare statements", "error", err)
		os.Exit(1)
	}
	defer func() { _ = store.Close() }()

	reads, err := readmodel.NewStore(startupCtx, db)
	if err != nil {
		logger.Error("prepare read-model statements", "error", err)
		os.Exit(1)
	}
	defer func() { _ = reads.Close() }()

	api, err := httpapi.New(httpapi.Config{
		Stats:        store,
		Reads:        reads,
		QueryTimeout: cfg.QueryTimeout,
		StaticDir:    cfg.StaticDir,
		Upstream: &apiproxy.Options{
			Upstream: cfg.UpstreamURL,
			Timeout:  cfg.ProxyTimeout,
		},
		RateLimit: limiter,
		Logger:    logger,
	})
	if err != nil {
		logger.Error("cannot serve the admin artifact or proxy the API", "error", err)
		os.Exit(1)
	}

	server := &http.Server{
		Addr:    cfg.Addr,
		Handler: api.Handler(),
		// WriteTimeout stays zero on purpose: every response here is either a
		// small aggregate or a stream whose progress the proxy deadline (and the
		// API's own limits) already bound. A fixed write deadline would abort a
		// large export mid-body while it was still being delivered.
		ReadHeaderTimeout: readHeaderTimeout,
		ReadTimeout:       cfg.ReadTimeout,
		IdleTimeout:       idleTimeout,
		MaxHeaderBytes:    maxHeaderBytes,
	}

	shutdown := make(chan os.Signal, 1)
	signal.Notify(shutdown, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		logger.Info("gateway listening",
			"addr", cfg.Addr,
			"static_dir", cfg.StaticDir,
			"upstream", cfg.UpstreamURL.Redacted(),
		)
		if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("serve", "error", err)
			os.Exit(1)
		}
	}()

	<-shutdown
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := server.Shutdown(ctx); err != nil {
		logger.Error("shutdown", "error", err)
		os.Exit(1)
	}
	logger.Info("gateway stopped")
}
