// Package stats implements the public home-page aggregate against the
// authoritative PostgreSQL database. It is the Go port of
// apps/api/app/api/v1/stats.py::_load_homepage_stats and must answer the same
// JSON contract, including the release scoping and visibility rules.
package stats

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"
)

// Querier is the read surface shared by *sql.DB and *sql.Tx.
type Querier interface {
	QueryRowContext(ctx context.Context, query string, args ...any) *sql.Row
}

// Homepage mirrors schemas.analytics.HomepageStats, field order included.
type Homepage struct {
	TotalVariants   int64   `json:"total_variants"`
	SNPCount        int64   `json:"snp_count"`
	IndelCount      int64   `json:"indel_count"`
	SVCount         int64   `json:"sv_count"`
	GeneCount       int64   `json:"gene_count"`
	MutantLineCount int64   `json:"mutant_line_count"`
	ReleaseCount    int64   `json:"release_count"`
	AssemblyCount   int64   `json:"assembly_count"`
	SeedAccessions  int64   `json:"seed_accessions"`
	LastReleaseDate *string `json:"last_release_date"`
	LastReleaseName *string `json:"last_release_name"`
}

// Store reads published-release aggregates. It performs no writes; the process
// additionally opens the database with default_transaction_read_only=on.
type Store struct {
	db Querier
}

func NewStore(db Querier) *Store {
	return &Store{db: db}
}

// The active pointer is a singleton (id = 1) and must not be trusted blindly:
// a pointer to a draft or rolled-back release is not public. The join drops it.
const publishedReleaseSQL = `
SELECT r.id, r.version, r.published_at
FROM active_release ar
JOIN releases r ON r.id = ar.release_id
WHERE ar.id = 1 AND r.status = 'published'`

// homepageSQL is the single-round-trip port of _load_homepage_stats.
//
// Every count is bound to $1, one already-resolved published release:
//   - genes are assembly-scoped and counted through the release's assemblies;
//   - mutant lines are counted with the public_mutant_visibility predicate
//     (is_public, not deleted, public_id present);
//   - seed lots hang off those public lines;
//   - variant facts additionally need the release published and the fact to
//     name either no line or a public line of the same release — the
//     variant_fact_visibility predicate.
//
// release_count is the publication history (all published releases), not a
// property of the resolved release, matching the Python aggregate.
const homepageSQL = `
WITH scoped_facts AS (
    SELECT vf.variant_type
    FROM variant_facts vf
    WHERE vf.release_id = $1
      AND EXISTS (
          SELECT 1 FROM releases r
          WHERE r.id = vf.release_id AND r.status = 'published'
      )
      AND (
          vf.mutant_line_name = ''
          OR EXISTS (
              SELECT 1 FROM mutant_lines ml
              WHERE ml.release_id = vf.release_id
                AND ml.name = vf.mutant_line_name
                AND ml.is_public
                AND NOT ml.is_deleted
                AND ml.public_id IS NOT NULL
          )
      )
)
SELECT
    (SELECT count(*) FROM genes g
      WHERE g.assembly_id IN (SELECT a.id FROM assemblies a WHERE a.release_id = $1)),
    (SELECT count(*) FROM mutant_lines ml
      WHERE ml.release_id = $1
        AND ml.is_public AND NOT ml.is_deleted AND ml.public_id IS NOT NULL),
    (SELECT count(*) FROM releases WHERE status = 'published'),
    (SELECT count(*) FROM assemblies a WHERE a.release_id = $1),
    (SELECT count(*) FROM seed_inventory si
      WHERE si.mutant_line_id IN (
          SELECT ml.id FROM mutant_lines ml
          WHERE ml.release_id = $1
            AND ml.is_public AND NOT ml.is_deleted AND ml.public_id IS NOT NULL)),
    count(*),
    count(*) FILTER (WHERE variant_type = 'SNP'),
    count(*) FILTER (WHERE variant_type = 'INS'),
    count(*) FILTER (WHERE variant_type = 'DEL'),
    count(*) FILTER (WHERE variant_type = 'SV')
FROM scoped_facts`

// Homepage returns the aggregate for the active published release. When no
// release is published it returns the zero aggregate, like the Python endpoint.
func (s *Store) Homepage(ctx context.Context) (Homepage, error) {
	var (
		releaseID   int64
		version     sql.NullString
		publishedAt sql.NullTime
	)
	err := s.db.QueryRowContext(ctx, publishedReleaseSQL).Scan(&releaseID, &version, &publishedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return Homepage{}, nil
	}
	if err != nil {
		return Homepage{}, fmt.Errorf("resolve published release: %w", err)
	}

	row, err := s.loadAggregate(ctx, releaseID)
	if err != nil {
		return Homepage{}, err
	}
	row.LastReleaseName = nullString(version)
	row.LastReleaseDate = nullTime(publishedAt)
	return row, nil
}

func (s *Store) loadAggregate(ctx context.Context, releaseID int64) (Homepage, error) {
	var (
		page Homepage
		ins  int64
		del  int64
	)
	err := s.db.QueryRowContext(ctx, homepageSQL, releaseID).Scan(
		&page.GeneCount,
		&page.MutantLineCount,
		&page.ReleaseCount,
		&page.AssemblyCount,
		&page.SeedAccessions,
		&page.TotalVariants,
		&page.SNPCount,
		&ins,
		&del,
		&page.SVCount,
	)
	if err != nil {
		return Homepage{}, fmt.Errorf("homepage aggregate: %w", err)
	}
	// The Python endpoint folds ins+del into one Indel bucket.
	page.IndelCount = ins + del
	return page, nil
}

func nullString(value sql.NullString) *string {
	if !value.Valid {
		return nil
	}
	text := value.String
	return &text
}

// nullTime renders a timestamp exactly as Pydantic v2 does: UTC, fractional
// seconds only when the value carries microseconds, and a literal Z suffix.
func nullTime(value sql.NullTime) *string {
	if !value.Valid {
		return nil
	}
	stamp := value.Time.UTC().Format(stampLayout(value.Time.UTC()))
	text := stamp
	return &text
}

func stampLayout(t time.Time) string {
	if t.Nanosecond()/1000 == 0 {
		return "2006-01-02T15:04:05Z"
	}
	return "2006-01-02T15:04:05.000000Z"
}
