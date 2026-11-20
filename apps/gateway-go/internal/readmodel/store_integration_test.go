package readmodel

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"

	_ "github.com/lib/pq"
)

// TestAssembliesAgainstPostgres runs inside a transaction and rolls it back,
// so it never changes the database. The point is not only the happy path: a
// draft release pointed to by active_release must NOT publish its assemblies.
//
//	SOYMUTDB_GATEWAY_TEST_DATABASE_URL=postgres://user:pass@host:5432/db go test ./...
func TestAssembliesAgainstPostgres(t *testing.T) {
	raw := strings.TrimSpace(os.Getenv("SOYMUTDB_GATEWAY_TEST_DATABASE_URL"))
	if raw == "" {
		t.Skip("SOYMUTDB_GATEWAY_TEST_DATABASE_URL is not set")
	}
	db, err := sql.Open("postgres", strings.Replace(raw, "postgresql+asyncpg://", "postgres://", 1))
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

	// Published release with one assembly, and a draft release with another.
	// Names are built before the call, not inside its argument list: the SQL
	// injection rule cannot tell a bound parameter from a formatted query when
	// fmt.Sprintf appears anywhere among the arguments.
	publicVersion := fmt.Sprintf("rm-pub-%d", suffix)
	draftVersion := fmt.Sprintf("rm-draft-%d", suffix)
	publicName := fmt.Sprintf("rm-public-%d", suffix)
	draftName := fmt.Sprintf("rm-draft-asm-%d", suffix)

	var publishedID, draftID int64
	if err := tx.QueryRowContext(ctx,
		`INSERT INTO releases (version, name, status) VALUES ($1, $2, $3::release_status_enum) RETURNING id`,
		publicVersion, "readmodel published", "published",
	).Scan(&publishedID); err != nil {
		t.Fatalf("insert published release: %v", err)
	}
	if err := tx.QueryRowContext(ctx,
		`INSERT INTO releases (version, name, status) VALUES ($1, $2, $3::release_status_enum) RETURNING id`,
		draftVersion, "readmodel draft", "draft",
	).Scan(&draftID); err != nil {
		t.Fatalf("insert draft release: %v", err)
	}

	if _, err := tx.ExecContext(ctx,
		`INSERT INTO assemblies (name, species, version, release_id, is_default)
		 VALUES ($1, $2, $3, $4, $5)`, publicName, "Glycine max", "v1", publishedID, false,
	); err != nil {
		t.Fatalf("insert public assembly: %v", err)
	}
	if _, err := tx.ExecContext(ctx,
		`INSERT INTO assemblies (name, species, version, release_id, is_default)
		 VALUES ($1, $2, $3, $4, $5)`, draftName, "Glycine max", "v2", draftID, true,
	); err != nil {
		t.Fatalf("insert draft assembly: %v", err)
	}

	// The singleton pointer names the DRAFT release. The join in
	// publishedReleaseSQL must drop it, so the public endpoint sees nothing.
	if _, err := tx.ExecContext(ctx, `DELETE FROM active_release WHERE id = 1`); err != nil {
		t.Fatalf("clear active release: %v", err)
	}
	if _, err := tx.ExecContext(ctx,
		`INSERT INTO active_release (id, release_id) VALUES (1,$1)`, draftID,
	); err != nil {
		t.Fatalf("point at draft: %v", err)
	}

	store, err := NewStore(ctx, tx)
	if err != nil {
		t.Fatalf("new store: %v", err)
	}
	defer func() { _ = store.Close() }()

	items, err := store.Assemblies(ctx)
	if err != nil {
		t.Fatalf("assemblies: %v", err)
	}
	if len(items) != 0 {
		t.Fatalf("draft release must publish no assemblies, got %+v", items)
	}

	// Now point the active pointer at the published release.
	if _, err := tx.ExecContext(ctx,
		`UPDATE active_release SET release_id = $1 WHERE id = 1`, publishedID,
	); err != nil {
		t.Fatalf("point at published: %v", err)
	}
	items, err = store.Assemblies(ctx)
	if err != nil {
		t.Fatalf("assemblies: %v", err)
	}
	if len(items) != 1 || items[0].Name != publicName {
		t.Fatalf("expected the published assembly %q, got %+v", publicName, items)
	}
	if items[0].ID == "" || items[0].Species != "Glycine max" || items[0].Version != "v1" {
		t.Fatalf("public fields missing from response: %+v", items[0])
	}
}

// The chromosome route carries a stronger rule than the assembly list: an
// assembly outside the published release must not answer "200 + []", because
// that would claim the assembly exists and has no chromosomes. It answers the
// same 404 as an unknown assembly, with no row data in the error.
func TestChromosomesAgainstPostgres(t *testing.T) {
	raw := strings.TrimSpace(os.Getenv("SOYMUTDB_GATEWAY_TEST_DATABASE_URL"))
	if raw == "" {
		t.Skip("SOYMUTDB_GATEWAY_TEST_DATABASE_URL is not set")
	}
	db, err := sql.Open("postgres", strings.Replace(raw, "postgresql+asyncpg://", "postgres://", 1))
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	defer db.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	defer func() { _ = tx.Rollback() }()

	suffix := time.Now().UnixNano()
	releaseVersion := fmt.Sprintf("rm-chr-pub-%d", suffix)
	var publishedID int64
	if err := tx.QueryRowContext(ctx,
		`INSERT INTO releases (version, name, status) VALUES ($1, $2, $3::release_status_enum) RETURNING id`,
		releaseVersion, "readmodel chromosomes", "published",
	).Scan(&publishedID); err != nil {
		t.Fatalf("insert release: %v", err)
	}

	assemblyName := fmt.Sprintf("rm-chr-asm-%d", suffix)
	var assemblyID int64
	if err := tx.QueryRowContext(ctx,
		`INSERT INTO assemblies (name, species, version, release_id, is_default)
		 VALUES ($1, $2, $3, $4, $5) RETURNING id`,
		assemblyName, "Glycine max", "v1", publishedID, false,
	).Scan(&assemblyID); err != nil {
		t.Fatalf("insert assembly: %v", err)
	}
	for i, name := range []string{"Gm01", "Gm02"} {
		if _, err := tx.ExecContext(ctx,
			`INSERT INTO chromosomes (assembly_id, name, length, "order")
			 VALUES ($1, $2, $3, $4)`,
			assemblyID, name, int64(1000+i), i+1,
		); err != nil {
			t.Fatalf("insert chromosome %s: %v", name, err)
		}
	}

	// An assembly of a different release must be refused, not answered empty.
	otherVersion := fmt.Sprintf("rm-chr-other-%d", suffix)
	var otherReleaseID int64
	if err := tx.QueryRowContext(ctx,
		`INSERT INTO releases (version, name, status) VALUES ($1, $2, $3::release_status_enum) RETURNING id`,
		otherVersion, "readmodel other", "draft",
	).Scan(&otherReleaseID); err != nil {
		t.Fatalf("insert other release: %v", err)
	}
	otherAssemblyName := fmt.Sprintf("rm-chr-other-asm-%d", suffix)
	var otherAssemblyID int64
	if err := tx.QueryRowContext(ctx,
		`INSERT INTO assemblies (name, species, version, release_id, is_default)
		 VALUES ($1, $2, $3, $4, $5) RETURNING id`,
		otherAssemblyName, "Glycine max", "v2", otherReleaseID, false,
	).Scan(&otherAssemblyID); err != nil {
		t.Fatalf("insert other assembly: %v", err)
	}

	if _, err := tx.ExecContext(ctx, `DELETE FROM active_release WHERE id = 1`); err != nil {
		t.Fatalf("clear active release: %v", err)
	}
	if _, err := tx.ExecContext(ctx,
		`INSERT INTO active_release (id, release_id) VALUES (1,$1)`, publishedID,
	); err != nil {
		t.Fatalf("point at published: %v", err)
	}

	store, err := NewStore(ctx, tx)
	if err != nil {
		t.Fatalf("new store: %v", err)
	}
	defer func() { _ = store.Close() }()

	items, err := store.Chromosomes(ctx, assemblyID)
	if err != nil {
		t.Fatalf("chromosomes: %v", err)
	}
	if len(items) != 2 || items[0].Name != "Gm01" || items[0].Order != 1 {
		t.Fatalf("unexpected chromosomes: %+v", items)
	}
	if items[0].AssemblyID == "" || items[0].Length != 1000 {
		t.Fatalf("public fields missing: %+v", items[0])
	}

	// The other release's assembly is not in scope: refuse it.
	if _, err := store.Chromosomes(ctx, otherAssemblyID); !errors.Is(err, ErrAssemblyNotInScope) {
		t.Fatalf("out-of-scope assembly: err = %v, want ErrAssemblyNotInScope", err)
	}
	// An assembly that does not exist at all is refused the same way.
	if _, err := store.Chromosomes(ctx, 999999); !errors.Is(err, ErrAssemblyNotInScope) {
		t.Fatalf("unknown assembly: err = %v, want ErrAssemblyNotInScope", err)
	}
}

// The active-release pointer answers the empty object while nothing is
// published, and the release row once a published one is active.
func TestActiveReleaseAgainstPostgres(t *testing.T) {
	raw := strings.TrimSpace(os.Getenv("SOYMUTDB_GATEWAY_TEST_DATABASE_URL"))
	if raw == "" {
		t.Skip("SOYMUTDB_GATEWAY_TEST_DATABASE_URL is not set")
	}
	db, err := sql.Open("postgres", strings.Replace(raw, "postgresql+asyncpg://", "postgres://", 1))
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	defer db.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	defer func() { _ = tx.Rollback() }()

	suffix := time.Now().UnixNano()
	version := fmt.Sprintf("rm-active-%d", suffix)
	var publishedID int64
	if err := tx.QueryRowContext(ctx,
		`INSERT INTO releases (version, name, status, published_at)
		 VALUES ($1, $2, $3::release_status_enum, $4) RETURNING id`,
		version, "readmodel active", "published", time.Now().UTC(),
	).Scan(&publishedID); err != nil {
		t.Fatalf("insert release: %v", err)
	}

	if _, err := tx.ExecContext(ctx, `DELETE FROM active_release WHERE id = 1`); err != nil {
		t.Fatalf("clear active release: %v", err)
	}
	if _, err := tx.ExecContext(ctx,
		`INSERT INTO active_release (id, release_id) VALUES (1,$1)`, publishedID,
	); err != nil {
		t.Fatalf("point at published: %v", err)
	}

	store, err := NewStore(ctx, tx)
	if err != nil {
		t.Fatalf("new store: %v", err)
	}
	defer func() { _ = store.Close() }()

	active, err := store.ActiveRelease(ctx)
	if err != nil {
		t.Fatalf("active release: %v", err)
	}
	if active.ReleaseID == nil || *active.ReleaseID != fmt.Sprintf("%d", publishedID) {
		t.Fatalf("unexpected release id: %+v", active)
	}
	if active.Version == nil || *active.Version != version {
		t.Fatalf("unexpected version: %+v", active)
	}
	if active.PublishedAt == nil {
		t.Fatalf("published_at missing: %+v", active)
	}

	// Point at a draft: the answer is the empty object, not the draft.
	draftVersion := fmt.Sprintf("rm-active-draft-%d", suffix)
	var draftID int64
	if err := tx.QueryRowContext(ctx,
		`INSERT INTO releases (version, name, status) VALUES ($1, $2, $3::release_status_enum) RETURNING id`,
		draftVersion, "readmodel active draft", "draft",
	).Scan(&draftID); err != nil {
		t.Fatalf("insert draft: %v", err)
	}
	if _, err := tx.ExecContext(ctx,
		`UPDATE active_release SET release_id = $1 WHERE id = 1`, draftID,
	); err != nil {
		t.Fatalf("point at draft: %v", err)
	}
	active, err = store.ActiveRelease(ctx)
	if err != nil {
		t.Fatalf("active release: %v", err)
	}
	if active.ReleaseID != nil || active.Version != nil {
		t.Fatalf("a draft must not be reported as active: %+v", active)
	}
}
