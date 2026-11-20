// Package readmodel implements public, unauthenticated read endpoints that the
// gateway answers directly from PostgreSQL instead of forwarding to Python.
//
// Scope discipline (AGENTS.md and docs/dev/go-gateway.md):
//   - only GET, only published-release data, only the public whitelist of
//     fields;
//   - no writes, no import/release workflow, no permission logic — those stay
//     in Python;
//   - every endpoint is a pure function of the resolved *published* release,
//     so an unpublished record cannot appear through this path.
//
// The Python API remains authoritative for the contract. Each port here must
// be accompanied by a parity check against the Python response; the check is
// intentionally a separate gate so a gateway build can never silently redefine
// what the public API says.
package readmodel

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
)

// Querier is the database surface the read models need. Both *sql.DB and
// *sql.Tx satisfy it, so the integration test can run in a rolled-back
// transaction, exactly as the stats store does.
type Querier interface {
	QueryContext(ctx context.Context, query string, args ...any) (*sql.Rows, error)
	PrepareContext(ctx context.Context, query string) (*sql.Stmt, error)
}

// Assembly is the public shape of schemas.genomic.AssemblyResponse. Field
// order and JSON names are part of the wire contract.
type Assembly struct {
	ID          string  `json:"id"`
	Name        string  `json:"name"`
	Species     string  `json:"species"`
	Version     string  `json:"version"`
	Description *string `json:"description"`
	IsDefault   bool    `json:"is_default"`
	CreatedAt   *string `json:"created_at"`
	UpdatedAt   *string `json:"updated_at"`
}

// Chromosome is the public shape of schemas.genomic.ChromosomeResponse.
type Chromosome struct {
	ID         string `json:"id"`
	AssemblyID string `json:"assembly_id"`
	Name       string `json:"name"`
	Length     int64  `json:"length"`
	Order      int64  `json:"order"`
}

// News is the public shape of schemas.content.NewsResponse.
type News struct {
	ID          string  `json:"id"`
	TitleEN     string  `json:"title_en"`
	TitleZH     *string `json:"title_zh"`
	Slug        string  `json:"slug"`
	Category    *string `json:"category"`
	IsPublished bool    `json:"is_published"`
	PublishedAt *string `json:"published_at"`
	CreatedAt   string  `json:"created_at"`
	UpdatedAt   string  `json:"updated_at"`
}

// NewsSummary is the public shape of schemas.news.NewsSummaryResponse: the
// list-item view of an article, without the body content.
type NewsSummary struct {
	ID            string  `json:"id"`
	TitleEN       string  `json:"title_en"`
	TitleZH       *string `json:"title_zh"`
	Slug          string  `json:"slug"`
	Category      *string `json:"category"`
	CoverURL      *string `json:"cover_url"`
	CoverAssetID  *string `json:"cover_asset_id"`
	CoverAltText  *string `json:"cover_alt_text"`
	FeaturedSort  int64   `json:"featured_sort"`
	CarouselGroup *string `json:"carousel_group"`
	CarouselSort  int64   `json:"carousel_sort"`
	Status        string  `json:"status"`
	IsPublished   bool    `json:"is_published"`
	PublishedAt   *string `json:"published_at"`
	CreatedAt     string  `json:"created_at"`
	UpdatedAt     string  `json:"updated_at"`
}

// NewsList is the public shape of schemas.news.NewsListResponse.
type NewsList struct {
	Items    []NewsSummary `json:"items"`
	Total    int64         `json:"total"`
	Page     int64         `json:"page"`
	PageSize int64         `json:"page_size"`
}

// ActiveRelease is the public shape of schemas.content.ActiveReleaseResponse.
// Every field is optional: before the first publish the endpoint answers an
// empty object, which is an answer and not an error.
type ActiveRelease struct {
	ReleaseID   *string `json:"release_id"`
	Version     *string `json:"version"`
	PublishedAt *string `json:"published_at"`
}

// Store prepares the read statements once at startup. Prepared statements are
// a measured win with lib/pq (see internal/stats): without them every request
// pays a describe round trip and a fresh server-side plan.
type Store struct {
	// The admin-authored public content shares the connection and the
	// read-only session, so it lives in the same store rather than a second
	// one with its own lifecycle.
	*ContentStore

	publishedRelease *sql.Stmt
	assemblies       *sql.Stmt
	assemblyInScope  *sql.Stmt
	chromosomes      *sql.Stmt
	activeRelease    *sql.Stmt
	news             *sql.Stmt
	newsPage         *sql.Stmt
	newsCount        *sql.Stmt
}

// The active-release pointer is a singleton and must not be trusted blindly:
// a pointer to a draft or rolled-back release must not make that release's
// assemblies public. The join drops it. The preview fallback is deliberately
// absent — local preview data is opt-in on the Python side and must never be
// served by the public gateway.
const publishedReleaseSQL = `
SELECT r.id
FROM active_release ar
JOIN releases r ON r.id = ar.release_id
WHERE ar.id = 1 AND r.status = 'published'`

// The release filter is a bind parameter, never interpolated. An assembly
// linked to a draft or another release is invisible here.
// The existence check is separate from the row query on purpose. Filtering a
// join by release and returning whatever came back makes an assembly outside
// the release answer "200 + []", which tells the caller "that assembly exists
// and has no chromosomes" -- a claim the data never made, and one that
// discloses the existence of unpublished rows.
const assemblyInScopeSQL = `
SELECT a.id
FROM assemblies a
WHERE a.id = $1 AND a.release_id = $2`

const chromosomesSQL = `
SELECT c.id, c.assembly_id, c.name, c.length, c.order
FROM chromosomes c
WHERE c.assembly_id = $1
ORDER BY c.order`

// The active-release pointer, joined to the published release. A pointer to a
// draft or rolled-back release yields no row, which the caller renders as the
// empty answer the Python endpoint gives.
const activeReleaseSQL = `
SELECT r.id, r.version,
       CASE WHEN date_part('microseconds', r.published_at) = 0
            THEN to_char(r.published_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
            ELSE to_char(r.published_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
       END
FROM active_release ar
JOIN releases r ON r.id = ar.release_id
WHERE ar.id = 1 AND r.status = 'published'`

// The canonical public news predicates: not deleted, published in both the
// status column and the legacy boolean, and inside the visibility window.
// This is the same contract as the Python `public_news_visibility_conditions`.
const newsSQL = `
SELECT n.id, n.title_en, n.title_zh, n.slug, n.category, n.is_published,
       CASE WHEN date_part('microseconds', n.published_at) = 0
            THEN to_char(n.published_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
            ELSE to_char(n.published_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
       END,
       to_char(n.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
       to_char(n.updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
FROM news_articles n
WHERE n.deleted_at IS NULL
  AND n.status = 'published'
  AND n.is_published IS TRUE
  AND (n.visible_from IS NULL OR n.visible_from <= now())
  AND (n.visible_to IS NULL OR n.visible_to >= now())
ORDER BY n.published_at DESC
LIMIT $1`

// The paginated public list: the same visibility contract as `newsSQL`, with
// the optional category filter and the ordering the Python service uses
// (published_at descending with nulls last, then id descending).
const newsPageSQL = `
SELECT n.id, n.title_en, n.title_zh, n.slug, n.category, n.cover_url,
       n.cover_asset_id, n.cover_alt_text, n.featured_sort, n.carousel_group,
       n.carousel_sort, n.status, n.is_published,
       CASE WHEN date_part('microseconds', n.published_at) = 0
            THEN to_char(n.published_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
            ELSE to_char(n.published_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
       END,
       to_char(n.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
       to_char(n.updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
FROM news_articles n
WHERE n.deleted_at IS NULL
  AND n.status = 'published'
  AND n.is_published IS TRUE
  AND (n.visible_from IS NULL OR n.visible_from <= now())
  AND (n.visible_to IS NULL OR n.visible_to >= now())
  AND ($1::text IS NULL OR n.category = $1)
ORDER BY n.published_at DESC NULLS LAST, n.id DESC
LIMIT $2 OFFSET $3`

const newsCountSQL = `
SELECT count(*)
FROM news_articles n
WHERE n.deleted_at IS NULL
  AND n.status = 'published'
  AND n.is_published IS TRUE
  AND (n.visible_from IS NULL OR n.visible_from <= now())
  AND (n.visible_to IS NULL OR n.visible_to >= now())
  AND ($1::text IS NULL OR n.category = $1)`

const assembliesSQL = `
SELECT a.id, a.name, a.species, a.version, a.description,
       a.is_default,
       -- FastAPI serialises datetimes through pydantic's JSON mode: six
       -- fractional digits when present, omitted entirely when zero. A bare
       -- to_char without .US silently drops microseconds and fails byte-level
       -- parity with the Python response.
       CASE WHEN date_part('microseconds', a.created_at) = 0
            THEN to_char(a.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
            ELSE to_char(a.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
       END,
       CASE WHEN date_part('microseconds', a.updated_at) = 0
            THEN to_char(a.updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
            ELSE to_char(a.updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
       END
FROM assemblies a
WHERE a.release_id = $1
ORDER BY a.name`

// NewStore prepares all statements, failing closed if any cannot be prepared.
// stmtSet collects prepared statements so a failure part-way through the
// preparation closes exactly what was opened, in one place. Without it every
// error branch has to repeat the closing of every statement before it, which
// is both noisy and easy to get wrong when a statement is added.
type stmtSet struct {
	opened []*sql.Stmt
}

// prepare adds one statement to the set.
func (s *stmtSet) prepare(ctx context.Context, db Querier, query, label string) (*sql.Stmt, error) {
	stmt, err := db.PrepareContext(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("readmodel: prepare %s: %w", label, err)
	}
	s.opened = append(s.opened, stmt)
	return stmt, nil
}

// closeAll releases every statement prepared so far. The close errors are
// deliberately not reported: the connection is being torn down anyway, and the
// statement whose preparation failed is the error worth reporting.
func (s *stmtSet) closeAll() {
	for _, stmt := range s.opened {
		_ = stmt.Close()
	}
}

// NewStore prepares every read statement, failing closed if any cannot be
// prepared.
func NewStore(ctx context.Context, db Querier) (*Store, error) {
	var set stmtSet
	release, err := set.prepare(ctx, db, publishedReleaseSQL, "published release")
	if err != nil {
		return nil, err
	}
	assemblies, err := set.prepare(ctx, db, assembliesSQL, "assemblies")
	if err != nil {
		set.closeAll()
		return nil, err
	}
	inScope, err := set.prepare(ctx, db, assemblyInScopeSQL, "assembly scope")
	if err != nil {
		set.closeAll()
		return nil, err
	}
	chromosomes, err := set.prepare(ctx, db, chromosomesSQL, "chromosomes")
	if err != nil {
		set.closeAll()
		return nil, err
	}
	news, err := set.prepare(ctx, db, newsSQL, "news")
	if err != nil {
		set.closeAll()
		return nil, err
	}
	newsPage, err := set.prepare(ctx, db, newsPageSQL, "news page")
	if err != nil {
		set.closeAll()
		return nil, err
	}
	newsCount, err := set.prepare(ctx, db, newsCountSQL, "news count")
	if err != nil {
		set.closeAll()
		return nil, err
	}
	active, err := set.prepare(ctx, db, activeReleaseSQL, "active release")
	if err != nil {
		set.closeAll()
		return nil, err
	}
	content, err := NewContentStore(ctx, db)
	if err != nil {
		set.closeAll()
		return nil, err
	}
	return &Store{
		ContentStore:     content,
		publishedRelease: release,
		assemblies:       assemblies,
		assemblyInScope:  inScope,
		chromosomes:      chromosomes,
		news:             news,
		newsPage:         newsPage,
		newsCount:        newsCount,
		activeRelease:    active,
	}, nil
}

// Close releases the prepared statements.
func (s *Store) Close() error {
	return errors.Join(
		s.ContentStore.Close(),
		s.publishedRelease.Close(),
		s.assemblies.Close(),
		s.assemblyInScope.Close(),
		s.chromosomes.Close(),
		s.news.Close(),
		s.newsPage.Close(),
		s.newsCount.Close(),
		s.activeRelease.Close(),
	)
}

// PublishedReleaseID resolves the active published release. A database with no
// published release is not an error: the public surface answers an empty list,
// exactly as the Python endpoint does after its preview fallback is disabled.
// The id is nil in that case.
func (s *Store) PublishedReleaseID(ctx context.Context) (*int64, error) {
	var id int64
	if err := s.publishedRelease.QueryRowContext(ctx).Scan(&id); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return &id, nil
}

// Assemblies returns the assemblies of the active published release.
// An empty slice means "nothing published", never "the query failed".
func (s *Store) Assemblies(ctx context.Context) ([]Assembly, error) {
	releaseID, err := s.PublishedReleaseID(ctx)
	if err != nil {
		return nil, err
	}
	if releaseID == nil {
		return []Assembly{}, nil
	}

	rows, err := s.assemblies.QueryContext(ctx, *releaseID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	items := make([]Assembly, 0)
	for rows.Next() {
		var item Assembly
		var created, updated sql.NullString
		if err := rows.Scan(
			&item.ID, &item.Name, &item.Species, &item.Version, &item.Description,
			&item.IsDefault, &created, &updated,
		); err != nil {
			return nil, err
		}
		if created.Valid {
			item.CreatedAt = &created.String
		}
		if updated.Valid {
			item.UpdatedAt = &updated.String
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

// ErrAssemblyNotInScope reports that the assembly does not belong to the
// published release. It is a distinct answer from "the assembly has no
// chromosomes": the Python API answers 404 for both an unknown and an
// out-of-scope assembly, and never discloses an unpublished row.
var ErrAssemblyNotInScope = errors.New("readmodel: assembly is not available in this release")

// Chromosomes returns the chromosomes of one assembly, only when the assembly
// belongs to the published release. An assembly outside the release answers
// ErrAssemblyNotInScope rather than an empty list.
func (s *Store) Chromosomes(ctx context.Context, assemblyID int64) ([]Chromosome, error) {
	releaseID, err := s.PublishedReleaseID(ctx)
	if err != nil {
		return nil, err
	}
	if releaseID == nil {
		return nil, ErrAssemblyNotInScope
	}

	var scoped int64
	if err := s.assemblyInScope.QueryRowContext(ctx, assemblyID, *releaseID).Scan(&scoped); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, ErrAssemblyNotInScope
		}
		return nil, err
	}

	rows, err := s.chromosomes.QueryContext(ctx, assemblyID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	items := make([]Chromosome, 0)
	for rows.Next() {
		var item Chromosome
		if err := rows.Scan(&item.ID, &item.AssemblyID, &item.Name, &item.Length, &item.Order); err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

// News returns the published news articles, newest first. The limit is
// clamped to the same range the Python query parameter allows, so the two
// services cannot answer different ranges for the same request.
func (s *Store) News(ctx context.Context, limit int) ([]News, error) {
	if limit < 1 {
		limit = 1
	}
	if limit > 100 {
		limit = 100
	}
	rows, err := s.news.QueryContext(ctx, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	items := make([]News, 0)
	for rows.Next() {
		var item News
		var titleZH, category, publishedAt sql.NullString
		if err := rows.Scan(
			&item.ID, &item.TitleEN, &titleZH, &item.Slug, &category, &item.IsPublished,
			&publishedAt, &item.CreatedAt, &item.UpdatedAt,
		); err != nil {
			return nil, err
		}
		assignOptional(&titleZH, &item.TitleZH)
		assignOptional(&category, &item.Category)
		assignOptional(&publishedAt, &item.PublishedAt)
		items = append(items, item)
	}
	return items, rows.Err()
}

// NewsPage returns one page of the published news list with the total count,
// matching the Python service's pagination envelope.
func (s *Store) NewsPage(ctx context.Context, category *string, page, pageSize int) (NewsList, error) {
	if page < 1 {
		page = 1
	}
	if pageSize < 1 {
		pageSize = 20
	}
	if pageSize > 200 {
		pageSize = 200
	}
	offset := (page - 1) * pageSize

	var total int64
	if err := s.newsCount.QueryRowContext(ctx, category).Scan(&total); err != nil {
		return NewsList{}, err
	}

	rows, err := s.newsPage.QueryContext(ctx, category, pageSize, offset)
	if err != nil {
		return NewsList{}, err
	}
	defer rows.Close()

	items := make([]NewsSummary, 0)
	for rows.Next() {
		item, err := scanNewsSummary(rows)
		if err != nil {
			return NewsList{}, err
		}
		items = append(items, item)
	}
	if err := rows.Err(); err != nil {
		return NewsList{}, err
	}
	return NewsList{Items: items, Total: total, Page: int64(page), PageSize: int64(pageSize)}, nil
}

// scanNewsSummary reads one row of newsPageSQL. The nullable columns are
// pointers in the response, so a NULL becomes an absent field rather than an
// empty string.
func scanNewsSummary(rows *sql.Rows) (NewsSummary, error) {
	var item NewsSummary
	var titleZH, category, coverURL, coverAssetID, coverAltText, carouselGroup sql.NullString
	var publishedAt sql.NullString
	if err := rows.Scan(
		&item.ID, &item.TitleEN, &titleZH, &item.Slug, &category, &coverURL,
		&coverAssetID, &coverAltText, &item.FeaturedSort, &carouselGroup,
		&item.CarouselSort, &item.Status, &item.IsPublished, &publishedAt,
		&item.CreatedAt, &item.UpdatedAt,
	); err != nil {
		return NewsSummary{}, err
	}
	for _, field := range []struct {
		valid sql.NullString
		into  **string
	}{
		{titleZH, &item.TitleZH},
		{category, &item.Category},
		{coverURL, &item.CoverURL},
		{coverAssetID, &item.CoverAssetID},
		{coverAltText, &item.CoverAltText},
		{carouselGroup, &item.CarouselGroup},
		{publishedAt, &item.PublishedAt},
	} {
		if field.valid.Valid {
			value := field.valid.String
			*field.into = &value
		}
	}
	return item, nil
}

// ActiveRelease returns the release the public surface currently serves. With
// no published release it answers the empty object, exactly like Python.
func (s *Store) ActiveRelease(ctx context.Context) (ActiveRelease, error) {
	var (
		id        int64
		version   string
		published sql.NullString
	)
	if err := s.activeRelease.QueryRowContext(ctx).Scan(&id, &version, &published); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return ActiveRelease{}, nil
		}
		return ActiveRelease{}, err
	}
	idText := fmt.Sprintf("%d", id)
	result := ActiveRelease{ReleaseID: &idText, Version: &version}
	if published.Valid {
		value := published.String
		result.PublishedAt = &value
	}
	return result, nil
}
