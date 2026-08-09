"""Rate limiter tests (G3): in-memory backend + Redis backend (fakeredis).

Covers:

- :class:`FixedWindowLimiter` semantics (allow/deny, window rollover, key
  isolation, reset/hits)
- :class:`RedisLimiter` against ``fakeredis`` (real pipeline execution:
  ``SET NX EX`` window stamping + ``INCR``), incl. key layout
  ``mcp:rl:<name>:<key>`` and runtime failover to the in-memory fallback
  when Redis raises
- :func:`get_limiter` backend selection (empty URL -> memory, unreachable
  URL -> memory + warning, injected client -> Redis)

The module-level ``GLOBAL_LIMITER`` / ``SUBMIT_LIMITER`` resolve to the
in-memory backend on machines without a reachable Redis, so the existing
``test_tools.py`` suite keeps its exact behaviour.
"""

from __future__ import annotations

import logging

import fakeredis
import pytest
from unittest import mock

from mcp_server import ratelimit
from mcp_server.ratelimit import (
    FixedWindowLimiter,
    GLOBAL_LIMITER,
    RedisLimiter,
    SUBMIT_LIMITER,
    get_limiter,
)

# ---------------------------------------------------------------------------
# In-memory backend
# ---------------------------------------------------------------------------


class TestMemoryBackend:
    def test_allows_until_limit_then_denies(self):
        limiter = FixedWindowLimiter(limit=3, window_seconds=60.0)
        t0 = 1000.0
        for i in range(3):
            assert limiter.check("k", now=t0 + i) == (True, 0)
        allowed, retry = limiter.check("k", now=t0 + 3)
        assert allowed is False
        assert retry >= 1

    def test_window_rolls_over(self):
        limiter = FixedWindowLimiter(limit=2, window_seconds=60.0)
        t0 = 1000.0
        assert limiter.check("k", now=t0) == (True, 0)
        assert limiter.check("k", now=t0 + 1) == (True, 0)
        assert limiter.check("k", now=t0 + 2)[0] is False
        # 60s later the window has reset
        assert limiter.check("k", now=t0 + 61)[0] is True

    def test_keys_are_isolated(self):
        limiter = FixedWindowLimiter(limit=1, window_seconds=60.0)
        assert limiter.check("a", now=1.0) == (True, 0)
        assert limiter.check("b", now=1.0) == (True, 0)
        assert limiter.check("a", now=1.0)[0] is False

    def test_reset_and_hits(self):
        limiter = FixedWindowLimiter(limit=1, window_seconds=60.0)
        assert limiter.hits("k") == 0
        limiter.check("k", now=1.0)
        assert limiter.hits("k") == 1
        limiter.reset("k")
        assert limiter.hits("k") == 0
        limiter.check("k", now=1.0)
        assert len(limiter) == 1
        limiter.reset()
        assert len(limiter) == 0

    def test_anonymous_key_default(self):
        limiter = FixedWindowLimiter(limit=1, window_seconds=60.0)
        assert limiter.check("", now=1.0) == (True, 0)
        assert limiter.check("", now=1.0)[0] is False

    def test_invalid_params_rejected(self):
        with pytest.raises(ValueError):
            FixedWindowLimiter(limit=0, window_seconds=60.0)
        with pytest.raises(ValueError):
            FixedWindowLimiter(limit=1, window_seconds=0.0)


# ---------------------------------------------------------------------------
# Redis backend (fakeredis)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


class TestRedisBackend:
    def test_allows_until_limit_then_denies(self, fake_redis):
        limiter = RedisLimiter(fake_redis, limit=3, window_seconds=60.0, name="global")
        for _ in range(3):
            assert limiter.check("c1") == (True, 0)
        allowed, retry = limiter.check("c1")
        assert allowed is False
        assert retry >= 1

    def test_window_ttl_stamped_on_first_hit(self, fake_redis):
        limiter = RedisLimiter(fake_redis, limit=3, window_seconds=60.0, name="global")
        limiter.check("c1")
        ttl = fake_redis.ttl("mcp:rl:global:c1")
        assert 0 < ttl <= 60
        # window start is NOT re-stamped by later hits
        fake_redis.delete("mcp:rl:global:c1")
        assert limiter.check("c1") == (True, 0)  # fresh window

    def test_window_rolls_over_on_expiry(self, fake_redis):
        limiter = RedisLimiter(fake_redis, limit=1, window_seconds=60.0, name="global")
        assert limiter.check("c1") == (True, 0)
        assert limiter.check("c1")[0] is False
        # expire the window: the next hit opens a new window
        fake_redis.expire("mcp:rl:global:c1", 0)
        assert limiter.check("c1") == (True, 0)

    def test_keys_are_isolated_and_prefixed(self, fake_redis):
        limiter = RedisLimiter(fake_redis, limit=1, window_seconds=60.0, name="global")
        assert limiter.check("a") == (True, 0)
        assert limiter.check("b") == (True, 0)
        assert limiter.check("a")[0] is False
        assert sorted(fake_redis.keys("mcp:rl:global:*")) == [
            "mcp:rl:global:a",
            "mcp:rl:global:b",
        ]

    def test_limiter_names_do_not_collide(self, fake_redis):
        global_lim = RedisLimiter(fake_redis, limit=1, window_seconds=60.0, name="global")
        submit_lim = RedisLimiter(fake_redis, limit=1, window_seconds=3600.0, name="blast_submit")
        assert global_lim.check("c1") == (True, 0)
        assert submit_lim.check("c1") == (True, 0)  # separate budget

    def test_custom_key_prefix(self, fake_redis):
        limiter = RedisLimiter(
            fake_redis, limit=1, window_seconds=60.0, name="global", key_prefix="custom:rl:"
        )
        limiter.check("c1")
        assert fake_redis.exists("custom:rl:global:c1")

    def test_reset_and_hits(self, fake_redis):
        limiter = RedisLimiter(fake_redis, limit=3, window_seconds=60.0, name="global")
        assert limiter.hits("c1") == 0
        limiter.check("c1")
        assert limiter.hits("c1") == 1
        limiter.reset("c1")
        assert limiter.hits("c1") == 0
        limiter.check("c1")
        assert len(limiter) == 1
        limiter.reset()
        assert len(limiter) == 0

    def test_redis_failure_falls_back_to_memory(self, fake_redis, caplog):
        """Redis raising at runtime -> per-process fallback, throttled warning."""
        import redis as redis_pkg

        limiter = RedisLimiter(fake_redis, limit=1, window_seconds=60.0, name="global")
        # Simulate Redis being fully down: every command raises.
        with mock.patch.object(
            fake_redis, "pipeline", side_effect=redis_pkg.ConnectionError("down")
        ), mock.patch.object(
            fake_redis, "get", side_effect=redis_pkg.ConnectionError("down")
        ):
            with caplog.at_level(logging.WARNING, logger="mcp_server.ratelimit"):
                assert limiter.check("c1") == (True, 0)  # fail-open via memory
                assert limiter.check("c1")[0] is False  # memory limit=1 enforced
                assert limiter.hits("c1") == 1  # hits read the fallback too
            assert any("unreachable" in r.message for r in caplog.records)

    def test_non_redis_errors_propagate(self, fake_redis):
        limiter = RedisLimiter(fake_redis, limit=1, window_seconds=60.0, name="global")
        with mock.patch.object(fake_redis, "pipeline", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                limiter.check("c1")

    def test_invalid_params_rejected(self, fake_redis):
        with pytest.raises(ValueError):
            RedisLimiter(fake_redis, limit=0, window_seconds=60.0)
        with pytest.raises(ValueError):
            RedisLimiter(fake_redis, limit=1, window_seconds=0.0)

    def test_anonymous_key_default(self, fake_redis):
        limiter = RedisLimiter(fake_redis, limit=1, window_seconds=60.0, name="global")
        assert limiter.check("") == (True, 0)
        assert limiter.check("")[0] is False
        assert fake_redis.exists("mcp:rl:global:anonymous")


# ---------------------------------------------------------------------------
# Factory: backend selection
# ---------------------------------------------------------------------------


class TestGetLimiter:
    def test_empty_url_forces_memory(self):
        assert isinstance(get_limiter(5, 10.0, name="x", redis_url=""), FixedWindowLimiter)

    def test_unreachable_redis_falls_back_with_warning(self, caplog):
        # 127.0.0.1:1 -> connection refused, fails fast (no 0.5s timeout wait)
        with caplog.at_level(logging.WARNING, logger="mcp_server.ratelimit"):
            limiter = get_limiter(5, 10.0, name="x", redis_url="redis://127.0.0.1:1/0")
        assert isinstance(limiter, FixedWindowLimiter)
        assert any("falling back to in-memory" in r.message for r in caplog.records)

    def test_injected_client_returns_redis_limiter(self, fake_redis):
        limiter = get_limiter(5, 10.0, name="x", redis_client=fake_redis)
        assert isinstance(limiter, RedisLimiter)
        assert limiter.check("k") == (True, 0)

    def test_injected_client_skips_connection_probe(self, fake_redis, caplog):
        """A provided client is trusted — no ping, no warning."""
        with caplog.at_level(logging.WARNING, logger="mcp_server.ratelimit"):
            get_limiter(5, 10.0, name="x", redis_client=fake_redis)
        assert not any("falling back" in r.message for r in caplog.records)

    def test_module_level_limiters_exist(self):
        """server.py imports these; both must expose the limiter contract."""
        for limiter, limit, window in (
            (GLOBAL_LIMITER, 60, 60.0),
            (SUBMIT_LIMITER, 10, 3600.0),
        ):
            assert isinstance(limiter, (FixedWindowLimiter, RedisLimiter))
            assert limiter.limit == limit
            assert limiter.window == window
            # contract: check() -> (bool, int), reset(), hits()
            allowed, retry = limiter.check("contract-probe")
            assert isinstance(allowed, bool)
            assert isinstance(retry, int)
            limiter.reset("contract-probe")

    def test_key_prefix_constant(self):
        assert ratelimit.KEY_PREFIX == "mcp:rl:"
