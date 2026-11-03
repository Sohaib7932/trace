"""Explicit unbilled Gemini launcher, portable from the backend working directory."""

import json
from collections.abc import Callable, Sequence

from app.core.ai_activation import (
    SafeArgumentParser,
    activated_gemini_environment,
    ai_setup_diagnostic,
    loopback_port,
)


def _serve(port: int) -> None:
    import uvicorn

    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        access_log=False,
        log_level="warning",
    )


def main(argv: Sequence[str] | None = None, *, server: Callable[[int], None] = _serve) -> int:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--confirm-free-tier-project", action="store_true")
    parser.add_argument(
        "--check", action="store_true", help="Offline preflight; no server or AI call."
    )
    parser.add_argument("--port", type=loopback_port, default=8000)
    args = parser.parse_args(argv)
    try:
        with activated_gemini_environment(confirm_free_tier_project=args.confirm_free_tier_project):
            diagnostic = ai_setup_diagnostic()
            if not diagnostic.backend_settings_valid:
                print('{"status":"backend_configuration_invalid"}')
                return 2
            if args.check:
                print(json.dumps(diagnostic.model_dump(mode="json"), sort_keys=True))
                return 0
            server(args.port)
            return 0
    except KeyboardInterrupt:
        print('{"status":"interrupted"}')
        return 130
    except (Exception, SystemExit):
        print('{"status":"gemini_activation_unavailable"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
