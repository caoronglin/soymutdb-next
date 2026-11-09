package config

import (
	"net/url"
	"strings"
	"testing"
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

func TestNormalizeKeywordDSN(t *testing.T) {
	dsn, err := NormalizeDatabaseURL("host=127.0.0.1 port=5432 dbname=soymutdb_dev")
	if err != nil {
		t.Fatalf("normalize: %v", err)
	}
	if !strings.Contains(dsn, "default_transaction_read_only=on") {
		t.Fatalf("read-only not appended: %q", dsn)
	}
}

func TestNormalizeRejectsEmpty(t *testing.T) {
	if _, err := NormalizeDatabaseURL("  "); err == nil {
		t.Fatal("empty DSN accepted")
	}
}
