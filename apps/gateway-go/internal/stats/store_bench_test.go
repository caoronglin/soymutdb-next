package stats

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"
)

// The benchmarks need the same migrated database the integration test uses and
// run inside a rolled-back transaction:
//
//	SOYMUTDB_GATEWAY_TEST_DATABASE_URL=postgres://user:pass@host:5432/db \
//	  go test ./internal/stats -run XXX -bench . -benchtime 200x
//
// The fixture is deliberately tiny: these benchmarks measure the fixed cost of
// issuing the aggregate, not the cost of scanning a large release.
func benchmarkFixture(b *testing.B) (context.Context, *sql.Tx) {
	b.Helper()
	raw := strings.TrimSpace(os.Getenv("SOYMUTDB_GATEWAY_TEST_DATABASE_URL"))
	if raw == "" {
		b.Skip("SOYMUTDB_GATEWAY_TEST_DATABASE_URL is not set")
	}
	db, err := sql.Open("postgres", libpqDSN(raw))
	if err != nil {
		b.Fatalf("open: %v", err)
	}
	b.Cleanup(func() { _ = db.Close() })

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	b.Cleanup(cancel)
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		b.Fatalf("begin: %v", err)
	}
	b.Cleanup(func() { _ = tx.Rollback() })

	suffix := time.Now().UnixNano()
	releaseID := insertRelease(b, tx, fmt.Sprintf("vbench-%d", suffix), "published",
		"2026-01-02 03:04:05.123456+00")
	setActiveRelease(b, tx, releaseID)
	assemblyID := insertAssembly(b, tx, fmt.Sprintf("asm-bench-%d", suffix), releaseID)
	chromosomeID := insertChromosome(b, tx, assemblyID, "chr01")
	insertGene(b, tx, fmt.Sprintf("GLYMA_BENCH_%d", suffix), assemblyID, chromosomeID)
	line := fmt.Sprintf("bench-line-%d", suffix)
	lineID := insertLine(b, tx, fmt.Sprintf("GWB%011d", suffix%100000000000), line, true, false, &releaseID)
	insertSeed(b, tx, lineID, fmt.Sprintf("LOT-BENCH-%d", suffix))
	insertFact(b, tx, releaseID, assemblyID, 1, "SNP", line)
	return ctx, tx
}

// BenchmarkHomepagePreparedStatements is the production path: both statements
// are prepared once, so a call costs two round trips and no re-planning.
func BenchmarkHomepagePreparedStatements(b *testing.B) {
	ctx, tx := benchmarkFixture(b)
	store, err := NewStore(ctx, tx)
	if err != nil {
		b.Fatalf("new store: %v", err)
	}
	b.Cleanup(func() { _ = store.Close() })
	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		if _, err := store.Homepage(ctx); err != nil {
			b.Fatalf("homepage: %v", err)
		}
	}
}

// BenchmarkHomepageUnpreparedStatements issues the same two statements through
// QueryRowContext, which is what the store did before it prepared them: lib/pq
// parses and describes each statement in its own round trip and PostgreSQL
// re-plans it on every execution.
func BenchmarkHomepageUnpreparedStatements(b *testing.B) {
	ctx, tx := benchmarkFixture(b)
	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		if _, err := homepageUnprepared(ctx, tx); err != nil {
			b.Fatalf("homepage: %v", err)
		}
	}
}

func homepageUnprepared(ctx context.Context, tx *sql.Tx) (Homepage, error) {
	var (
		releaseID   int64
		version     sql.NullString
		publishedAt sql.NullTime
	)
	err := tx.QueryRowContext(ctx, publishedReleaseSQL).Scan(&releaseID, &version, &publishedAt)
	if err != nil {
		return Homepage{}, err
	}
	var (
		page Homepage
		ins  int64
		del  int64
	)
	err = tx.QueryRowContext(ctx, homepageSQL, releaseID).Scan(
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
		return Homepage{}, err
	}
	page.IndelCount = ins + del
	page.LastReleaseName = nullString(version)
	page.LastReleaseDate = nullTime(publishedAt)
	return page, nil
}
