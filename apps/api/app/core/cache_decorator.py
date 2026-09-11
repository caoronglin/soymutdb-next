"""Declarative cache-aside decorator for read-only async service functions."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from ..services.cache import get_or_set

P = ParamSpec("P")
T = TypeVar("T")


def cached(
    name: str,
    ttl: int | None = None,
    *,
    key_params: tuple[str, ...] = (),
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Cache a read-only async function using explicitly selected key parameters.

    Only values named by ``key_params`` contribute to the cache key. Positional
    and keyword calls produce the same key. Misspelled key parameters fail at
    decoration time rather than silently sharing an incomplete cache entry.

    Wrapped functions must return JSON-serialisable data. Do not use this on
    writes: cache invalidation remains explicit at mutation boundaries.
    """
    if not name or not name.strip():
        raise ValueError("cache name must be non-empty")

    def decorator(fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        signature = inspect.signature(fn)
        unknown = set(key_params).difference(signature.parameters)
        if unknown:
            raise ValueError(
                "cache key parameters are not function parameters: "
                + ", ".join(sorted(unknown))
            )

        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            params = {key: bound.arguments[key] for key in key_params}
            return await get_or_set(
                name,
                ttl,
                lambda: fn(*args, **kwargs),
                params=params or None,
            )

        return wrapper

    return decorator


__all__ = ["cached"]
