"""Approved Gemini text transport; no tools, alternate hosts/models or paid fallback."""

import json
from collections.abc import Iterator
from contextvars import ContextVar
from pathlib import Path
from typing import Literal

import httpx
from google import genai
from google.genai import errors, types
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ai.client import AITransportError
from app.ai.json_output import strict_json_object
from app.core.ai_settings import AIClientSettings
from app.schemas.ai_client import ClientErrorCode, TransportCompletion, TransportRequest

MODEL = "gemini-3.5-flash-lite"
_PATH = f"/v1beta/models/{MODEL}:generateContent"
_WIRE_LIMIT = 131072
_KEY_FILE = Path(__file__).resolve().parents[3] / ".env.gemini"
_CONNECT_TIMEOUT: ContextVar[float] = ContextVar("gemini_connect_timeout", default=3.0)


class GeminiCredentials(BaseSettings):
    model_config = SettingsConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    key: SecretStr = Field(validation_alias="GEMINI_API_KEY", repr=False)


class _BoundedStream(httpx.SyncByteStream):
    def __init__(self, stream: httpx.SyncByteStream) -> None:
        self.stream = stream

    def __iter__(self) -> Iterator[bytes]:
        size = 0
        try:
            for chunk in self.stream:
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
            stream=_BoundedStream(response.stream),
            extensions=response.extensions,
        )

    def close(self) -> None:
        self.transport.close()


class GeminiTransport:
    source: Literal["ai"] = "ai"

    def __init__(
        self, key: SecretStr, *, http_transport: httpx.BaseTransport | None = None
    ) -> None:
        if not key.get_secret_value().strip():
            raise AITransportError("configuration_missing")
        self._closed = False
        transport = http_transport or httpx.HTTPTransport(
            trust_env=False,
            retries=0,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
        )
        self._http = httpx.Client(
            transport=_PinnedTransport(transport),
            trust_env=False,
            follow_redirects=False,
            headers={"Accept-Encoding": "identity"},
        )
        try:
            self._client = genai.Client(
                api_key=key.get_secret_value(),
                vertexai=False,
                http_options=types.HttpOptions(
                    base_url="https://generativelanguage.googleapis.com",
                    api_version="v1beta",
                    httpx_client=self._http,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        except Exception:
            self._http.close()
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
        if not self._closed:
            self._closed = True
            try:
                self._client.close()
            finally:
                self._http.close()

    def complete(self, request: TransportRequest) -> TransportCompletion:
        if self._closed:
            raise AITransportError("disabled")
        checked = TransportRequest.model_validate(request.model_dump(warnings=False))
        if checked.requested_model_id != MODEL or checked.capability not in {
            "tutor",
            "generation",
            "support",
        }:
            raise AITransportError("invalid_request")
        connection_budget = _CONNECT_TIMEOUT.set(checked.connect_timeout_seconds)
        try:
            data = strict_json_object(checked.data_json, max_bytes=65536)
            schema = strict_json_object(checked.output_schema_json or "", max_bytes=65536)
            timeout = min(checked.response_timeout_seconds, 20.0)
            if timeout <= 0 or checked.connect_timeout_seconds <= 0:
                raise AITransportError("invalid_request")
            result = self._client.models.generate_content(
                model=MODEL,
                contents=json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                config=types.GenerateContentConfig(
                    system_instruction=checked.instructions,
                    response_mime_type="application/json",
                    response_json_schema=schema,
                    candidate_count=1,
                    max_output_tokens=min(checked.max_output_tokens, 4096),
                    tools=[],
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    http_options=types.HttpOptions(timeout=max(1, int(timeout * 1000))),
                ),
            )
            candidates = result.candidates or []
            if not candidates:
                return TransportCompletion(status="refusal", cost_microusd=0)
            if len(candidates) != 1:
                raise AITransportError("invalid_response")
            candidate = candidates[0]
            if candidate.finish_reason == types.FinishReason.MAX_TOKENS:
                return TransportCompletion(status="truncated", cost_microusd=0)
            if candidate.finish_reason != types.FinishReason.STOP:
                return TransportCompletion(status="refusal", cost_microusd=0)
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
            usage = result.usage_metadata
            output = (
                (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
                if usage
                else None
            )
            return TransportCompletion(
                text=text,
                returned_model_id=result.model_version,
                request_id=result.response_id,
                input_tokens=usage.prompt_token_count if usage else None,
                output_tokens=output,
                # This is free-project accounting, not a query of Google Billing.
                cost_microusd=0,
            )
        except AITransportError:
            raise
        except (httpx.TimeoutException, TimeoutError):
            raise AITransportError("timeout") from None
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
