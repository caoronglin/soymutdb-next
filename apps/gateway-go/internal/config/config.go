// Package config loads the gateway's process configuration from the
// environment. The gateway is a read-only surface, so the database URL is
// normalised and forced into a read-only session before any query runs.
package config

import (
	"errors"
	"fmt"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

const (
	defaultAddr         = ":18020"
	defaultMaxOpenConns = 10
	defaultMaxIdleConns = 5
	defaultQueryTimeout = 5 * time.Second

	// Serving-layer defaults. The proxy deadline answers a slow upstream with
	// a 504 instead of holding a connection open, while the read deadline only
	// bounds how long a client may spend sending its request body: admin
	// imports upload files through the same listener, so it cannot be the 10s
	// that bounds the header phase.
	defaultProxyTimeout     = 30 * time.Second
	defaultReadTimeout      = 5 * time.Minute
	defaultRateLimitRate    = 30.0
	defaultRateLimitBurst   = 60
	defaultRateLimitClients = 4096

	// readOnlySetting is forced onto every session, whatever the DSN says.
	readOnlySetting = "default_transaction_read_only"

	// jitSetting disables PostgreSQL's cost-based JIT for this process. The
	// gateway serves one small aggregate whose estimated plan cost trips
	// jit_above_cost while its actual work is a single scan, so every request
	// paid for LLVM compilation it could not use: on a release holding 600k
	// variant facts the aggregate took 2.02s with JIT and 0.54s without it.
	// It is a default, not a force: an explicit setting in the DSN wins. The
	// parameter exists on PostgreSQL 11+, which covers every supported server;
	// an older server would refuse the connection at startup.
	jitSetting = "jit"
)

// Config is the resolved gateway configuration.
type Config struct {
	Addr         string
	DatabaseURL  string
	MaxOpenConns int
	MaxIdleConns int
	QueryTimeout time.Duration

	// StaticDir is the built admin console artifact (apps/admin/dist).
	StaticDir string
	// UpstreamURL is the Python API the gateway reverse-proxies /api/* to.
	UpstreamURL  *url.URL
	ProxyTimeout time.Duration
	ReadTimeout  time.Duration

	RateLimitRate    float64
	RateLimitBurst   int
	RateLimitClients int
}

// Load reads configuration from the process environment.
func Load() (Config, error) {
	cfg := Config{
		Addr:         stringEnv("SOYMUTDB_GATEWAY_ADDR", defaultAddr),
		MaxOpenConns: intEnv("SOYMUTDB_GATEWAY_MAX_OPEN_CONNS", defaultMaxOpenConns),
		MaxIdleConns: intEnv("SOYMUTDB_GATEWAY_MAX_IDLE_CONNS", defaultMaxIdleConns),
		QueryTimeout: durationEnv("SOYMUTDB_GATEWAY_QUERY_TIMEOUT", defaultQueryTimeout),
		ProxyTimeout: durationEnv("SOYMUTDB_GATEWAY_PROXY_TIMEOUT", defaultProxyTimeout),
		ReadTimeout:  durationEnv("SOYMUTDB_GATEWAY_READ_TIMEOUT", defaultReadTimeout),

		RateLimitRate:    floatEnv("SOYMUTDB_GATEWAY_RATE_LIMIT_RATE", defaultRateLimitRate),
		RateLimitBurst:   intEnv("SOYMUTDB_GATEWAY_RATE_LIMIT_BURST", defaultRateLimitBurst),
		RateLimitClients: intEnv("SOYMUTDB_GATEWAY_RATE_LIMIT_CLIENTS", defaultRateLimitClients),
	}

	dsn, err := NormalizeDatabaseURL(os.Getenv("SOYMUTDB_DATABASE_URL"))
	if err != nil {
		return Config{}, err
	}
	cfg.DatabaseURL = dsn

	// Fail closed: without an artifact there is no admin console to serve, and
	// without an upstream every /api/* call would answer 502.
	if cfg.StaticDir, err = requiredEnv("SOYMUTDB_GATEWAY_STATIC_DIR"); err != nil {
		return Config{}, err
	}
	if cfg.UpstreamURL, err = parseUpstreamURL(os.Getenv("SOYMUTDB_GATEWAY_UPSTREAM_URL")); err != nil {
		return Config{}, err
	}

	if cfg.MaxIdleConns > cfg.MaxOpenConns {
		cfg.MaxIdleConns = cfg.MaxOpenConns
	}
	return cfg, nil
}

// parseUpstreamURL validates SOYMUTDB_GATEWAY_UPSTREAM_URL. A base path is
// allowed (the proxy joins it with the request path). Credentials in the URL
// are rejected instead of forwarded, so no secret can reach a log line or a
// readiness answer by accident.
func parseUpstreamURL(raw string) (*url.URL, error) {
	value := strings.TrimSpace(raw)
	if value == "" {
		return nil, errors.New("SOYMUTDB_GATEWAY_UPSTREAM_URL is required")
	}
	parsed, err := url.Parse(value)
	if err != nil {
		return nil, fmt.Errorf("invalid SOYMUTDB_GATEWAY_UPSTREAM_URL: %w", err)
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return nil, fmt.Errorf("invalid SOYMUTDB_GATEWAY_UPSTREAM_URL %q: scheme must be http or https", parsed.Scheme)
	}
	if parsed.Host == "" {
		return nil, errors.New("invalid SOYMUTDB_GATEWAY_UPSTREAM_URL: host is empty")
	}
	if parsed.User != nil {
		return nil, errors.New("invalid SOYMUTDB_GATEWAY_UPSTREAM_URL: credentials in the URL are not supported")
	}
	if parsed.RawQuery != "" || parsed.Fragment != "" {
		return nil, errors.New("invalid SOYMUTDB_GATEWAY_UPSTREAM_URL: query and fragment are not supported")
	}
	parsed.Path = strings.TrimRight(parsed.Path, "/")
	parsed.RawPath = ""
	return parsed, nil
}

// NormalizeDatabaseURL accepts the DSN forms the Python services publish and
// returns one that lib/pq can open, with read-only transactions forced on.
func NormalizeDatabaseURL(raw string) (string, error) {
	dsn := strings.TrimSpace(raw)
	if dsn == "" {
		return "", errors.New("SOYMUTDB_DATABASE_URL is required")
	}

	// SQLAlchemy URLs carry the driver in the scheme; lib/pq does not.
	for _, prefix := range []string{
		"postgresql+asyncpg://",
		"postgresql+psycopg://",
		"postgresql+psycopg2://",
	} {
		if strings.HasPrefix(dsn, prefix) {
			dsn = "postgres://" + strings.TrimPrefix(dsn, prefix)
			break
		}
	}

	if strings.HasPrefix(dsn, "postgres://") || strings.HasPrefix(dsn, "postgresql://") {
		return forceReadOnlyURL(dsn)
	}
	return forceReadOnlyKeywordDSN(dsn), nil
}

func forceReadOnlyURL(dsn string) (string, error) {
	parsed, err := url.Parse(dsn)
	if err != nil {
		return "", fmt.Errorf("invalid database URL: %w", err)
	}
	query := parsed.Query()
	query.Set(readOnlySetting, "on")
	if _, explicit := query[jitSetting]; !explicit {
		query.Set(jitSetting, "off")
	}
	parsed.RawQuery = query.Encode()
	return parsed.String(), nil
}

func forceReadOnlyKeywordDSN(dsn string) string {
	if !strings.Contains(dsn, readOnlySetting+"=") {
		dsn += " " + readOnlySetting + "=on"
	}
	if !strings.Contains(dsn, jitSetting+"=") {
		dsn += " " + jitSetting + "=off"
	}
	return dsn
}

func requiredEnv(key string) (string, error) {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return "", fmt.Errorf("%s is required", key)
	}
	return value, nil
}

func floatEnv(key string, fallback float64) float64 {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return fallback
	}
	value, err := strconv.ParseFloat(raw, 64)
	if err != nil || value <= 0 {
		return fallback
	}
	return value
}

func stringEnv(key, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(key)); value != "" {
		return value
	}
	return fallback
}

func intEnv(key string, fallback int) int {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return fallback
	}
	value, err := strconv.Atoi(raw)
	if err != nil || value <= 0 {
		return fallback
	}
	return value
}

func durationEnv(key string, fallback time.Duration) time.Duration {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return fallback
	}
	value, err := time.ParseDuration(raw)
	if err != nil || value <= 0 {
		return fallback
	}
	return value
}
