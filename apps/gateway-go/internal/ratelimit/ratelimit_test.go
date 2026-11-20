package ratelimit

import (
	"sync"
	"testing"
	"time"
)

func newFixedLimiter(t *testing.T, rate float64, burst, maxKeys int) (*Limiter, *time.Time) {
	t.Helper()
	limiter, err := New(rate, burst, maxKeys)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	now := time.Unix(1700000000, 0)
	limiter.now = func() time.Time { return now }
	return limiter, &now
}

func TestExhaustionThenRecovery(t *testing.T) {
	limiter, now := newFixedLimiter(t, 1, 2, 8)

	if allowed, _ := limiter.Allow("10.0.0.1"); !allowed {
		t.Fatal("first request rejected")
	}
	if allowed, _ := limiter.Allow("10.0.0.1"); !allowed {
		t.Fatal("second request rejected")
	}

	allowed, retryAfter := limiter.Allow("10.0.0.1")
	if allowed {
		t.Fatal("third request allowed with an empty bucket")
	}
	if retryAfter != time.Second {
		t.Fatalf("retry-after = %v, want 1s", retryAfter)
	}

	// Half a token is not enough.
	*now = now.Add(500 * time.Millisecond)
	allowed, retryAfter = limiter.Allow("10.0.0.1")
	if allowed {
		t.Fatal("request allowed before a full token refilled")
	}
	if retryAfter != time.Second {
		t.Fatalf("retry-after = %v, want 1s", retryAfter)
	}

	// A full second later one token exists again.
	*now = now.Add(500 * time.Millisecond)
	if allowed, _ := limiter.Allow("10.0.0.1"); !allowed {
		t.Fatal("request rejected after a token refilled")
	}
	if allowed, _ := limiter.Allow("10.0.0.1"); allowed {
		t.Fatal("bucket refilled beyond the refill rate")
	}
}

func TestBucketsArePerClient(t *testing.T) {
	limiter, _ := newFixedLimiter(t, 1, 1, 8)

	if allowed, _ := limiter.Allow("10.0.0.1"); !allowed {
		t.Fatal("first client rejected")
	}
	if allowed, _ := limiter.Allow("10.0.0.1"); allowed {
		t.Fatal("first client allowed twice")
	}
	if allowed, _ := limiter.Allow("10.0.0.2"); !allowed {
		t.Fatal("second client inherited the first client's empty bucket")
	}
}

func TestBurstCapsTheRefill(t *testing.T) {
	limiter, now := newFixedLimiter(t, 10, 3, 8)
	*now = now.Add(time.Hour)

	for attempt := 0; attempt < 3; attempt++ {
		if allowed, _ := limiter.Allow("10.0.0.1"); !allowed {
			t.Fatalf("attempt %d rejected inside the burst", attempt)
		}
	}
	if allowed, _ := limiter.Allow("10.0.0.1"); allowed {
		t.Fatal("bucket refilled past its capacity")
	}
}

func TestEvictionBoundsTheTrackedClients(t *testing.T) {
	limiter, _ := newFixedLimiter(t, 1, 1, 2)

	if _, err := New(1, 1, 1); err != nil {
		t.Fatalf("New: %v", err)
	}

	limiter.Allow("a") // used first, evicted first
	limiter.Allow("b")
	limiter.Allow("c")

	if got := limiter.Tracked(); got != 2 {
		t.Fatalf("tracked = %d, want the 2-client cap", got)
	}
	// The evicted client starts from a fresh bucket instead of being refused
	// for the rest of its life.
	if allowed, _ := limiter.Allow("a"); !allowed {
		t.Fatal("evicted client was remembered")
	}
	if got := limiter.Tracked(); got != 2 {
		t.Fatalf("tracked = %d after re-inserting the evicted client", got)
	}
}

func TestNewRejectsInvalidBounds(t *testing.T) {
	cases := []struct {
		name    string
		rate    float64
		burst   int
		clients int
	}{
		{name: "zero rate", rate: 0, burst: 1, clients: 1},
		{name: "negative rate", rate: -1, burst: 1, clients: 1},
		{name: "zero burst", rate: 1, burst: 0, clients: 1},
		{name: "zero clients", rate: 1, burst: 1, clients: 0},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := New(tc.rate, tc.burst, tc.clients); err == nil {
				t.Fatalf("New(%v, %d, %d) accepted invalid bounds", tc.rate, tc.burst, tc.clients)
			}
		})
	}
}

// TestConcurrentAllowIsRaceFree exists for `go test -race`: the limiter is
// shared by every request goroutine.
func TestConcurrentAllowIsRaceFree(t *testing.T) {
	limiter, err := New(1000, 1000, 16)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	var wg sync.WaitGroup
	for worker := 0; worker < 8; worker++ {
		wg.Add(1)
		go func(worker int) {
			defer wg.Done()
			for i := 0; i < 200; i++ {
				limiter.Allow(string(rune('a' + (worker+i)%16)))
			}
		}(worker)
	}
	wg.Wait()
	if got := limiter.Tracked(); got > limiter.Cap() {
		t.Fatalf("tracked = %d exceeds cap %d", got, limiter.Cap())
	}
}
