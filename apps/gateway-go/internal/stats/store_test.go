package stats

import (
	"database/sql"
	"testing"
	"time"
)

func TestNullTimeMatchesPydantic(t *testing.T) {
	withMicros := sql.NullTime{
		Time:  time.Date(2026, 1, 2, 3, 4, 5, 123456000, time.UTC),
		Valid: true,
	}
	if got := *nullTime(withMicros); got != "2026-01-02T03:04:05.123456Z" {
		t.Fatalf("with micros = %q", got)
	}

	whole := sql.NullTime{Time: time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC), Valid: true}
	if got := *nullTime(whole); got != "2026-01-02T03:04:05Z" {
		t.Fatalf("whole seconds = %q", got)
	}

	if nullTime(sql.NullTime{}) != nil {
		t.Fatal("invalid time must render null")
	}
}

func TestNullTimeConvertsToUTC(t *testing.T) {
	zone := time.FixedZone("UTC+8", 8*3600)
	value := sql.NullTime{
		Time:  time.Date(2026, 1, 2, 11, 4, 5, 0, zone),
		Valid: true,
	}
	if got := *nullTime(value); got != "2026-01-02T03:04:05Z" {
		t.Fatalf("utc conversion = %q", got)
	}
}

func TestNullString(t *testing.T) {
	if nullString(sql.NullString{}) != nil {
		t.Fatal("invalid string must render null")
	}
	value := "v1"
	if got := nullString(sql.NullString{String: value, Valid: true}); got == nil || *got != value {
		t.Fatalf("string = %v", got)
	}
}
