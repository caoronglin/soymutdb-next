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
)

// Config is the resolved gateway configuration.
type Config struct {
	Addr         string
	DatabaseURL  string
	MaxOpenConns int
	MaxIdleConns int
	QueryTimeout time.Duration
}

// Load reads configuration from the process environment.
func Load() (Config, error) {
	cfg := Config{
		Addr:         stringEnv("SOYMUTDB_GATEWAY_ADDR", defaultAddr),
		MaxOpenConns: intEnv("SOYMUTDB_GATEWAY_MAX_OPEN_CONNS", defaultMaxOpenConns),
		MaxIdleConns: intEnv("SOYMUTDB_GATEWAY_MAX_IDLE_CONNS", defaultMaxIdleConns),
		QueryTimeout: durationEnv("SOYMUTDB_GATEWAY_QUERY_TIMEOUT", defaultQueryTimeout),
	}

	dsn, err := NormalizeDatabaseURL(os.Getenv("SOYMUTDB_DATABASE_URL"))
	if err != nil {
		return Config{}, err
	}
	cfg.DatabaseURL = dsn

	if cfg.MaxIdleConns > cfg.MaxOpenConns {
		cfg.MaxIdleConns = cfg.MaxOpenConns
	}
	return cfg, nil
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
	query.Set("default_transaction_read_only", "on")
	parsed.RawQuery = query.Encode()
	return parsed.String(), nil
}

func forceReadOnlyKeywordDSN(dsn string) string {
	const setting = "default_transaction_read_only"
	if strings.Contains(dsn, setting+"=") {
		return dsn
	}
	return dsn + " " + setting + "=on"
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
