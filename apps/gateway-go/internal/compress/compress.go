// Package compress applies gzip content encoding to responses that can use it.
//
// Brotli is deliberately absent: the standard library has no brotli encoder and
// the gateway's dependency tree is vendored and offline, so `br` would cost a
// third-party module. gzip is negotiated from Accept-Encoding and advertised
// with Vary so a shared cache never hands a compressed body to a client that
// did not ask for one.
package compress

import (
	"compress/gzip"
	"io"
	"mime"
	"net/http"
	"strconv"
	"strings"
	"sync"
)

// minSizeBytes is the smallest known body worth compressing. Below it the gzip
// header and trailer (18 bytes) dominate the saving, and every static artifact
// asset that matters is far larger.
const minSizeBytes = 512

// compressibleTypes are the media types this server compresses. Anything else
// (fonts, images, archives, protobuf) is already compressed or would only grow.
var compressibleTypes = map[string]bool{
	"application/json":          true,
	"application/javascript":    true,
	"application/xml":           true,
	"application/manifest+json": true,
	"image/svg+xml":             true,
}

var gzipPool = sync.Pool{
	New: func() any {
		// BestSpeed: the gateway is a latency-sensitive front door and the
		// artifacts are small text files, so the extra ratio of the default
		// level costs more CPU per request than it saves on the wire.
		writer, err := gzip.NewWriterLevel(io.Discard, gzip.BestSpeed)
		if err != nil {
			panic("compress: gzip level rejected: " + err.Error())
		}
		return writer
	},
}

// WithGzip wraps next with gzip negotiation.
func WithGzip(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writer := &responseWriter{ResponseWriter: w, request: r}
		defer writer.close()
		next.ServeHTTP(writer, r)
	})
}

type responseWriter struct {
	http.ResponseWriter
	request  *http.Request
	gzip     *gzip.Writer
	compress bool
	decided  bool
}

func (w *responseWriter) WriteHeader(status int) {
	if w.decided {
		w.ResponseWriter.WriteHeader(status)
		return
	}
	w.decided = true

	header := w.ResponseWriter.Header()
	if !eligible(w.request, header, status) {
		w.ResponseWriter.WriteHeader(status)
		return
	}
	// The resource is negotiable: advertise that even when this client gets the
	// identity body, so a shared cache keeps one variant per Accept-Encoding.
	w.addVary(header)
	if !compressible(w.request, header) {
		w.ResponseWriter.WriteHeader(status)
		return
	}
	// A compressed body has a different length than the file it came from, and
	// the length is not known before the stream ends.
	header.Del("Content-Length")
	header.Set("Content-Encoding", "gzip")
	w.compress = true
	w.ResponseWriter.WriteHeader(status)
}

func (w *responseWriter) Write(p []byte) (int, error) {
	if !w.decided {
		w.WriteHeader(http.StatusOK)
	}
	if !w.compress {
		return w.ResponseWriter.Write(p)
	}
	if w.gzip == nil {
		// The encoder is created on the first body byte, not in WriteHeader: a
		// HEAD request has no body, so creating it there would emit an empty
		// gzip stream and report its 23 bytes as Content-Length.
		w.gzip = gzipPool.Get().(*gzip.Writer)
		w.gzip.Reset(w.ResponseWriter)
	}
	return w.gzip.Write(p)
}

// Flush keeps a streamed proxied response streamed: the gzip buffer is pushed
// out with each flush instead of at the end of the body.
func (w *responseWriter) Flush() {
	if w.gzip != nil {
		_ = w.gzip.Flush()
	}
	if flusher, ok := w.ResponseWriter.(http.Flusher); ok {
		flusher.Flush()
	}
}

// Unwrap exposes the underlying writer to http.ResponseController, which is how
// httputil.ReverseProxy reaches Flush.
func (w *responseWriter) Unwrap() http.ResponseWriter {
	return w.ResponseWriter
}

func (w *responseWriter) close() {
	if w.gzip == nil {
		return
	}
	_ = w.gzip.Close()
	gzipPool.Put(w.gzip)
	w.gzip = nil
}

// addVary advertises the negotiation even when a body is not compressed, so a
// cache stores one variant per Accept-Encoding value.
func (w *responseWriter) addVary(header http.Header) {
	for _, value := range header.Values("Vary") {
		if strings.Contains(strings.ToLower(value), "accept-encoding") {
			return
		}
	}
	header.Add("Vary", "Accept-Encoding")
}

// eligible decides whether a response is negotiable at all, independent of what
// this client accepts. Both the static handler and the reverse proxy reach this
// through the same writer, so the rules and the streaming behaviour cannot
// drift apart.
func eligible(request *http.Request, header http.Header, status int) bool {
	if request.Method != http.MethodGet && request.Method != http.MethodHead {
		return false
	}
	// A range request expects byte offsets of the stored entity; re-encoding it
	// would make the offsets meaningless.
	if request.Header.Get("Range") != "" {
		return false
	}
	// 206 and 304 describe a stored entity, and the rest carry no body.
	if status != http.StatusOK {
		return false
	}
	if header.Get("Content-Encoding") != "" {
		// The upstream already encoded it; re-encoding would double-compress.
		return false
	}
	return compressibleContentType(header.Get("Content-Type"))
}

// compressible decides whether this request gets gzip on an eligible response.
func compressible(request *http.Request, header http.Header) bool {
	if !acceptsGzip(request.Header.Get("Accept-Encoding")) {
		return false
	}
	if length := header.Get("Content-Length"); length != "" {
		if size, err := strconv.ParseInt(length, 10, 64); err == nil && size < minSizeBytes {
			return false
		}
	}
	return true
}

func compressibleContentType(value string) bool {
	if value == "" {
		return false
	}
	mediaType, _, err := mime.ParseMediaType(value)
	if err != nil {
		mediaType = strings.TrimSpace(strings.Split(value, ";")[0])
	}
	if strings.HasPrefix(mediaType, "text/") {
		return true
	}
	return compressibleTypes[mediaType]
}

// acceptsGzip parses Accept-Encoding with its q-values. An explicit gzip entry
// wins over a wildcard; q=0 is a refusal.
func acceptsGzip(header string) bool {
	explicit, wildcard := -1.0, -1.0
	for _, entry := range strings.Split(header, ",") {
		fields := strings.Split(entry, ";")
		token := strings.ToLower(strings.TrimSpace(fields[0]))
		quality := 1.0
		for _, parameter := range fields[1:] {
			parameter = strings.TrimSpace(parameter)
			if !strings.HasPrefix(strings.ToLower(parameter), "q=") {
				continue
			}
			value, err := strconv.ParseFloat(strings.TrimSpace(parameter[2:]), 64)
			if err != nil {
				quality = 0
				continue
			}
			quality = value
		}
		switch token {
		case "gzip", "x-gzip":
			if quality > explicit {
				explicit = quality
			}
		case "*":
			if quality > wildcard {
				wildcard = quality
			}
		}
	}
	if explicit >= 0 {
		return explicit > 0
	}
	return wildcard > 0
}
