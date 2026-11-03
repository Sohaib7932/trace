"""Owned public-JWKS HTTP I/O with a cancelable absolute refresh deadline.

The synchronous port remains compatible with authentication workers. No token
selects a URL, redirects/proxies are disabled, and no keys/errors are logged.
Async I/O cancellation cannot preempt CPU stalls or an OS resolver call; at most
one resolver job is owned and retained until it really finishes.
"""

import asyncio
import json
import math
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from threading import BoundedSemaphore, Condition, Event, Lock, RLock, Thread, current_thread
from typing import Any, ParamSpec, TypeVar

import httpx2

P = ParamSpec("P")
T = TypeVar("T")


class _SingleResolver(ThreadPoolExecutor):
    def __init__(self) -> None:
        super().__init__(max_workers=1, thread_name_prefix="trace-jwks-dns")
        self._permit = BoundedSemaphore(1)
        self._gate = Lock()
        self._idle = Event()
        self._idle.set()

    def submit(self, fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> Future[T]:
        with self._gate:
            if not self._permit.acquire(blocking=False):
                raise RuntimeError("Authentication resolver is busy")
            self._idle.clear()
        try:
            future = super().submit(fn, *args, **kwargs)
        except BaseException:
            self._finished()
            raise
        future.add_done_callback(lambda _: self._finished())
        return future

    def _finished(self) -> None:
        with self._gate:
            self._permit.release()
            self._idle.set()

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        return self._idle.wait(timeout)


class HttpJwksSource:
    def __init__(
        self,
        url: str,
        *,
        http_transport: httpx2.AsyncBaseTransport | None = None,
        timeout_seconds: float = 3.0,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 3
        ):
            raise ValueError("Invalid authentication refresh deadline")
        self.url, self.timeout = url, timeout_seconds
        self._transport = http_transport
        self._state = Condition(RLock())
        self._closed = self._disposed = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: Thread | None = None
        self._client: httpx2.AsyncClient | None = None
        self._resolver: _SingleResolver | None = None
        self._pending: set[Future[dict[str, Any]]] = set()

    def _start(self) -> None:
        if self._loop is not None:
            return
        try:
            loop = asyncio.new_event_loop()
            self._loop = loop
            self._resolver = _SingleResolver()
            loop.set_default_executor(self._resolver)
            self._client = httpx2.AsyncClient(
                timeout=self.timeout,
                follow_redirects=False,
                trust_env=False,
                headers={"Accept-Encoding": "identity"},
                transport=self._transport,
                limits=httpx2.Limits(max_connections=1, max_keepalive_connections=1),
            )
            started = Event()
            loop.call_soon(started.set)
            self._thread = Thread(target=loop.run_forever, daemon=True, name="trace-jwks-io")
            self._thread.start()
            if not started.wait(self.timeout):
                raise ValueError("Authentication worker did not start")
        except Exception:
            self._closed = True
            self._dispose()
            raise ValueError("Authentication refresh is unavailable") from None

    def fetch(self) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout
        with self._state:
            if self._closed or current_thread() is self._thread:
                raise ValueError("Authentication refresh is unavailable")
            try:
                self._start()
                loop = self._loop
                if loop is None or not loop.is_running():
                    raise ValueError("Authentication refresh is unavailable")
                coroutine = self._fetch(deadline)
                try:
                    future = asyncio.run_coroutine_threadsafe(coroutine, loop)
                except Exception:
                    coroutine.close()
                    raise
                self._pending.add(future)
            except Exception:
                raise ValueError("Authentication refresh is unavailable") from None
        try:
            result = future.result()
            if self._closed:
                raise ValueError("Authentication refresh is unavailable")
            return result
        except Exception:
            raise ValueError("Authentication refresh is unavailable") from None
        finally:
            with self._state:
                self._pending.remove(future)
                self._state.notify_all()
                cleanup = self._closed and not self._pending
            if cleanup:
                self._dispose()

    async def _fetch(self, deadline: float) -> dict[str, Any]:
        if time.monotonic() >= deadline or self._client is None:
            raise ValueError("Authentication refresh is unavailable")
        async with asyncio.timeout_at(deadline):
            async with self._client.stream("GET", self.url) as response:
                response.raise_for_status()
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ValueError("Unexpected authentication response encoding")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > 65536:
                        raise ValueError("Authentication response exceeds its bound")
                    body.extend(chunk)
            value: Any = json.loads(body)
            await asyncio.sleep(0)
            if not isinstance(value, dict) or time.monotonic() >= deadline:
                raise ValueError("Invalid authentication response")
            return value

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        with self._state:
            self._closed = True
            if self._pending:
                return
        self._dispose()

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._state:
            while self._pending:
                remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                if remaining == 0:
                    return False
                self._state.wait(remaining)
            resolver = self._resolver
        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
        return resolver is None or resolver.wait_for_idle(remaining)

    async def _close_http(self) -> None:
        if self._client is not None:
            async with asyncio.timeout(3):
                await self._client.aclose()

    def _dispose(self) -> None:
        with self._state:
            if self._disposed or self._loop is None:
                return
            self._disposed = True
            loop, thread = self._loop, self._thread
        # Only called after actual refresh cleanup, never by the I/O thread.
        try:
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(self._close_http(), loop).result()
            else:
                loop.run_until_complete(self._close_http())
        except Exception:
            pass  # Fixed public unavailable result; never print source/key diagnostics.
        finally:
            if thread is not None and thread.is_alive():
                loop.call_soon_threadsafe(loop.stop)
                thread.join()
            with suppress(Exception):
                loop.close()
            # A canceled getaddrinfo await does not stop the underlying OS call.
            # Retain ownership until it really ends rather than orphaning one
            # resolver thread per replacement application lifespan.
            if self._resolver is not None:
                self._resolver.shutdown(wait=True, cancel_futures=True)
