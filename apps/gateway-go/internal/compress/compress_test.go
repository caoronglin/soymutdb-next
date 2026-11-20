package compress

import (
	"compress/gzip"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestAcceptsGzip(t *testing.T) {
	cases := []struct {
		header string
		want   bool
	}{
		{header: "", want: false},
		{header: "gzip", want: true},
		{header: "GZip", want: true},
		{header: "x-gzip", want: true},
		{header: "br", want: false},
		{header: "br, gzip", want: true},
		{header: "gzip;q=0", want: false},
		{header: "gzip; q=0.0", want: false},
		{header: "gzip;q=0.5", want: true},
		{header: "br;q=1.0, gzip;q=0.1", want: true},
		{header: "*", want: true},
		{header: "identity", want: false},
		{header: "identity, *;q=0", want: false},
		{header: "br;q=1, *;q=0", want: false},
		{header: "gzip;q=0, *", want: false}, // an explicit refusal wins
	}
	for _, tc := range cases {
		if got := acceptsGzip(tc.header); got != tc.want {
			t.Fatalf("acceptsGzip(%q) = %v, want %v", tc.header, got, tc.want)
		}
	}
}

// largeText is bigger than the compression threshold, so the tests exercise the
// negotiated path rather than the small-body shortcut.
var largeText = strings.Repeat("body{color:#333}\n", 128)

type fixedHandler struct {
	contentType string
	body        string
	encoding    string
	length      string
}

func (h fixedHandler) ServeHTTP(w http.ResponseWriter, _ *http.Request) {
	header := w.Header()
	header.Set("Content-Type", h.contentType)
	if h.encoding != "" {
		header.Set("Content-Encoding", h.encoding)
	}
	if h.length != "" {
		header.Set("Content-Length", h.length)
	}
	header.Set("X-Kept", "yes")
	w.WriteHeader(http.StatusOK)
	_, _ = io.WriteString(w, h.body)
}

func TestNegotiation(t *testing.T) {
	cases := []struct {
		name         string
		handler      http.Handler
		method       string
		accept       string
		rangeHeader  string
		wantEncoding string
		wantVary     bool
		wantKept     bool
	}{
		{
			name:         "gzip is applied when accepted",
			handler:      fixedHandler{contentType: "text/css", body: largeText},
			method:       http.MethodGet,
			accept:       "gzip, deflate",
			wantEncoding: "gzip",
			wantVary:     true,
			wantKept:     true,
		},
		{
			name:     "identity when no encoding is accepted",
			handler:  fixedHandler{contentType: "text/css", body: largeText},
			method:   http.MethodGet,
			accept:   "",
			wantVary: true,
			wantKept: true,
		},
		{
			name:     "brotli only stays identity",
			handler:  fixedHandler{contentType: "text/css", body: largeText},
			method:   http.MethodGet,
			accept:   "br",
			wantVary: true,
		},
		{
			name:     "q=0 refuses gzip",
			handler:  fixedHandler{contentType: "text/css", body: largeText},
			method:   http.MethodGet,
			accept:   "gzip;q=0",
			wantVary: true,
		},
		{
			name:         "already encoded upstream response is left alone",
			handler:      fixedHandler{contentType: "text/plain", body: largeText, encoding: "br"},
			method:       http.MethodGet,
			accept:       "gzip",
			wantEncoding: "br",
			wantVary:     false,
		},
		{
			name:     "binary content types are not compressed",
			handler:  fixedHandler{contentType: "font/woff2", body: largeText},
			method:   http.MethodGet,
			accept:   "gzip",
			wantVary: false,
		},
		{
			name:     "known small bodies are left uncompressed",
			handler:  fixedHandler{contentType: "image/svg+xml", body: "<svg/>", length: "6"},
			method:   http.MethodGet,
			accept:   "gzip",
			wantVary: true,
		},
		{
			name:        "range requests are not re-encoded",
			handler:     fixedHandler{contentType: "text/css", body: largeText, length: "2048"},
			method:      http.MethodGet,
			accept:      "gzip",
			rangeHeader: "bytes=0-10",
			wantVary:    false,
		},
		{
			name:     "post is not compressed",
			handler:  fixedHandler{contentType: "application/json", body: largeText},
			method:   http.MethodPost,
			accept:   "gzip",
			wantVary: false,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			request := httptest.NewRequest(tc.method, "/resource", nil)
			if tc.accept != "" {
				request.Header.Set("Accept-Encoding", tc.accept)
			}
			if tc.rangeHeader != "" {
				request.Header.Set("Range", tc.rangeHeader)
			}
			recorder := httptest.NewRecorder()
			WithGzip(tc.handler).ServeHTTP(recorder, request)

			if got := recorder.Header().Get("Content-Encoding"); got != tc.wantEncoding {
				t.Fatalf("content-encoding = %q, want %q", got, tc.wantEncoding)
			}
			if got := strings.Contains(recorder.Header().Get("Vary"), "Accept-Encoding"); got != tc.wantVary {
				t.Fatalf("vary = %q, want Accept-Encoding present = %v", recorder.Header().Get("Vary"), tc.wantVary)
			}
			if tc.wantKept && recorder.Header().Get("X-Kept") != "yes" {
				t.Fatalf("handler header lost: %v", recorder.Header())
			}

			body := recorder.Body.Bytes()
			if tc.wantEncoding == "gzip" {
				reader, err := gzip.NewReader(strings.NewReader(string(body)))
				if err != nil {
					t.Fatalf("gzip reader: %v", err)
				}
				decoded, err := io.ReadAll(reader)
				if err != nil {
					t.Fatalf("gunzip: %v", err)
				}
				if string(decoded) != largeText {
					t.Fatalf("decoded body does not match the handler body")
				}
				if recorder.Header().Get("Content-Length") != "" {
					t.Fatalf("compressed response must not advertise the uncompressed length")
				}
				return
			}
			if string(body) != tc.handler.(fixedHandler).body {
				t.Fatalf("body = %q, want %q", body, tc.handler.(fixedHandler).body)
			}
		})
	}
}

// TestNonOKStatusIsNotCompressed pins the status rule: error bodies keep their
// shape so a JSON client can read them without a decoder.
func TestNonOKStatusIsNotCompressed(t *testing.T) {
	handler := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusTooManyRequests)
		_, _ = io.WriteString(w, `{"detail":"Too Many Requests"}`)
	})
	request := httptest.NewRequest(http.MethodGet, "/api/v1/things", nil)
	request.Header.Set("Accept-Encoding", "gzip")
	recorder := httptest.NewRecorder()
	WithGzip(handler).ServeHTTP(recorder, request)

	if got := recorder.Header().Get("Content-Encoding"); got != "" {
		t.Fatalf("content-encoding = %q, want none for a 429", got)
	}
	if rec := recorder.Body.String(); rec != `{"detail":"Too Many Requests"}` {
		t.Fatalf("body = %q", rec)
	}
}

// TestHeadAdvertisesGzipWithoutAFakeLength pins the wire behaviour a client
// sees: HEAD must not report the length of the empty gzip stream, because a GET
// of the same resource is longer than that.
func TestHeadAdvertisesGzipWithoutAFakeLength(t *testing.T) {
	// The handler follows the same contract as the static one: a HEAD request
	// writes headers only. A handler that writes a body on HEAD makes net/http
	// derive Content-Length from the discarded gzip stream, which is a property
	// of that handler, not of the negotiation.
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		if r.Method == http.MethodHead {
			// Like http.ServeContent: headers are written, no body.
			w.WriteHeader(http.StatusOK)
			return
		}
		_, _ = io.WriteString(w, largeText)
	})
	server := httptest.NewServer(WithGzip(handler))
	defer server.Close()

	request, err := http.NewRequest(http.MethodHead, server.URL, nil)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	request.Header.Set("Accept-Encoding", "gzip")
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatalf("do: %v", err)
	}
	defer func() { _ = response.Body.Close() }()

	if got := response.Header.Get("Content-Encoding"); got != "gzip" {
		t.Fatalf("content-encoding = %q, want gzip", got)
	}
	if got := response.Header.Get("Content-Length"); got != "" {
		t.Fatalf("content-length = %q, want no length for a re-encoded body", got)
	}
	if got := response.Header.Get("Vary"); !strings.Contains(got, "Accept-Encoding") {
		t.Fatalf("vary = %q", got)
	}
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	if len(body) != 0 {
		t.Fatalf("HEAD body = %d bytes, want 0", len(body))
	}
}
