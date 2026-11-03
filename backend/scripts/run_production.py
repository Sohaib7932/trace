"""Explicit container entry point; no migrations, credentials or live probes at startup."""

import ipaddress
import os
import sys

import uvicorn
from pydantic import ValidationError

from app.core.accounting_settings import AccountingSettings
from app.core.settings import Settings


def main() -> int:
    try:
        settings = Settings(_env_file=None)
        if settings.environment != "production":
            raise ValueError
        accounting = AccountingSettings(_env_file=None)
        if accounting.mode != "durable":
            raise ValueError
        accounting.policy()
        proxy_ips = os.environ.get("TRACE_TRUSTED_PROXY_IPS", "")
        entries = proxy_ips.split(",")
        if not proxy_ips or any(
            not item.strip() or ipaddress.ip_network(item.strip(), strict=False).prefixlen == 0
            for item in entries
        ):
            raise ValueError
    except (ValueError, ValidationError):
        print(
            "Production configuration is invalid; review the production template privately.",
            file=sys.stderr,
        )
        return 2
    # One worker per container. Shared durable controls are required before scaling.
    # Only explicitly configured proxy peers may establish the HTTPS scheme.
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
        workers=1,
        proxy_headers=True,
        forwarded_allow_ips=",".join(item.strip() for item in entries),
        access_log=False,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
