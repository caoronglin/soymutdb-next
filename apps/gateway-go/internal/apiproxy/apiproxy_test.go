package apiproxy

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"

	"soymutdb.local/gateway/internal/ratelimit"
)

func mustProxy(t *testing.T, upstream string, timeout time.Duration, limiter *ratelimit.Limiter) *Proxy {
	t.Helper()
	parsed, err := url.Parse(upstream)
	if err != nil {
		t.Fatalf("parse upstream: %v", err)
	}
	proxy, err := New(Options{Upstream: parsed, Timeout: timeout, Limiter: limiter})
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	return proxy
}

func TestForwardsMethodBodyHeadersAndStatus(t *testing.T) {
	type observed struct {
		method string
		path   string
		query  string
		body   string
		header http.Header
	}
	seen := make(chan observed, 1)
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		seen <- observed{method: r.Method, path: r.URL.Path, query: r.URL.RawQuery, body: string(body), header: r.Header.Clone()}
		w.Header().Set("X-Upstream", "yes")
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		_, _ = io.WriteString(w, `{"created":true}`)
	}))
	defer upstream.Close()

	proxy := mustProxy(t, upstream.URL, 2*time.Second, nil)
	request := httptest.NewRequest(http.MethodPost, "/api/v1/things?dry=1", strings.NewReader(`{"name":"x"}`))
	// A client-supplied chain must not survive: the gateway can only vouch for
	// the peer that opened the connection.
	request.Header.Set("X-Forwarded-For", "203.0.113.9")
	request.Header.Set("Forwarded", "for=203.0.113.9")
	request.Header.Set("X-Real-IP", "203.0.113.9")
	request.Header.Set("X-Request-Id", "abc")
	recorder := httptest.NewRecorder()

	proxy.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusCreated {
		t.Fatalf("status = %d, want 201", recorder.Code)
	}
	if got := recorder.Header().Get("X-Upstream"); got != "yes" {
		t.Fatalf("upstream response header lost: %v", recorder.Header())
	}
	if got := recorder.Body.String(); got != `{"created":true}` {
		t.Fatalf("body = %q", got)
	}

	got := <-seen
	if got.method != http.MethodPost {
		t.Fatalf("method = %q", got.method)
	}
	if got.path != "/api/v1/things" || got.query != "dry=1" {
		t.Fatalf("path = %q query = %q", got.path, got.query)
	}
	if got.body != `{"name":"x"}` {
		t.Fatalf("body = %q", got.body)
	}
	if got.header.Get("X-Request-Id") != "abc" {
		t.Fatalf("request header not preserved: %v", got.header)
	}
	// httptest.NewRequest sets RemoteAddr to 192.0.2.1:1234, so the peer is the
	// only address the proxy may vouch for.
	if forwarded := got.header.Get("X-Forwarded-For"); forwarded != "192.0.2.1" {
		t.Fatalf("x-forwarded-for = %q, want the peer address only", forwarded)
	}
	if realIP := got.header.Get("X-Real-IP"); realIP != "192.0.2.1" {
		t.Fatalf("x-real-ip = %q", realIP)
	}
	forwarded := got.header.Get("Forwarded")
	if !strings.Contains(forwarded, "for=192.0.2.1") || strings.Contains(forwarded, "203.0.113.9") {
		t.Fatalf("forwarded = %q, want the peer address only", forwarded)
	}
	if !strings.Contains(forwarded, "proto=http") {
		t.Fatalf("forwarded = %q, want proto=http", forwarded)
	}
}

func TestUpstreamContentEncodingIsNotReplaced(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/plain")
		w.Header().Set("Content-Encoding", "br")
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, "already encoded")
	}))
	defer upstream.Close()

	proxy := mustProxy(t, upstream.URL, 2*time.Second, nil)
	recorder := httptest.NewRecorder()
	proxy.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/v1/raw", nil))

	if got := recorder.Header().Get("Content-Encoding"); got != "br" {
		t.Fatalf("content-encoding = %q, want the upstream value", got)
	}
}

func TestProxyErrorMapping(t *testing.T) {
	t.Run("unreachable upstream is a 502", func(t *testing.T) {
		dead := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
		upstream := dead.URL
		dead.Close()

		proxy := mustProxy(t, upstream, 2*time.Second, nil)
		recorder := httptest.NewRecorder()
		proxy.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/v1/things", nil))

		if recorder.Code != http.StatusBadGateway {
			t.Fatalf("status = %d, want 502", recorder.Code)
		}
		assertDetail(t, recorder.Body.Bytes(), "Bad Gateway")
	})

	t.Run("slow upstream is a 504", func(t *testing.T) {
		release := make(chan struct{})
		upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			select {
			case <-release:
			case <-r.Context().Done():
			}
			w.WriteHeader(http.StatusOK)
		}))
		defer upstream.Close()
		defer close(release)

		proxy := mustProxy(t, upstream.URL, 50*time.Millisecond, nil)
		recorder := httptest.NewRecorder()
		proxy.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/v1/slow", nil))

		if recorder.Code != http.StatusGatewayTimeout {
			t.Fatalf("status = %d, want 504", recorder.Code)
		}
		assertDetail(t, recorder.Body.Bytes(), "Gateway Timeout")
	})
}

func assertDetail(t *testing.T, body []byte, want string) {
	t.Helper()
	var decoded map[string]string
	if err := json.Unmarshal(body, &decoded); err != nil {
		t.Fatalf("error body is not JSON: %v (%q)", err, body)
	}
	if decoded["detail"] != want {
		t.Fatalf("detail = %q, want %q", decoded["detail"], want)
	}
}

func TestRateLimitRejectsAndRecovers(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(w, "ok")
	}))
	defer upstream.Close()

	// 5 tokens/s keeps the pre-refill window wide enough that a scheduler hiccup
	// cannot turn the denial assertion into a false failure.
	limiter, err := ratelimit.New(5, 2, 16)
	if err != nil {
		t.Fatalf("limiter: %v", err)
	}
	proxy := mustProxy(t, upstream.URL, 2*time.Second, limiter)

	for attempt := 0; attempt < 2; attempt++ {
		recorder := httptest.NewRecorder()
		proxy.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/v1/things", nil))
		if recorder.Code != http.StatusOK {
			t.Fatalf("attempt %d status = %d", attempt, recorder.Code)
		}
	}

	recorder := httptest.NewRecorder()
	proxy.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/v1/things", nil))
	if recorder.Code != http.StatusTooManyRequests {
		t.Fatalf("status = %d, want 429", recorder.Code)
	}
	if retryAfter := recorder.Header().Get("Retry-After"); retryAfter == "" {
		t.Fatal("429 without Retry-After")
	}
	assertDetail(t, recorder.Body.Bytes(), "Too Many Requests")

	time.Sleep(250 * time.Millisecond)
	recorder = httptest.NewRecorder()
	proxy.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/v1/things", nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("status after refill = %d, want 200", recorder.Code)
	}
}

func TestUpstreamReady(t *testing.T) {
	t.Run("healthy", func(t *testing.T) {
		upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path != upstreamReadyPath {
				w.WriteHeader(http.StatusNotFound)
				return
			}
			w.WriteHeader(http.StatusOK)
		}))
		defer upstream.Close()

		proxy := mustProxy(t, upstream.URL, 2*time.Second, nil)
		state, ok := proxy.UpstreamReady(context.Background())
		if !ok || state != "ok" {
			t.Fatalf("state = %q ok = %v", state, ok)
		}
	})

	t.Run("unhealthy status", func(t *testing.T) {
		upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(http.StatusServiceUnavailable)
		}))
		defer upstream.Close()

		proxy := mustProxy(t, upstream.URL, 2*time.Second, nil)
		state, ok := proxy.UpstreamReady(context.Background())
		if ok || state != "unhealthy" {
			t.Fatalf("state = %q ok = %v", state, ok)
		}
	})

	t.Run("unreachable", func(t *testing.T) {
		dead := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
		upstream := dead.URL
		dead.Close()

		proxy := mustProxy(t, upstream, 2*time.Second, nil)
		state, ok := proxy.UpstreamReady(context.Background())
		if ok || state != "unreachable" {
			t.Fatalf("state = %q ok = %v", state, ok)
		}
	})
}

func TestForwardedValue(t *testing.T) {
	cases := []struct {
		name   string
		ip     string
		secure bool
		host   string
		want   string
	}{
		{name: "ipv4", ip: "192.0.2.7", host: "admin.example:8443", want: `for=192.0.2.7;proto=http;host="admin.example:8443"`},
		{name: "ipv6", ip: "2001:db8::1", secure: true, host: "admin.example", want: `for="[2001:db8::1]";proto=https;host=admin.example`},
		{name: "no peer", host: "admin.example", want: `proto=http;host=admin.example`},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := forwardedValue(tc.ip, tc.secure, tc.host); got != tc.want {
				t.Fatalf("forwardedValue = %q, want %q", got, tc.want)
			}
		})
	}
}
