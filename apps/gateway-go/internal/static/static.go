// Package static serves the built admin console artifact from a directory.
//
// The admin console is a client-side single-page application with a manual
// route tree, so a request for a route that is not a file has to answer
// index.html. A request that names a file (a hashed chunk, a font, a
// stylesheet) must instead answer 404: returning the HTML shell with a 200 for
// a missing chunk turns a deploy mistake into a script-parse error in the
// browser.
package static

import (
	"encoding/json"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"strings"
)

// contentTypes is an explicit table instead of mime.TypeByExtension, which
// falls back to the host's mime.types database and therefore answers
// differently on two machines serving the same artifact.
var contentTypes = map[string]string{
	".html":  "text/html; charset=utf-8",
	".js":    "text/javascript; charset=utf-8",
	".mjs":   "text/javascript; charset=utf-8",
	".css":   "text/css; charset=utf-8",
	".json":  "application/json",
	".map":   "application/json",
	".svg":   "image/svg+xml",
	".woff2": "font/woff2",
	".woff":  "font/woff",
	".ttf":   "font/ttf",
	".png":   "image/png",
	".jpg":   "image/jpeg",
	".jpeg":  "image/jpeg",
	".gif":   "image/gif",
	".webp":  "image/webp",
	".ico":   "image/x-icon",
	".txt":   "text/plain; charset=utf-8",
	".wasm":  "application/wasm",
}

// hashedSegment matches umi/webpack content hashes anywhere in a file name.
// Hashed files are not confined to /assets/: this artifact also emits
// `umi.<hash>.js` and `<id>.<hash>.chunk.css` at the root, which is why
// immutability is decided by name shape rather than by directory.
var hashedSegment = regexp.MustCompile(`\.[0-9a-f]{8,}\.`)

// Handler serves one artifact directory.
type Handler struct {
	root  string
	index string
}

// New resolves root and fails closed when it is not a directory holding an
// index.html.
func New(root string) (*Handler, error) {
	absolute, err := filepath.Abs(strings.TrimSpace(root))
	if err != nil {
		return nil, err
	}
	info, err := os.Stat(absolute)
	if err != nil {
		return nil, err
	}
	if !info.IsDir() {
		return nil, &os.PathError{Op: "open", Path: absolute, Err: os.ErrInvalid}
	}
	index := filepath.Join(absolute, "index.html")
	indexInfo, err := os.Stat(index)
	if err != nil {
		return nil, err
	}
	if !indexInfo.Mode().IsRegular() {
		return nil, &os.PathError{Op: "open", Path: index, Err: os.ErrInvalid}
	}
	return &Handler{root: absolute, index: index}, nil
}

// Root is the resolved artifact directory.
func (h *Handler) Root() string { return h.root }

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		writeDetail(w, http.StatusMethodNotAllowed, "Method Not Allowed")
		return
	}

	urlPath, ok := requestPath(r.URL.Path)
	if !ok {
		writeDetail(w, http.StatusNotFound, "Not Found")
		return
	}

	filePath := filepath.Join(h.root, filepath.FromSlash(urlPath))
	if filePath != h.root && !strings.HasPrefix(filePath, h.root+string(os.PathSeparator)) {
		// Unreachable through requestPath, which cleans every request into a
		// rooted slash path; kept as the containment check that makes the join
		// safe to read on its own.
		writeDetail(w, http.StatusNotFound, "Not Found")
		return
	}
	if info, file, ok := openRegular(filePath); ok {
		defer func() { _ = file.Close() }()
		h.serveFile(w, r, urlPath, info, file)
		return
	}

	if documentRoute(urlPath) {
		h.serveIndex(w, r)
		return
	}
	writeDetail(w, http.StatusNotFound, "Not Found")
}

// requestPath turns the request URL path into a slash path rooted at "/". A
// path that cannot be expressed as one (an embedded NUL) is refused.
func requestPath(raw string) (string, bool) {
	if raw == "" || strings.ContainsRune(raw, 0) {
		return "", false
	}
	return path.Clean("/" + raw), true
}

// documentRoute reports whether a path may fall back to index.html: "/" or a
// segment without a file extension. Everything under /assets/ and /fonts/ is a
// file by definition, and a name with a dot names a file too.
func documentRoute(urlPath string) bool {
	if urlPath == "/" {
		return true
	}
	if strings.HasPrefix(urlPath, "/assets/") || strings.HasPrefix(urlPath, "/fonts/") {
		return false
	}
	return !strings.Contains(path.Base(urlPath), ".")
}

func (h *Handler) serveFile(w http.ResponseWriter, r *http.Request, urlPath string, info os.FileInfo, file *os.File) {
	header := w.Header()
	header.Set("Content-Type", contentType(urlPath))
	header.Set("Cache-Control", cacheControl(urlPath))
	header.Set("X-Content-Type-Options", "nosniff")
	setSecurityHeaders(header)
	// ServeContent answers Range and If-Modified-Since and keeps HEAD bodyless.
	http.ServeContent(w, r, info.Name(), info.ModTime(), file)
}

func (h *Handler) serveIndex(w http.ResponseWriter, r *http.Request) {
	file, err := os.Open(h.index)
	if err != nil {
		writeDetail(w, http.StatusNotFound, "Not Found")
		return
	}
	defer func() { _ = file.Close() }()
	info, err := file.Stat()
	if err != nil {
		writeDetail(w, http.StatusNotFound, "Not Found")
		return
	}
	// index.html is the only mutable document in the artifact: it names the
	// hashed chunks of the current build, so it must always revalidate.
	header := w.Header()
	header.Set("Content-Type", "text/html; charset=utf-8")
	header.Set("Cache-Control", "no-cache")
	header.Set("X-Content-Type-Options", "nosniff")
	setSecurityHeaders(header)
	http.ServeContent(w, r, "index.html", info.ModTime(), file)
}

// setSecurityHeaders adds the headers a document meta tag cannot express.
//
// The artifact's CSP is a <meta http-equiv="Content-Security-Policy"> in
// index.html, so it survives any front door that serves the HTML unchanged.
// `_headers` (Cloudflare Pages) is not read by this server; HSTS stays with the
// TLS-terminating front door because this process cannot know whether the
// client's connection was encrypted.
func setSecurityHeaders(header http.Header) {
	header.Set("Referrer-Policy", "strict-origin-when-cross-origin")
	header.Set("X-Frame-Options", "DENY")
	header.Set("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()")
}

func contentType(urlPath string) string {
	if value, ok := contentTypes[strings.ToLower(path.Ext(urlPath))]; ok {
		return value
	}
	return "application/octet-stream"
}

// cacheControl splits the artifact into three classes: hashed files never
// change under their name, HTML revalidates, and everything else (fonts, the
// favicon) gets an hour so a rebuild is picked up without a revalidation round
// trip per font file.
func cacheControl(urlPath string) string {
	if strings.HasPrefix(urlPath, "/assets/") || hashedSegment.MatchString(path.Base(urlPath)) {
		return "public, max-age=31536000, immutable"
	}
	if strings.EqualFold(path.Ext(urlPath), ".html") {
		return "no-cache"
	}
	return "public, max-age=3600"
}

// openRegular opens a regular file inside the artifact. A directory is
// reported as absent, so a request for one cannot be served as a body.
func openRegular(filePath string) (os.FileInfo, *os.File, bool) {
	file, err := os.Open(filePath)
	if err != nil {
		return nil, nil, false
	}
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() {
		_ = file.Close()
		return nil, nil, false
	}
	return info, file, true
}

func writeDetail(w http.ResponseWriter, status int, detail string) {
	body, err := json.Marshal(map[string]string{"detail": detail})
	if err != nil {
		panic("static: response body does not marshal: " + err.Error())
	}
	header := w.Header()
	header.Set("Content-Type", "application/json")
	header.Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(status)
	_, _ = w.Write(append(body, '\n'))
}
