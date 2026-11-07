"""Explicit container entry point; no migrations, credentials or live probes at startup."""

import ipaddress
import os
import sys
from typing import cast

import uvicorn
from pydantic import ValidationError
from starlette.types import ASGIApp
from uvicorn._types import ASGI3Application
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.accounting_settings import AccountingSettings
from app.core.ingress_settings import IngressSettings
from app.core.render_edge_middleware import RawSocketCaptureMiddleware
from app.core.render_edge_settings import RenderEdgeSettings
from app.core.settings import Settings
from app.main import create_app


def _trusted_proxy_ips() -> str:
    proxy_ips = os.environ.get("TRACE_TRUSTED_PROXY_IPS", "")
    entries = proxy_ips.split(",")
    if not proxy_ips or any(
        not item.strip() or ipaddress.ip_network(item.strip(), strict=False).prefixlen == 0
        for item in entries
    ):
        raise ValueError("Explicit trusted proxy addresses are required")
    return ",".join(item.strip() for item in entries)


def create_render_production_app() -> ASGIApp:
    """Capture actual socket metadata before the unchanged trusted-XFF algorithm."""
    settings = Settings(_env_file=None)
    edge = RenderEdgeSettings(_env_file=None)
    edge.validate_environment(settings.environment)
    if edge.mode != "enabled":
        raise ValueError("The Render production factory requires explicit edge mode")
    app = create_app(settings=settings, render_edge_settings=edge)
    # Uvicorn uses TypedDict event types; Starlette uses mutable ASGI mappings.
    # Both implement the same runtime ASGI3 protocol at this library boundary.
    proxy = ProxyHeadersMiddleware(cast(ASGI3Application, app), trusted_hosts=_trusted_proxy_ips())
    return RawSocketCaptureMiddleware(cast(ASGIApp, proxy))


def main() -> int:
    try:
        settings = Settings(_env_file=None)
        if settings.environment != "production":
            raise ValueError
        accounting = AccountingSettings(_env_file=None)
        if accounting.mode != "durable":
            raise ValueError
        accounting.policy()
        trusted_proxy_ips = _trusted_proxy_ips()
        edge = RenderEdgeSettings(_env_file=None)
        edge.validate_environment(settings.environment)
        ingress = IngressSettings(_env_file=None)
        ingress.validate_deployment(settings.environment, edge.mode)
    except (ValueError, ValidationError):
        print(
            "Production configuration is invalid; review the production template privately.",
            file=sys.stderr,
        )
        return 2
    # One worker per container. Shared durable controls are required before scaling.
    # Client-address trust stays restricted to the explicit proxy list. The
    # opt-in Render profile interprets only scheme over its confirmed perimeter.
    uvicorn.run(
        "scripts.run_production:create_render_production_app"
        if edge.mode == "enabled"
        else "app.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
        workers=1,
        # Enabled mode captures the original socket before applying the SAME
        # stock proxy parser and allowlist in its factory; never apply it twice.
        proxy_headers=edge.mode != "enabled",
        forwarded_allow_ips=trusted_proxy_ips,
        access_log=False,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
