"""Safe offline setup state; this CLI cannot inspect a running process's AI mode."""

import json
from collections.abc import Sequence

from app.core.ai_activation import SafeArgumentParser, ai_setup_diagnostic, loopback_port


def main(argv: Sequence[str] | None = None) -> int:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--check-backend", action="store_true")
    parser.add_argument("--port", type=loopback_port, default=8000)
    args = parser.parse_args(argv)
    try:
        report = ai_setup_diagnostic(check_backend=args.check_backend, port=args.port)
        print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
        return 0
    except Exception:
        print('{"status":"setup_check_unavailable"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
