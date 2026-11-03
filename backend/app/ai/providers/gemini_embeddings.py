"""Standard Gemini embedding RPC only. No paid asynchronous Batch API or model fallback."""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from concurrent.futures import Future
from contextlib import suppress
from contextvars import ContextVar
from pathlib import Path
from threading import Condition, Event, RLock, Thread, current_thread
from typing import Literal

import httpx
from google import genai
from google.genai import errors, types
from pydantic import SecretStr

from app.ai.embeddings import EmbeddingTransportError
from app.ai.providers.gemini import GeminiCredentials
from app.core.embedding_settings import EmbeddingSettings
from app.schemas.embeddings import EMBEDDING_MODEL, EmbeddingRequest, EmbeddingTransportResult

EMBEDDING_PATH = f"/v1beta/models/{EMBEDDING_MODEL}:batchEmbedContents"
_RESPONSE_LIMIT: ContextVar[int] = ContextVar("embedding_response_bytes", default=4194304)
_CONNECT_LIMIT: ContextVar[float] = ContextVar("embedding_connect_seconds", default=3.0)


class _EmbeddingStream(httpx.AsyncByteStream):
    def __init__(self, stream: httpx.AsyncByteStream, limit: int) -> None:
        self.stream, self.limit = stream, limit

    async def __aiter__(self) -> AsyncIterator[bytes]:
        count = 0
        try:
            async for chunk in self.stream:
                count += len(chunk)
                if count > self.limit:
                    raise EmbeddingTransportError("response_too_large")
                yield chunk
        finally:
            await self.stream.aclose()

    async def aclose(self) -> None:
        await self.stream.aclose()


class _EmbeddingWire(httpx.AsyncBaseTransport):
    def __init__(self, transport: httpx.AsyncBaseTransport, response_limit: int) -> None:
        self.transport, self.response_limit = transport, response_limit

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if (
            request.method != "POST"
            or request.url.scheme != "https"
            or request.url.host != "generativelanguage.googleapis.com"
            or request.url.username
            or request.url.password
            or request.url.port not in {None, 443}
            or request.url.path != EMBEDDING_PATH
            or request.url.query
        ):
            raise EmbeddingTransportError("invalid_request")
        if len(request.content) > 65536:
            raise EmbeddingTransportError("request_too_large")
        body = json.loads(request.content)
        entries = body.get("requests")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
            raise EmbeddingTransportError("invalid_request")
        if any(entry.get("model") != "models/" + EMBEDDING_MODEL for entry in entries):
            raise EmbeddingTransportError("invalid_request")
        timeouts = dict(request.extensions.get("timeout", {}))
        timeouts["connect"] = min(timeouts.get("connect") or 3.0, _CONNECT_LIMIT.get())
        request.extensions["timeout"] = timeouts
        response = await self.transport.handle_async_request(request)
        if not isinstance(response.stream, httpx.AsyncByteStream):
            raise EmbeddingTransportError("invalid_response")
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            await response.aclose()
            raise EmbeddingTransportError("invalid_response")
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            stream=_EmbeddingStream(
                response.stream, min(self.response_limit, _RESPONSE_LIMIT.get())
            ),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self.transport.aclose()


class GeminiEmbeddingTransport:
    source: Literal["ai"] = "ai"

    def __init__(
        self,
        key: SecretStr,
        *,
        http_transport: httpx.AsyncBaseTransport | None = None,
        max_response_bytes: int = 4194304,
    ) -> None:
        if not key.get_secret_value().strip() or not 4096 <= max_response_bytes <= 4194304:
            raise EmbeddingTransportError("configuration_missing")
        self._lock = Condition(RLock())
        self._closed = False
        self._pending: set[Future[EmbeddingTransportResult]] = set()
        try:
            self._loop = asyncio.new_event_loop()
            self._http = httpx.AsyncClient(
                transport=_EmbeddingWire(
                    http_transport
                    or httpx.AsyncHTTPTransport(
                        retries=0,
                        trust_env=False,
                        limits=httpx.Limits(max_connections=2, max_keepalive_connections=2),
                    ),
                    max_response_bytes,
                ),
                timeout=httpx.Timeout(10, connect=3),
                trust_env=False,
                follow_redirects=False,
                headers={"Accept-Encoding": "identity"},
            )
        except Exception:
            loop = getattr(self, "_loop", None)
            if loop is not None:
                with suppress(Exception):
                    loop.close()
            raise EmbeddingTransportError("configuration_missing") from None
        try:
            started = Event()
            self._loop.call_soon(started.set)
            self._thread = Thread(
                target=self._loop.run_forever, daemon=True, name="trace-embedding-io"
            )
            self._thread.start()
            if not started.wait(5):
                raise RuntimeError("Embedding I/O did not start")
            self._client = genai.Client(
                api_key=key.get_secret_value(),
                vertexai=False,
                http_options=types.HttpOptions(
                    base_url="https://generativelanguage.googleapis.com",
                    api_version="v1beta",
                    httpx_async_client=self._http,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        except Exception:
            with suppress(Exception):
                if self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(self._http.aclose(), self._loop).result(5)
                else:
                    self._loop.run_until_complete(self._http.aclose())
            thread = getattr(self, "_thread", None)
            if thread is not None and thread.is_alive():
                self._loop.call_soon_threadsafe(self._loop.stop)
                thread.join(5)
            with suppress(Exception):
                self._loop.close()
            raise EmbeddingTransportError("configuration_missing") from None

    @classmethod
    def from_environment(cls, settings: EmbeddingSettings) -> "GeminiEmbeddingTransport":
        checked = EmbeddingSettings.model_validate(settings.model_dump(warnings=False))
        if checked.mode != "gemini_free":
            raise EmbeddingTransportError("configuration_missing")
        try:
            key_path = Path(__file__).resolve().parents[3] / ".env.gemini"
            credentials = GeminiCredentials(_env_file=key_path)
            return cls(credentials.key, max_response_bytes=checked.max_response_bytes)
        except Exception:
            raise EmbeddingTransportError("configuration_missing") from None

    def embed(self, request: EmbeddingRequest) -> EmbeddingTransportResult:
        checked = EmbeddingRequest.model_validate(request.model_dump(warnings=False))
        if current_thread() is self._thread:
            raise EmbeddingTransportError("invalid_request")
        deadline = time.monotonic() + checked.response_timeout_seconds
        with self._lock:
            if self._closed:
                raise EmbeddingTransportError("disabled")
            if not self._thread.is_alive() or not self._loop.is_running():
                raise EmbeddingTransportError("transport_error")
            coroutine = self._embed(checked, deadline)
            try:
                future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
            except Exception:
                coroutine.close()
                raise EmbeddingTransportError("transport_error") from None
            self._pending.add(future)
        try:
            result = future.result()
            with self._lock:
                if self._closed:
                    raise EmbeddingTransportError("disabled")
            return result
        finally:
            with self._lock:
                self._pending.remove(future)
                self._lock.notify_all()

    async def _embed(self, request: EmbeddingRequest, deadline: float) -> EmbeddingTransportResult:
        response_limit = _RESPONSE_LIMIT.set(request.max_response_bytes)
        connect_limit = _CONNECT_LIMIT.set(request.connect_timeout_seconds)
        try:
            if time.monotonic() >= deadline:
                raise EmbeddingTransportError("timeout")
            async with asyncio.timeout_at(deadline):
                response = await self._client.aio.models.embed_content(
                    model=request.profile.model_id,
                    contents=list(request.texts),
                    config=types.EmbedContentConfig(
                        task_type=(
                            request.profile.document_task
                            if request.purpose == "document"
                            else request.profile.query_task
                        ),
                        output_dimensionality=request.profile.dimensions,
                        http_options=types.HttpOptions(
                            timeout=max(1, int(request.response_timeout_seconds * 1000)),
                        ),
                    ),
                )
                embeddings = response.embeddings
                if embeddings is None or len(embeddings) != len(request.texts):
                    raise EmbeddingTransportError("invalid_response")
                if any(embedding.values is None for embedding in embeddings):
                    raise EmbeddingTransportError("invalid_response")
                # Installed SDK2.34.0 drops Developer API usageMetadata. Never
                # manufacture zero tokens or a model revision from requested ID.
                result = EmbeddingTransportResult(
                    vectors=tuple(tuple(embedding.values or ()) for embedding in embeddings),
                    input_tokens=None,
                    observed_provider_revision=None,
                )
                await asyncio.sleep(0)
                if time.monotonic() >= deadline:
                    raise EmbeddingTransportError("timeout")
                return result
        except EmbeddingTransportError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise EmbeddingTransportError("timeout") from None
        except errors.APIError as error:
            if error.code in {401, 403}:
                raise EmbeddingTransportError("authentication_error") from None
            if error.code == 429:
                raise EmbeddingTransportError("rate_limited") from None
            if error.code in {400, 404}:
                raise EmbeddingTransportError("invalid_request") from None
            raise EmbeddingTransportError("transport_error") from None
        except Exception:
            raise EmbeddingTransportError("transport_error") from None
        finally:
            _RESPONSE_LIMIT.reset(response_limit)
            _CONNECT_LIMIT.reset(connect_limit)

    async def _shutdown(self) -> None:
        try:
            async with asyncio.timeout(5):
                await self._client.aio.aclose()
                await self._http.aclose()
        finally:
            self._client.close()

    def close(self) -> None:
        if current_thread() is self._thread:
            raise EmbeddingTransportError("invalid_request")
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._lock.wait_for(lambda: not self._pending)
        try:
            if self._loop.is_running():
                asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop).result()
            else:
                self._loop.run_until_complete(self._shutdown())
        except Exception:
            raise EmbeddingTransportError("transport_error") from None
        finally:
            if self._thread.is_alive():
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._thread.join()
            self._loop.close()
