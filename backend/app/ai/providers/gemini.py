"""Approved Gemini text transport; no tools, alternate hosts/models or paid fallback."""

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import Future
from contextlib import suppress
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from threading import Condition, Event, RLock, Thread, current_thread
from typing import Literal

import httpx
from google import genai
from google.genai import errors, types
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ai.client import AITransportError
from app.ai.json_output import strict_json_object
from app.core.ai_settings import (
    GEMINI_MAX_OUTPUT_TOKENS,
    GEMINI_MAX_RESPONSE_SECONDS,
    GEMINI_MODEL,
    AIClientSettings,
)
from app.schemas.ai_client import ClientErrorCode, TransportCompletion, TransportRequest

MODEL = GEMINI_MODEL
_PATH = f"/v1beta/models/{MODEL}:generateContent"
_WIRE_LIMIT = 131072
_KEY_FILE = Path(__file__).resolve().parents[3] / ".env.gemini"
_CONNECT_TIMEOUT: ContextVar[float] = ContextVar("gemini_connect_timeout", default=3.0)
_DEADLINE: ContextVar[float | None] = ContextVar("gemini_response_deadline", default=None)


def _gemini_json_schema(schema: dict[str, object]) -> dict[str, object]:
    """Express string constants using Gemini's supported singleton enums.

    GenerateContent's responseJsonSchema keyword subset includes enum, not const.
    The SDK's raw JSON-schema path passes it through unchanged. Match its string
    Literal compatibility behavior without changing the original domain schema,
    annotations, field names or any adjacent constraints. Local output validation
    remains authoritative. Non-string constants and contradictions fail closed.
    """
    copied = deepcopy(schema)

    def visit(value: object) -> None:
        if not isinstance(value, dict):
            return
        if "const" in value:
            constant = value["const"]
            if not isinstance(constant, str):
                raise AITransportError("invalid_request")
            existing = value.get("enum")
            if "enum" in value and (not isinstance(existing, list) or constant not in existing):
                raise AITransportError("invalid_request")
            value["enum"] = [constant]
            del value["const"]
        # These dictionaries contain named schema nodes. A property literally
        # named "const" is a field, not a keyword to rewrite in this dictionary.
        for key in ("properties", "$defs", "definitions", "patternProperties", "dependentSchemas"):
            mapping = value.get(key)
            if isinstance(mapping, dict):
                for child in mapping.values():
                    visit(child)
        for key in (
            "items",
            "additionalItems",
            "additionalProperties",
            "contains",
            "propertyNames",
            "unevaluatedItems",
            "unevaluatedProperties",
            "not",
            "if",
            "then",
            "else",
        ):
            child = value.get(key)
            if isinstance(child, list):
                for item in child:
                    visit(item)
            else:
                visit(child)
        for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
            children = value.get(key)
            if isinstance(children, list):
                for child in children:
                    visit(child)

    visit(copied)
    if len(json.dumps(copied, ensure_ascii=False).encode("utf-8")) > 65536:
        raise AITransportError("request_too_large")
    return copied


class GeminiCredentials(BaseSettings):
    model_config = SettingsConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    key: SecretStr = Field(validation_alias="GEMINI_API_KEY", repr=False)


class _BoundedStream(httpx.SyncByteStream):
    def __init__(
        self,
        stream: httpx.SyncByteStream,
        deadline: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.stream, self.deadline, self.clock = stream, deadline, clock

    def __iter__(self) -> Iterator[bytes]:
        size = 0
        try:
            for chunk in self.stream:
                # Defense against progressing bodies; this does NOT interrupt a
                # blocked socket read. HTTPX's per-I/O timeout still applies.
                if self.deadline is not None and self.clock() >= self.deadline:
                    raise AITransportError("timeout")
                size += len(chunk)
                if size > _WIRE_LIMIT:
                    raise AITransportError("response_too_large")
                yield chunk
        finally:
            self.stream.close()

    def close(self) -> None:
        self.stream.close()


class _PinnedTransport(httpx.BaseTransport):
    def __init__(self, transport: httpx.BaseTransport) -> None:
        self.transport = transport

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if (
            request.method != "POST"
            or request.url.scheme != "https"
            or request.url.host != "generativelanguage.googleapis.com"
            or request.url.port not in {None, 443}
            or request.url.path != _PATH
            or request.url.query
        ):
            raise AITransportError("invalid_request")
        timeouts = dict(request.extensions.get("timeout", {}))
        timeouts["connect"] = min(timeouts.get("connect") or 3.0, _CONNECT_TIMEOUT.get())
        request.extensions["timeout"] = timeouts
        response = self.transport.handle_request(request)
        if not isinstance(response.stream, httpx.SyncByteStream):
            response.close()
            raise AITransportError("invalid_response")
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            stream=_BoundedStream(response.stream, _DEADLINE.get()),
            extensions=response.extensions,
        )

    def close(self) -> None:
        self.transport.close()


class _BoundedAsyncStream(httpx.AsyncByteStream):
    def __init__(self, stream: httpx.AsyncByteStream) -> None:
        self.stream = stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        size = 0
        try:
            async for chunk in self.stream:
                size += len(chunk)
                if size > _WIRE_LIMIT:
                    raise AITransportError("response_too_large")
                yield chunk
        finally:
            await self.stream.aclose()

    async def aclose(self) -> None:
        await self.stream.aclose()


class _PinnedAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, transport: httpx.AsyncBaseTransport) -> None:
        self.transport = transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if (
            request.method != "POST"
            or request.url.scheme != "https"
            or request.url.host != "generativelanguage.googleapis.com"
            or request.url.port not in {None, 443}
            or request.url.path != _PATH
            or request.url.query
        ):
            raise AITransportError("invalid_request")
        timeouts = dict(request.extensions.get("timeout", {}))
        timeouts["connect"] = min(timeouts.get("connect") or 3.0, _CONNECT_TIMEOUT.get())
        request.extensions["timeout"] = timeouts
        response = await self.transport.handle_async_request(request)
        if not isinstance(response.stream, httpx.AsyncByteStream):
            raise AITransportError("invalid_response")
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            # A compressed body could inflate beyond the wire-byte budget after
            # this wrapper. Identity is requested; fail closed if it is ignored.
            await response.aclose()
            raise AITransportError("invalid_response")
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            stream=_BoundedAsyncStream(response.stream),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self.transport.aclose()


class GeminiTransport:
    source: Literal["ai"] = "ai"
    network_deadline_enforced = True

    def __init__(
        self, key: SecretStr, *, http_transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        if not key.get_secret_value().strip():
            raise AITransportError("configuration_missing")
        self._closed = False
        self._idle = Condition(RLock())
        self._pending: set[Future[TransportCompletion]] = set()
        try:
            self._loop = asyncio.new_event_loop()
            transport = http_transport or httpx.AsyncHTTPTransport(
                trust_env=False,
                retries=0,
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
            )
            self._http = httpx.AsyncClient(
                transport=_PinnedAsyncTransport(transport),
                trust_env=False,
                follow_redirects=False,
                headers={"Accept-Encoding": "identity"},
            )
        except Exception:
            loop = getattr(self, "_loop", None)
            if loop is not None:
                loop.close()
            raise AITransportError("configuration_missing") from None
        # The sync learner/service interface remains unchanged. Only the owned
        # provider I/O runs on this reusable loop, where cancellation can close
        # HTTPX streams. No request creates another event loop or SDK client.
        started = Event()
        self._loop.call_soon(started.set)
        self._thread = Thread(target=self._loop.run_forever, daemon=True, name="trace-gemini-io")
        try:
            self._thread.start()
            if not started.wait(5):
                raise RuntimeError("Provider event loop did not start")
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
            try:
                with suppress(Exception):
                    if self._loop.is_running():
                        asyncio.run_coroutine_threadsafe(self._http.aclose(), self._loop).result()
                    else:
                        self._loop.run_until_complete(self._http.aclose())
            finally:
                if self._thread.is_alive():
                    self._loop.call_soon_threadsafe(self._loop.stop)
                    self._thread.join()
                self._loop.close()
            raise AITransportError("configuration_missing") from None

    @classmethod
    def from_environment(cls, settings: AIClientSettings) -> "GeminiTransport":
        checked = AIClientSettings.model_validate(settings.model_dump(warnings=False))
        if checked.mode != "gemini_free":
            raise AITransportError("configuration_missing")
        # Only the explicitly approved variable is read; no GOOGLE_API_KEY fallback.
        try:
            credentials = GeminiCredentials(_env_file=_KEY_FILE)
            return cls(credentials.key)
        except Exception:
            raise AITransportError("configuration_missing") from None

    def close(self) -> None:
        if current_thread() is self._thread:
            raise RuntimeError("Provider cleanup requires its owner thread")
        with self._idle:
            if self._closed:
                return
            self._closed = True
            # A deadline expires by cancelling actual async I/O. Retain ownership
            # until its cleanup completes, rather than releasing a canceled Future.
            self._idle.wait_for(lambda: not self._pending)
        try:
            if self._loop.is_running():
                asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop).result()
            else:
                self._loop.run_until_complete(self._shutdown())
        except Exception:
            raise RuntimeError("Provider cleanup failed") from None
        finally:
            if self._thread.is_alive():
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._thread.join()
            self._loop.close()

    async def _shutdown(self) -> None:
        try:
            async with asyncio.timeout(5):
                await self._client.aio.aclose()
                await self._http.aclose()
        finally:
            self._client.close()

    def complete(self, request: TransportRequest) -> TransportCompletion:
        if current_thread() is self._thread:
            raise AITransportError("invalid_request")
        checked = TransportRequest.model_validate(request.model_dump(warnings=False))
        if checked.requested_model_id != MODEL or checked.capability not in {
            "tutor",
            "generation",
            "support",
        }:
            raise AITransportError("invalid_request")
        if (
            not 0 < checked.response_timeout_seconds <= GEMINI_MAX_RESPONSE_SECONDS
            or not 0 < checked.connect_timeout_seconds <= 10
            or not 0 < checked.max_output_tokens <= GEMINI_MAX_OUTPUT_TOKENS
        ):
            raise AITransportError("invalid_request")
        deadline = time.monotonic() + checked.response_timeout_seconds
        with self._idle:
            if self._closed:
                raise AITransportError("disabled")
            if not self._thread.is_alive() or not self._loop.is_running():
                raise AITransportError("transport_error")
            coroutine = self._complete_with_deadline(checked, deadline)
            try:
                future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
            except Exception:
                coroutine.close()
                raise AITransportError("transport_error") from None
            self._pending.add(future)
        try:
            # The coroutine's deadline controls I/O; wait for real finalization,
            # including stream cleanup, before the shared client releases a lease.
            result = future.result()
            with self._idle:
                if self._closed:
                    raise AITransportError("disabled", result)
            return result
        finally:
            with self._idle:
                self._pending.remove(future)
                self._idle.notify_all()

    async def _complete_with_deadline(
        self, checked: TransportRequest, deadline: float
    ) -> TransportCompletion:
        result: TransportCompletion | None = None
        try:
            if time.monotonic() >= deadline:
                raise AITransportError("timeout")
            # Covers queueing, connect/write/read waits and a progressing body.
            # It cannot preempt CPU-bound code or a cancellation-resistant custom
            # transport. Bounded wire bytes and late-output checks remain required.
            async with asyncio.timeout_at(deadline):
                result = await self._complete(checked)
                await asyncio.sleep(0)
                if time.monotonic() >= deadline:
                    raise AITransportError("timeout", result)
                return result
        except TimeoutError:
            raise AITransportError("timeout", result) from None

    async def _complete(self, checked: TransportRequest) -> TransportCompletion:
        connection_budget = _CONNECT_TIMEOUT.set(checked.connect_timeout_seconds)
        response_deadline = _DEADLINE.set(time.monotonic() + checked.response_timeout_seconds)
        metadata: TransportCompletion | None = None
        try:
            data = strict_json_object(checked.data_json, max_bytes=65536)
            schema = _gemini_json_schema(
                strict_json_object(checked.output_schema_json or "", max_bytes=65536)
            )
            timeout = checked.response_timeout_seconds
            result = await self._client.aio.models.generate_content(
                model=MODEL,
                contents=json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                config=types.GenerateContentConfig(
                    system_instruction=checked.instructions,
                    response_mime_type="application/json",
                    response_json_schema=schema,
                    candidate_count=1,
                    max_output_tokens=checked.max_output_tokens,
                    tools=[],
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    http_options=types.HttpOptions(timeout=max(1, int(timeout * 1000))),
                ),
            )
            usage = result.usage_metadata
            metadata = TransportCompletion(
                status="refusal",
                returned_model_id=result.model_version,
                request_id=result.response_id,
                input_tokens=usage.prompt_token_count if usage else None,
                # Missing token fields remain unknown; they are not invented zeroes.
                output_tokens=(
                    usage.candidates_token_count + (usage.thoughts_token_count or 0)
                    if usage and usage.candidates_token_count is not None
                    else None
                ),
                # Operator-attested free-project accounting, not a Billing query.
                cost_microusd=0,
            )
            candidates = result.candidates or []
            if not candidates:
                return metadata
            if len(candidates) != 1:
                raise AITransportError("invalid_response")
            candidate = candidates[0]
            if candidate.finish_reason == types.FinishReason.MAX_TOKENS:
                return metadata.model_copy(update={"status": "truncated"})
            if candidate.finish_reason != types.FinishReason.STOP:
                return metadata
            parts = candidate.content.parts if candidate.content else None
            if not parts or any(
                part.function_call
                or part.executable_code
                or part.code_execution_result
                or part.inline_data
                or part.file_data
                for part in parts
            ):
                raise AITransportError("invalid_response")
            text = "".join(part.text or "" for part in parts if not part.thought)
            if len(text.encode("utf-8")) > checked.max_response_bytes:
                raise AITransportError("response_too_large")
            return metadata.model_copy(update={"status": "success", "text": text})
        except AITransportError as exc:
            raise AITransportError(exc.code, metadata) from None
        except (httpx.TimeoutException, TimeoutError):
            raise AITransportError("timeout") from None
        except (httpx.NetworkError, httpx.RemoteProtocolError, httpx.ProxyError):
            raise AITransportError("transient_error") from None
        except errors.APIError as exc:
            code: ClientErrorCode
            if exc.code in {401, 403}:
                code = "authentication_error"
            elif exc.code == 429:
                code = "rate_limited"
            elif exc.code in {408, 504}:
                code = "timeout"
            elif exc.code in {500, 502, 503}:
                code = "transient_error"
            else:
                code = "invalid_request"
            raise AITransportError(code) from None
        except Exception:
            raise AITransportError("invalid_response") from None
        finally:
            _CONNECT_TIMEOUT.reset(connection_budget)
            _DEADLINE.reset(response_deadline)
