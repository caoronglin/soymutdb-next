package stats

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"reflect"
	"strings"
	"testing"
	"time"

	_ "github.com/lib/pq"

	"soymutdb.local/gateway/internal/config"
)

// The integration test runs inside one transaction and rolls it back, so it
// never leaves rows behind. Point it at any migrated database:
//
//	SOYMUTDB_GATEWAY_TEST_DATABASE_URL=postgres://user:pass@host:5432/db go test ./...
func TestHomepageAgainstPostgres(t *testing.T) {
	raw := strings.TrimSpace(os.Getenv("SOYMUTDB_GATEWAY_TEST_DATABASE_URL"))
	if raw == "" {
		t.Skip("SOYMUTDB_GATEWAY_TEST_DATABASE_URL is not set")
	}
	db, err := sql.Open("postgres", libpqDSN(raw))
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	defer db.Close()
	if err := db.Ping(); err != nil {
		t.Fatalf("ping: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	defer func() { _ = tx.Rollback() }()

	suffix := time.Now().UnixNano()
	publishedID := insertRelease(t, tx, fmt.Sprintf("vtest-pub-%d", suffix), "published",
		"2026-01-02 03:04:05.123456+00")
	draftID := insertRelease(t, tx, fmt.Sprintf("vtest-draft-%d", suffix), "draft", nil)
	setActiveRelease(t, tx, publishedID)

	assemblyID := insertAssembly(t, tx, fmt.Sprintf("asm-test-%d", suffix), publishedID)
	chromosomeID := insertChromosome(t, tx, assemblyID, "chr01")
	insertGene(t, tx, fmt.Sprintf("GLYMA_TEST_%d_A", suffix), assemblyID, chromosomeID)
	insertGene(t, tx, fmt.Sprintf("GLYMA_TEST_%d_B", suffix), assemblyID, chromosomeID)

	lineA := fmt.Sprintf("line-a-%d", suffix)
	lineB := fmt.Sprintf("line-b-%d", suffix)
	lineDeleted := fmt.Sprintf("line-del-%d", suffix)
	linePrivate := fmt.Sprintf("line-priv-%d", suffix)
	lineNoPublicID := fmt.Sprintf("line-nopub-%d", suffix)

	pubA := insertLine(t, tx, fmt.Sprintf("GWAS%08d1", suffix%100000000), lineA, true, false, &publishedID)
	insertLine(t, tx, fmt.Sprintf("GWAS%08d2", suffix%100000000), lineB, true, false, &publishedID)
	deleted := insertLine(t, tx, fmt.Sprintf("GWAS%08d3", suffix%100000000), lineDeleted, true, true, &publishedID)
	insertLine(t, tx, fmt.Sprintf("GWAS%08d4", suffix%100000000), linePrivate, false, false, &publishedID)
	insertLine(t, tx, "", lineNoPublicID, true, false, &publishedID)

	insertSeed(t, tx, pubA, fmt.Sprintf("LOT-A-%d", suffix))
	insertSeed(t, tx, deleted, fmt.Sprintf("LOT-DEL-%d", suffix))

	facts := []struct {
		releaseID      int
		variantID      int64
		variantType    string
		mutantLineName string
	}{
		{publishedID, 1, "SNP", lineA},
		{publishedID, 2, "SNP", ""},
		{publishedID, 3, "INS", lineB},
		{publishedID, 4, "DEL", lineDeleted},
		{publishedID, 5, "SV", lineA},
		{publishedID, 6, "MNV", ""},
		{publishedID, 7, "SNP", linePrivate},
		{publishedID, 8, "SNP", lineNoPublicID},
		{draftID, 9, "SNP", lineA},
	}
	for _, fact := range facts {
		insertFact(t, tx, fact.releaseID, assemblyID, fact.variantID, fact.variantType, fact.mutantLineName)
	}

	store, err := NewStore(ctx, tx)
	if err != nil {
		t.Fatalf("new store: %v", err)
	}
	defer func() { _ = store.Close() }()
	got, err := store.Homepage(ctx)
	if err != nil {
		t.Fatalf("homepage: %v", err)
	}

	// Counted facts: SNP/published line, SNP/no line, INS/public line,
	// SV/public line, MNV/no line. Deleted, private and null-public-id lines
	// and the draft release's fact are all excluded.
	assertCount(t, "total_variants", got.TotalVariants, 5)
	assertCount(t, "snp_count", got.SNPCount, 2)
	assertCount(t, "indel_count", got.IndelCount, 1)
	assertCount(t, "sv_count", got.SVCount, 1)
	assertCount(t, "gene_count", got.GeneCount, 2)
	assertCount(t, "mutant_line_count", got.MutantLineCount, 2)
	assertCount(t, "assembly_count", got.AssemblyCount, 1)
	assertCount(t, "seed_accessions", got.SeedAccessions, 1)

	var releaseCount int64
	if err := tx.QueryRowContext(ctx,
		"SELECT count(*) FROM releases WHERE status = 'published'").Scan(&releaseCount); err != nil {
		t.Fatalf("release count: %v", err)
	}
	assertCount(t, "release_count", got.ReleaseCount, releaseCount)

	if got.LastReleaseDate == nil || *got.LastReleaseDate != "2026-01-02T03:04:05.123456Z" {
		t.Fatalf("last_release_date = %v", got.LastReleaseDate)
	}
	if got.LastReleaseName == nil || *got.LastReleaseName != fmt.Sprintf("vtest-pub-%d", suffix) {
		t.Fatalf("last_release_name = %v", got.LastReleaseName)
	}

	// A pointer at a draft release is not public: the aggregate must answer
	// zeros even though a published release with data exists.
	setActiveRelease(t, tx, draftID)
	empty, err := store.Homepage(ctx)
	if err != nil {
		t.Fatalf("draft-pointer homepage: %v", err)
	}
	if empty != (Homepage{}) {
		t.Fatalf("draft pointer must answer the zero aggregate, got %+v", empty)
	}

	// A prepared statement is re-planned by PostgreSQL from a custom plan to a
	// generic one after five executions. The answer must not move with it.
	setActiveRelease(t, tx, publishedID)
	for i := 0; i < 6; i++ {
		repeated, err := store.Homepage(ctx)
		if err != nil {
			t.Fatalf("repeat %d: %v", i, err)
		}
		if !reflect.DeepEqual(repeated, got) {
			t.Fatalf("repeat %d = %+v, want %+v", i, repeated, got)
		}
	}
}

// TestForcedSessionParametersReachServer proves the DSN normalisation is not
// decoration: lib/pq forwards unknown keys as startup runtime parameters, so
// the read-only guarantee and the JIT setting arrive before any statement runs.
func TestForcedSessionParametersReachServer(t *testing.T) {
	raw := strings.TrimSpace(os.Getenv("SOYMUTDB_GATEWAY_TEST_DATABASE_URL"))
	if raw == "" {
		t.Skip("SOYMUTDB_GATEWAY_TEST_DATABASE_URL is not set")
	}
	dsn, err := config.NormalizeDatabaseURL(raw)
	if err != nil {
		t.Fatalf("normalize: %v", err)
	}
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	defer db.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	for setting, want := range map[string]string{
		"default_transaction_read_only": "on",
		"jit":                           "off",
	} {
		var got string
		if err := db.QueryRowContext(ctx, "SHOW "+setting).Scan(&got); err != nil {
			t.Fatalf("show %s: %v", setting, err)
		}
		if got != want {
			t.Fatalf("%s = %q, want %q", setting, got, want)
		}
	}
}

func assertCount(t testing.TB, name string, got, want int64) {
	t.Helper()
	if got != want {
		t.Fatalf("%s = %d, want %d", name, got, want)
	}
}

// libpqDSN strips the SQLAlchemy driver suffix without forcing read-only, so
// the fixture can write inside its rolled-back transaction.
func libpqDSN(raw string) string {
	for _, prefix := range []string{
		"postgresql+asyncpg://",
		"postgresql+psycopg://",
		"postgresql+psycopg2://",
	} {
		if strings.HasPrefix(raw, prefix) {
			return "postgres://" + strings.TrimPrefix(raw, prefix)
		}
	}
	return raw
}

func insertRelease(t testing.TB, tx *sql.Tx, version, status string, publishedAt any) int {
	t.Helper()
	var id int
	err := tx.QueryRow(
		`INSERT INTO releases (version, name, status, published_at)
		 VALUES ($1, $1, $2::release_status_enum, $3) RETURNING id`,
		version, status, publishedAt,
	).Scan(&id)
	if err != nil {
		t.Fatalf("insert release %s: %v", version, err)
	}
	return id
}

func setActiveRelease(t testing.TB, tx *sql.Tx, releaseID int) {
	t.Helper()
	result, err := tx.Exec(`UPDATE active_release SET release_id = $1 WHERE id = 1`, releaseID)
	if err != nil {
		t.Fatalf("update active_release: %v", err)
	}
	affected, err := result.RowsAffected()
	if err != nil {
		t.Fatalf("rows affected: %v", err)
	}
	if affected == 0 {
		if _, err := tx.Exec(`INSERT INTO active_release (id, release_id) VALUES (1, $1)`, releaseID); err != nil {
			t.Fatalf("insert active_release: %v", err)
		}
	}
}

func insertAssembly(t testing.TB, tx *sql.Tx, name string, releaseID int) int {
	t.Helper()
	var id int
	err := tx.QueryRow(
		`INSERT INTO assemblies (name, species, version, release_id)
		 VALUES ($1, 'Glycine max', 'test', $2) RETURNING id`,
		name, releaseID,
	).Scan(&id)
	if err != nil {
		t.Fatalf("insert assembly: %v", err)
	}
	return id
}

func insertChromosome(t testing.TB, tx *sql.Tx, assemblyID int, name string) int {
	t.Helper()
	var id int
	err := tx.QueryRow(
		`INSERT INTO chromosomes (assembly_id, name, length, "order")
		 VALUES ($1, $2, 1000, 0) RETURNING id`,
		assemblyID, name,
	).Scan(&id)
	if err != nil {
		t.Fatalf("insert chromosome: %v", err)
	}
	return id
}

func insertGene(t testing.TB, tx *sql.Tx, accession string, assemblyID, chromosomeID int) {
	t.Helper()
	if _, err := tx.Exec(
		`INSERT INTO genes (accession, assembly_id, chromosome_id, start, "end", strand)
		 VALUES ($1, $2, $3, 1, 10, '+')`,
		accession, assemblyID, chromosomeID,
	); err != nil {
		t.Fatalf("insert gene: %v", err)
	}
}

func insertLine(
	t testing.TB, tx *sql.Tx, publicID, name string, isPublic, isDeleted bool, releaseID *int,
) int {
	t.Helper()
	var id int
	var pid any
	if publicID != "" {
		pid = publicID
	}
	err := tx.QueryRow(
		`INSERT INTO mutant_lines (public_id, name, is_public, is_deleted, release_id, species)
		 VALUES ($1, $2, $3, $4, $5, 'Glycine max') RETURNING id`,
		pid, name, isPublic, isDeleted, releaseID,
	).Scan(&id)
	if err != nil {
		t.Fatalf("insert mutant line %s: %v", name, err)
	}
	return id
}

func insertSeed(t testing.TB, tx *sql.Tx, lineID int, lot string) {
	t.Helper()
	if _, err := tx.Exec(
		`INSERT INTO seed_inventory (mutant_line_id, lot_number, seed_lot, quantity_grams)
		 VALUES ($1, $2, $2, 1.00)`,
		lineID, lot,
	); err != nil {
		t.Fatalf("insert seed lot: %v", err)
	}
}

func insertFact(t testing.TB, tx *sql.Tx, releaseID, assemblyID int, variantID int64, variantType, lineName string) {
	t.Helper()
	if _, err := tx.Exec(
		`INSERT INTO variant_facts (
		    release_id, assembly_id, variant_id, assembly_key, chromosome, position,
		    ref_allele, alt_allele, variant_type, mutant_line_name
		 ) VALUES ($1, $2, $3, 'test-asm', 'chr01', $4, 'A', 'T', $5, $6)`,
		releaseID, assemblyID, variantID, variantID*10, variantType, lineName,
	); err != nil {
		t.Fatalf("insert variant fact: %v", err)
	}
}
