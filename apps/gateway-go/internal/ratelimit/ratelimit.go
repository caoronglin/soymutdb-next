// Package ratelimit implements a bounded per-client token bucket.
//
// The bucket map is capped and evicted least-recently-used first, so a scan of
// random source addresses cannot turn the limiter itself into a memory leak.
package ratelimit

import (
	"container/list"
	"math"
	"sync"
	"time"
)

// Limiter grants at most one token per request from a per-key bucket.
type Limiter struct {
	rate    float64 // tokens per second
	burst   float64 // bucket capacity, also the largest immediate burst
	maxKeys int
	now     func() time.Time

	mu      sync.Mutex
	buckets map[string]*bucket
	recent  *list.List // front = most recently used
}

type bucket struct {
	tokens float64
	last   time.Time
	order  *list.Element
}

// New validates the bounds. rate is tokens per second and may be fractional.
func New(rate float64, burst, maxKeys int) (*Limiter, error) {
	switch {
	case !(rate > 0) || math.IsInf(rate, 0):
		return nil, &ConfigError{Field: "rate"}
	case burst < 1:
		return nil, &ConfigError{Field: "burst"}
	case maxKeys < 1:
		return nil, &ConfigError{Field: "clients"}
	}
	return &Limiter{
		rate:    rate,
		burst:   float64(burst),
		maxKeys: maxKeys,
		now:     time.Now,
		buckets: make(map[string]*bucket, maxKeys),
		recent:  list.New(),
	}, nil
}

// ConfigError names the rejected limiter bound so startup can fail closed with
// a message that says which number to fix.
type ConfigError struct {
	Field string
}

func (e *ConfigError) Error() string {
	return "ratelimit: invalid " + e.Field + " (rate must be > 0, burst and clients >= 1)"
}

// Allow consumes one token for key. When the bucket is empty it returns false
// and how long the client has to wait before the next token exists.
func (l *Limiter) Allow(key string) (bool, time.Duration) {
	now := l.now()

	l.mu.Lock()
	defer l.mu.Unlock()

	entry, seen := l.buckets[key]
	if !seen {
		l.evictLocked()
		entry = &bucket{tokens: l.burst}
		entry.order = l.recent.PushFront(key)
		l.buckets[key] = entry
	} else {
		elapsed := now.Sub(entry.last).Seconds()
		if elapsed > 0 {
			entry.tokens = math.Min(l.burst, entry.tokens+elapsed*l.rate)
		}
		l.recent.MoveToFront(entry.order)
	}
	entry.last = now

	if entry.tokens >= 1 {
		entry.tokens--
		return true, 0
	}
	wait := time.Duration(math.Ceil((1-entry.tokens)/l.rate)) * time.Second
	if wait < time.Second {
		wait = time.Second
	}
	return false, wait
}

// evictLocked drops the least recently used keys until the map is below its
// cap. It runs before the new key is inserted, so the map never exceeds it.
func (l *Limiter) evictLocked() {
	for len(l.buckets) >= l.maxKeys {
		oldest := l.recent.Back()
		if oldest == nil {
			return
		}
		l.recent.Remove(oldest)
		delete(l.buckets, oldest.Value.(string))
	}
}

// Tracked reports how many clients currently hold a bucket.
func (l *Limiter) Tracked() int {
	l.mu.Lock()
	defer l.mu.Unlock()
	return len(l.buckets)
}

// Cap is the configured client bound.
func (l *Limiter) Cap() int { return l.maxKeys }
