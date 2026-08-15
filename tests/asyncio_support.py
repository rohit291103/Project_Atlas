"""Run an awaitable from a synchronous test, without lying to the type checker.

`asyncio.run` is annotated as taking a `Coroutine`, and several of the things
under test here return a plain `Awaitable` -- an SDK tool handler, a permission
gate. Passing one directly works at runtime and fails strict mypy, which is how
`tests/` accumulated a set of errors that `src/` never had.

Wrapping in a coroutine is the honest fix: no `type: ignore`, no cast, and the
awaited value keeps its real type through the call.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable

__all__ = ["run_await"]


def run_await[T](awaitable: Awaitable[T]) -> T:
    async def wrapped() -> T:
        return await awaitable

    return asyncio.run(wrapped())
