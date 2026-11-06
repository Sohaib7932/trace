"""Exact pilot corpus operator. Default is offline; production writes need separate approval."""

import json
from collections.abc import Sequence
from uuid import UUID

from app.core.ai_activation import SafeArgumentParser
from scripts.corpus_operator import CorpusOperatorError, execute, plan
from scripts.operator_http import OperatorHTTP, OperatorHTTPError


def main(argv: Sequence[str] | None = None) -> int:
    parser = SafeArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--import-reviewed", action="store_true")
    mode.add_argument("--publish-initial", action="store_true")
    parser.add_argument("--operation-id", type=UUID)
    parser.add_argument("--confirm-production-write", action="store_true")
    args = parser.parse_args(argv)
    apply = args.import_reviewed or args.publish_initial
    if apply and (not args.confirm_production_write or args.operation_id is None):
        parser.error("Explicit write confirmation and a retained operation UUID are required.")
    if not apply and (args.confirm_production_write or args.operation_id is not None):
        parser.error("Write options require an explicit operation mode.")
    try:
        if not apply:
            result = plan()
        else:
            with OperatorHTTP.from_environment() as client:
                result = execute(
                    client,
                    operation_id=args.operation_id,
                    publish=args.publish_initial,
                )
        print(json.dumps(result, sort_keys=True))
        return 0
    except OperatorHTTPError as error:
        print(
            json.dumps(
                {
                    "status": "stopped",
                    "reason": error.code,
                    "write_outcome_unknown": error.outcome_unknown,
                    "automatic_retries": 0,
                },
                sort_keys=True,
            )
        )
        return 1
    except CorpusOperatorError:
        print('{"reason":"corpus_integrity_unavailable","status":"stopped"}')
        return 1
    except (Exception, KeyboardInterrupt):
        print('{"reason":"operator_unavailable","status":"stopped"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
