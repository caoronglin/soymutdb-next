package config

import (
	"net/url"
	"strings"
	"testing"
	"time"
)

func TestNormalizeSQLAlchemyURL(t *testing.T) {
	dsn, err := NormalizeDatabaseURL("postgresql+asyncpg://soymutdb:soymutdb@127.0.0.1:5432/soymutdb_dev")
	if err != nil {
		t.Fatalf("normalize: %v", err)
	}
	parsed, err := url.Parse(dsn)
	if err != nil {
		t.Fatalf("parse normalized dsn: %v", err)
	}
	if parsed.Scheme != "postgres" {
		t.Fatalf("scheme = %q, want postgres", parsed.Scheme)
	}
	if got := parsed.Query().Get("default_transaction_read_only"); got != "on" {
		t.Fatalf("read-only = %q, want on", got)
	}
	if !strings.Contains(dsn, "soymutdb_dev") {
		t.Fatalf("database name lost: %q", dsn)
	}
}

func TestNormalizeKeepsExistingReadOnlySetting(t *testing.T) {
	dsn, err := NormalizeDatabaseURL("postgres://u:p@db:5432/x?default_transaction_read_only=on&sslmode=disable")
	if err != nil {
		t.Fatalf("normalize: %v", err)
	}
	if strings.Count(dsn, "default_transaction_read_only") != 1 {
		t.Fatalf("duplicated read-only setting: %q", dsn)
	}
	if !strings.Contains(dsn, "sslmode=disable") {
		t.Fatalf("other settings lost: %q", dsn)
	}
}

func TestNormalizeDisablesJITByDefault(t *testing.T) {
	dsn, err := NormalizeDatabaseURL("postgresql+asyncpg://soymutdb:soymutdb@127.0.0.1:5432/soymutdb_dev")
	if err != nil {
		t.Fatalf("normalize: %v", err)
	}
	parsed, err := url.Parse(dsn)
	if err != nil {
		t.Fatalf("parse normalized dsn: %v", err)
	}
	if got := parsed.Query().Get("jit"); got != "off" {
		t.Fatalf("jit = %q, want off", got)
	}
}

func TestNormalizeKeepsExplicitJITSetting(t *testing.T) {
	dsn, err := NormalizeDatabaseURL("postgres://u:p@db:5432/x?jit=on")
	if err != nil {
		t.Fatalf("normalize: %v", err)
	}
	parsed, err := url.Parse(dsn)
	if err != nil {
		t.Fatalf("parse normalized dsn: %v", err)
	}
	if got := parsed.Query().Get("jit"); got != "on" {
		t.Fatalf("operator setting overwritten: jit = %q", got)
	}
}

func TestNormalizeKeywordDSN(t *testing.T) {
	dsn, err := NormalizeDatabaseURL("host=127.0.0.1 port=5432 dbname=soymutdb_dev")
	if err != nil {
		t.Fatalf("normalize: %v", err)
	}
	if !strings.Contains(dsn, "default_transaction_read_only=on") {
		t.Fatalf("read-only not appended: %q", dsn)
	}
	if !strings.Contains(dsn, "jit=off") {
		t.Fatalf("jit default not appended: %q", dsn)
	}
}

func TestNormalizeRejectsEmpty(t *testing.T) {
	if _, err := NormalizeDatabaseURL("  "); err == nil {
		t.Fatal("empty DSN accepted")
	}
}

// setServingEnv installs a complete, valid environment so Load's defaults can
// be asserted without inheriting whatever the operator's shell exported.
func setServingEnv(t *testing.T) {
	t.Helper()
	t.Setenv("SOYMUTDB_DATABASE_URL", "postgresql+asyncpg://soymutdb:soymutdb@127.0.0.1:5432/soymutdb_dev")
	t.Setenv("SOYMUTDB_GATEWAY_STATIC_DIR", "/srv/admin/dist")
	t.Setenv("SOYMUTDB_GATEWAY_UPSTREAM_URL", "http://api:8010/")
	t.Setenv("SOYMUTDB_GATEWAY_ADDR", "")
	t.Setenv("SOYMUTDB_GATEWAY_PROXY_TIMEOUT", "")
	t.Setenv("SOYMUTDB_GATEWAY_READ_TIMEOUT", "")
	t.Setenv("SOYMUTDB_GATEWAY_RATE_LIMIT_RATE", "")
	t.Setenv("SOYMUTDB_GATEWAY_RATE_LIMIT_BURST", "")
	t.Setenv("SOYMUTDB_GATEWAY_RATE_LIMIT_CLIENTS", "")
}

func TestLoadServingDefaults(t *testing.T) {
	setServingEnv(t)
	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.StaticDir != "/srv/admin/dist" {
		t.Fatalf("static dir = %q", cfg.StaticDir)
	}
	if got := cfg.UpstreamURL.String(); got != "http://api:8010" {
		t.Fatalf("upstream = %q, want the trailing slash trimmed", got)
	}
	if cfg.ProxyTimeout != 30*time.Second || cfg.ReadTimeout != 5*time.Minute {
		t.Fatalf("timeouts = %v / %v", cfg.ProxyTimeout, cfg.ReadTimeout)
	}
	if cfg.RateLimitRate != 30 || cfg.RateLimitBurst != 60 || cfg.RateLimitClients != 4096 {
		t.Fatalf("rate limits = %v / %d / %d", cfg.RateLimitRate, cfg.RateLimitBurst, cfg.RateLimitClients)
	}
}

func TestLoadRequiresServingConfiguration(t *testing.T) {
	cases := []struct {
		name     string
		variable string
		value    string
		want     string
	}{
		{name: "artifact", variable: "SOYMUTDB_GATEWAY_STATIC_DIR", value: "", want: "SOYMUTDB_GATEWAY_STATIC_DIR is required"},
		{name: "upstream", variable: "SOYMUTDB_GATEWAY_UPSTREAM_URL", value: "", want: "SOYMUTDB_GATEWAY_UPSTREAM_URL is required"},
		{name: "credentials", variable: "SOYMUTDB_GATEWAY_UPSTREAM_URL", value: "http://user:secret@api:8010", want: "credentials"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			setServingEnv(t)
			t.Setenv(tc.variable, tc.value)
			_, err := Load()
			if err == nil {
				t.Fatalf("Load accepted %s=%q", tc.variable, tc.value)
			}
			if !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("error = %q, want it to mention %q", err, tc.want)
			}
		})
	}
}

func TestParseUpstreamURLRejectsUnusableValues(t *testing.T) {
	cases := []struct {
		name string
		raw  string
	}{
		{name: "empty", raw: ""},
		{name: "not a url", raw: "://api"},
		{name: "wrong scheme", raw: "ftp://api:8010"},
		{name: "missing host", raw: "http://"},
		{name: "query", raw: "http://api:8010?debug=1"},
		{name: "fragment", raw: "http://api:8010/#frag"},
		{name: "credentials", raw: "http://user:pass@api:8010"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := parseUpstreamURL(tc.raw); err == nil {
				t.Fatalf("parseUpstreamURL(%q) accepted", tc.raw)
			}
		})
	}
}

func TestParseUpstreamURLKeepsBasePath(t *testing.T) {
	parsed, err := parseUpstreamURL("https://api.internal/soymutdb/")
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if parsed.Path != "/soymutdb" {
		t.Fatalf("path = %q, want /soymutdb", parsed.Path)
	}
}
