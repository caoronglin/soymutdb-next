package readmodel

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
)

// Publication is the public shape of schemas.content.PublicationResponse. The
// persistence key is not part of the contract: a publication is addressed by
// its DOI.
type Publication struct {
	Title      string  `json:"title"`
	TitleZH    *string `json:"title_zh"`
	Authors    string  `json:"authors"`
	AuthorsZH  *string `json:"authors_zh"`
	Journal    *string `json:"journal"`
	Year       *int64  `json:"year"`
	DOI        *string `json:"doi"`
	PMID       *string `json:"pmid"`
	Abstract   *string `json:"abstract"`
	AbstractZH *string `json:"abstract_zh"`
	IsFeatured bool    `json:"is_featured"`
	CreatedAt  string  `json:"created_at"`
}

// StaticPage is the public shape of schemas.content.StaticPageResponse.
type StaticPage struct {
	ID        string  `json:"id"`
	Slug      string  `json:"slug"`
	TitleEN   string  `json:"title_en"`
	TitleZH   *string `json:"title_zh"`
	ContentEN string  `json:"content_en"`
	ContentZH *string `json:"content_zh"`
	Status    string  `json:"status"`
	Category  *string `json:"category"`
	Summary   *string `json:"summary"`
	SortOrder int64   `json:"sort_order"`
	CreatedAt string  `json:"created_at"`
	UpdatedAt string  `json:"updated_at"`
}

// DownloadFile is the public shape of schemas.content.DownloadFileResponse.
type DownloadFile struct {
	ID            string  `json:"id"`
	Name          string  `json:"name"`
	Description   *string `json:"description"`
	FileURL       string  `json:"file_url"`
	FileSize      *int64  `json:"file_size"`
	Category      *string `json:"category"`
	DownloadCount int64   `json:"download_count"`
	CreatedAt     string  `json:"created_at"`
	SHA256        *string `json:"sha256"`
	License       *string `json:"license"`
	GeneratedAt   *string `json:"generated_at"`
	SourceRef     *string `json:"source_ref"`
}

// TrackCategory is the public shape of the track-category list. The Python
// endpoint answers a list of free-form dictionaries, so the same keys are
// reproduced here rather than a stricter projection.
type TrackCategory struct {
	ID           int64  `json:"id"`
	Name         string `json:"name"`
	DisplayOrder int64  `json:"display_order"`
}

const publicationsSQL = `
SELECT p.title, p.title_zh, p.authors, p.authors_zh, p.journal, p.year,
       p.doi, p.pmid, p.abstract, p.abstract_zh, p.is_featured,
       to_char(p.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
FROM publications p
ORDER BY p.year DESC NULLS LAST, p.id DESC
LIMIT $1`

const staticPagesSQL = `
SELECT p.id, p.slug, p.title_en, p.title_zh, p.content_en, p.content_zh,
       p.status, p.category, p.summary, p.sort_order,
       to_char(p.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
       to_char(p.updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
FROM static_pages p
WHERE p.status = 'published'
ORDER BY p.sort_order ASC, p.slug`

// Download files belong to the resolved published release: the column is
// nullable, and a file that is not bound to a release (or bound to another
// one) must not be listed.
const downloadFilesSQL = `
SELECT d.id, d.name, d.description, d.file_url, d.file_size, d.category,
       d.download_count,
       to_char(d.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
       d.sha256, d.license,
       CASE WHEN date_part('microseconds', d.generated_at) = 0
            THEN to_char(d.generated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
            ELSE to_char(d.generated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
       END,
       d.source_ref
FROM download_files d
WHERE d.release_id = $1
  AND ($2::text IS NULL OR d.category = $2)
ORDER BY d.created_at DESC`

const trackCategoriesSQL = `
SELECT c.id, c.name, c.display_order
FROM track_categories c
ORDER BY c.display_order`

// ContentStore holds the statements for the admin-authored public content:
// publications, static pages, downloadable files and track categories. It is a
// separate store from the genomic read model so the two can grow apart.
type ContentStore struct {
	publications    *sql.Stmt
	staticPages     *sql.Stmt
	downloadFiles   *sql.Stmt
	trackCategories *sql.Stmt
}

// NewContentStore prepares the content statements.
func NewContentStore(ctx context.Context, db Querier) (*ContentStore, error) {
	publications, err := db.PrepareContext(ctx, publicationsSQL)
	if err != nil {
		return nil, fmt.Errorf("readmodel: prepare publications: %w", err)
	}
	pages, err := db.PrepareContext(ctx, staticPagesSQL)
	if err != nil {
		_ = publications.Close()
		return nil, fmt.Errorf("readmodel: prepare static pages: %w", err)
	}
	downloads, err := db.PrepareContext(ctx, downloadFilesSQL)
	if err != nil {
		_ = publications.Close()
		_ = pages.Close()
		return nil, fmt.Errorf("readmodel: prepare download files: %w", err)
	}
	categories, err := db.PrepareContext(ctx, trackCategoriesSQL)
	if err != nil {
		_ = publications.Close()
		_ = pages.Close()
		_ = downloads.Close()
		return nil, fmt.Errorf("readmodel: prepare track categories: %w", err)
	}
	return &ContentStore{
		publications:    publications,
		staticPages:     pages,
		downloadFiles:   downloads,
		trackCategories: categories,
	}, nil
}

// Close releases the prepared statements.
func (s *ContentStore) Close() error {
	return errors.Join(
		s.publications.Close(),
		s.staticPages.Close(),
		s.downloadFiles.Close(),
		s.trackCategories.Close(),
	)
}

// Publications returns the publication list, newest year first.
func (s *ContentStore) Publications(ctx context.Context, limit int) ([]Publication, error) {
	if limit < 1 {
		limit = 20
	}
	if limit > 100 {
		limit = 100
	}
	rows, err := s.publications.QueryContext(ctx, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	items := make([]Publication, 0)
	for rows.Next() {
		var item Publication
		var titleZH, authorsZH, journal, doi, pmid, abstract, abstractZH sql.NullString
		var year sql.NullInt64
		if err := rows.Scan(
			&item.Title, &titleZH, &item.Authors, &authorsZH, &journal, &year,
			&doi, &pmid, &abstract, &abstractZH, &item.IsFeatured, &item.CreatedAt,
		); err != nil {
			return nil, err
		}
		assignOptional(&titleZH, &item.TitleZH)
		assignOptional(&authorsZH, &item.AuthorsZH)
		assignOptional(&journal, &item.Journal)
		assignOptional(&doi, &item.DOI)
		assignOptional(&pmid, &item.PMID)
		assignOptional(&abstract, &item.Abstract)
		assignOptional(&abstractZH, &item.AbstractZH)
		if year.Valid {
			value := year.Int64
			item.Year = &value
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

// StaticPages returns the published static pages in display order.
func (s *ContentStore) StaticPages(ctx context.Context) ([]StaticPage, error) {
	rows, err := s.staticPages.QueryContext(ctx)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	items := make([]StaticPage, 0)
	for rows.Next() {
		var item StaticPage
		var titleZH, contentZH, category, summary sql.NullString
		if err := rows.Scan(
			&item.ID, &item.Slug, &item.TitleEN, &titleZH, &item.ContentEN, &contentZH,
			&item.Status, &category, &summary, &item.SortOrder,
			&item.CreatedAt, &item.UpdatedAt,
		); err != nil {
			return nil, err
		}
		assignOptional(&titleZH, &item.TitleZH)
		assignOptional(&contentZH, &item.ContentZH)
		assignOptional(&category, &item.Category)
		assignOptional(&summary, &item.Summary)
		items = append(items, item)
	}
	return items, rows.Err()
}

// DownloadFiles returns the downloadable files of the published release.
func (s *ContentStore) DownloadFiles(ctx context.Context, releaseID int64, category *string) ([]DownloadFile, error) {
	rows, err := s.downloadFiles.QueryContext(ctx, releaseID, category)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	items := make([]DownloadFile, 0)
	for rows.Next() {
		var item DownloadFile
		var description, fileCategory, sha256, license, generatedAt, sourceRef sql.NullString
		var fileSize sql.NullInt64
		if err := rows.Scan(
			&item.ID, &item.Name, &description, &item.FileURL, &fileSize, &fileCategory,
			&item.DownloadCount, &item.CreatedAt, &sha256, &license, &generatedAt, &sourceRef,
		); err != nil {
			return nil, err
		}
		assignOptional(&description, &item.Description)
		assignOptional(&fileCategory, &item.Category)
		assignOptional(&sha256, &item.SHA256)
		assignOptional(&license, &item.License)
		assignOptional(&generatedAt, &item.GeneratedAt)
		assignOptional(&sourceRef, &item.SourceRef)
		if fileSize.Valid {
			value := fileSize.Int64
			item.FileSize = &value
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

// TrackCategories returns the track-category list.
func (s *ContentStore) TrackCategories(ctx context.Context) ([]TrackCategory, error) {
	rows, err := s.trackCategories.QueryContext(ctx)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	items := make([]TrackCategory, 0)
	for rows.Next() {
		var item TrackCategory
		if err := rows.Scan(&item.ID, &item.Name, &item.DisplayOrder); err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

// assignOptional copies a nullable column into an optional field. A NULL
// becomes an absent field, not an empty string.
func assignOptional(source *sql.NullString, target **string) {
	if source.Valid {
		value := source.String
		*target = &value
	}
}
