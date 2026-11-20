// Package apiproxy reverse-proxies the Python API through the gateway.
//
// It forwards methods, bodies, headers and status codes unchanged, streams the
// response instead of buffering it, and bounds every proxied request with a
// deadline so a slow upstream becomes a 504 instead of a hung connection.
package apiproxy

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strconv"
	"strings"
	"time"

	"soymutdb.local/gateway/internal/ratelimit"
)

// Upstream health path used by the readiness route. It is the same probe the
// release scripts poll, and it is deliberately not configurable: a deployment
// that points it somewhere else would make readiness mean something else.
const upstreamReadyPath = "/api/v1/health/ready"

var (
	badGatewayBody     = []byte("{\"detail\":\"Bad Gateway\"}\n")
	gatewayTimeoutBody = []byte("{\"detail\":\"Gateway Timeout\"}\n")
	tooManyRequests    = []byte("{\"detail\":\"Too Many Requests\"}\n")
)

// Options configures the proxy.
type Options struct {
	// Upstream is the Python API base URL, without credentials.
	Upstream *url.URL
	// Timeout bounds a single proxied request, including its body.
	Timeout time.Duration
	// Limiter is optional; when set it caps proxied requests per client.
	Limiter *ratelimit.Limiter
	// Logger receives sanitized proxy failures; nil discards them.
	Logger *slog.Logger
}

// Proxy is an http.Handler for the proxied API subtree.
type Proxy struct {
	upstream *url.URL
	timeout  time.Duration
	limiter  *ratelimit.Limiter
	logger   *slog.Logger
	reverse  *httputil.ReverseProxy
}

// New builds the proxy handler.
func New(options Options) (*Proxy, error) {
	if options.Upstream == nil {
		return nil, errors.New("apiproxy: upstream URL is required")
	}
	if options.Timeout <= 0 {
		return nil, errors.New("apiproxy: timeout must be positive")
	}

	proxy := &Proxy{
		upstream: options.Upstream,
		timeout:  options.Timeout,
		limiter:  options.Limiter,
		logger:   options.Logger,
	}

	reverse := &httputil.ReverseProxy{
		// Rewrite rather than Director: the forwarded headers have to replace
		// the client's copies, and Rewrite is the hook that sees both requests.
		Rewrite: func(request *httputil.ProxyRequest) {
			request.SetURL(options.Upstream)
			setForwardedHeaders(request.In, request.Out)
		},
		// A negative interval flushes every write, so a proxied response is
		// streamed instead of accumulated.
		FlushInterval: -1,
		ErrorHandler:  proxy.fail,
	}
	// DisableCompression keeps the client's Accept-Encoding on the wire and
	// stops the transport from silently decompressing the response, which would
	// desynchronize the response headers from the body we forward.
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.DisableCompression = true
	transport.MaxIdleConns = 100
	transport.MaxIdleConnsPerHost = 32
	transport.IdleConnTimeout = 90 * time.Second
	transport.ResponseHeaderTimeout = options.Timeout
	transport.ExpectContinueTimeout = time.Second
	transport.DialContext = (&net.Dialer{Timeout: 5 * time.Second, KeepAlive: 30 * time.Second}).DialContext
	reverse.Transport = transport

	proxy.reverse = reverse
	return proxy, nil
}

// UpstreamReady probes the API readiness endpoint. A nil error means the
// upstream answered 2xx; the returned string is a fixed label, never the
// upstream address, so a readiness body cannot disclose where the API lives.
func (p *Proxy) UpstreamReady(ctx context.Context) (string, bool) {
	ctx, cancel := context.WithTimeout(ctx, probeTimeout)
	defer cancel()

	target := *p.upstream
	target.Path = strings.TrimRight(p.upstream.Path, "/") + upstreamReadyPath
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, target.String(), nil)
	if err != nil {
		return "error", false
	}
	response, err := (&http.Client{Transport: p.reverse.Transport, Timeout: probeTimeout}).Do(request)
	if err != nil {
		if isTimeout(err) {
			return "timeout", false
		}
		return "unreachable", false
	}
	defer func() { _ = response.Body.Close() }()
	// Drain a bounded amount so the connection can be reused.
	_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, 4<<10))
	if response.StatusCode < 200 || response.StatusCode > 299 {
		return "unhealthy", false
	}
	return "ok", true
}

const probeTimeout = 2 * time.Second

func (p *Proxy) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if p.limiter != nil {
		allowed, retryAfter := p.limiter.Allow(clientIP(r))
		if !allowed {
			writeFixed(w, http.StatusTooManyRequests, tooManyRequests, map[string]string{
				"Retry-After": strconv.Itoa(int(retryAfter.Seconds())),
			})
			return
		}
	}

	ctx, cancel := context.WithTimeout(r.Context(), p.timeout)
	defer cancel()
	p.reverse.ServeHTTP(w, r.WithContext(ctx))
}

// fail maps a transport or deadline failure onto a JSON 502/504. The response
// carries no upstream address; the operator log does.
func (p *Proxy) fail(w http.ResponseWriter, r *http.Request, err error) {
	status, body := http.StatusBadGateway, badGatewayBody
	if isTimeout(err) || errors.Is(err, context.DeadlineExceeded) {
		status, body = http.StatusGatewayTimeout, gatewayTimeoutBody
	}
	if p.logger != nil {
		p.logger.Warn("api proxy request failed",
			"path", r.URL.Path,
			"method", r.Method,
			"status", status,
			"error", err.Error(),
		)
	}
	writeFixed(w, status, body, nil)
}

func isTimeout(err error) bool {
	var netErr net.Error
	return errors.As(err, &netErr) && netErr.Timeout()
}

func writeFixed(w http.ResponseWriter, status int, body []byte, headers map[string]string) {
	header := w.Header()
	for key, value := range headers {
		header.Set(key, value)
	}
	header.Set("Content-Type", "application/json")
	header.Set("X-Content-Type-Options", "nosniff")
	header.Set("Content-Length", strconv.Itoa(len(body)))
	w.WriteHeader(status)
	_, _ = w.Write(body)
}

// setForwardedHeaders replaces, never extends, the client-visible forwarding
// headers. The gateway is the front door, so the only peer it can vouch for is
// the one that opened the TCP connection: a client-supplied X-Forwarded-For
// could otherwise claim any address, including one the API trusts for scheme
// and host decisions.
func setForwardedHeaders(in, out *http.Request) {
	out.Header.Del("X-Forwarded-For")
	out.Header.Del("Forwarded")
	out.Header.Del("X-Real-IP")

	ip := clientIP(in)
	if ip != "" {
		out.Header.Set("X-Forwarded-For", ip)
		out.Header.Set("X-Real-IP", ip)
	}
	out.Header.Set("Forwarded", forwardedValue(ip, in.TLS != nil, in.Host))
}

func forwardedValue(ip string, secure bool, host string) string {
	scheme := "http"
	if secure {
		scheme = "https"
	}
	parts := make([]string, 0, 3)
	if ip != "" {
		node := ip
		if strings.Contains(node, ":") {
			// RFC 7239 spells an IPv6 node as a bracketed, quoted literal.
			node = "[" + node + "]"
		}
		parts = append(parts, "for="+quoted(node))
	}
	parts = append(parts, "proto="+scheme)
	if host != "" {
		parts = append(parts, "host="+quoted(host))
	}
	return strings.Join(parts, ";")
}

// quoted renders a value as an RFC 7230 quoted-string only when the raw value
// is not a token. IPv6 addresses and host:port pairs always need it.
func quoted(value string) string {
	if value == "" {
		return `""`
	}
	if !strings.ContainsAny(value, `:;"\\@[]()<>?,= `) {
		return value
	}
	escaped := strings.ReplaceAll(value, `\`, `\\`)
	escaped = strings.ReplaceAll(escaped, `"`, `\"`)
	return `"` + escaped + `"`
}

// clientIP is the TCP peer of the request. It is also the rate-limit key, so
// the two uses of "client" can never disagree.
func clientIP(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}
