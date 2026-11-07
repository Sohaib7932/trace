"""Operator defaults and private console behavior; no real credential or HTTP."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from scripts import publish_reviewed_corpus as cli
from scripts.corpus_operator import PACKAGE_SHA256
from scripts.corpus_operator import plan as corpus_plan
from scripts.operator_http import OperatorHTTPError


@pytest.mark.parametrize("arguments", [[], ["--plan"]])
def test_default_plan_is_offline_even_when_token_is_present(monkeypatch, capsys, arguments):
    monkeypatch.setenv("TRACE_OPERATOR_ACCESS_TOKEN", "private.token.canary")
    monkeypatch.setattr(cli.OperatorHTTP, "from_environment", lambda: pytest.fail("HTTP created"))
    monkeypatch.setattr(cli, "plan", lambda: corpus_plan(lambda: datetime(2026, 11, 3, tzinfo=UTC)))
    assert cli.main(arguments) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["http_requests"] == 0
    assert result["source_count"] == 9 and result["passage_count"] == 19
    assert result["package_sha256"] == PACKAGE_SHA256
    assert result["publish_knowledge_calls"] == 2


@pytest.mark.parametrize(
    "arguments",
    [
        ["--import-reviewed"],
        ["--publish-initial", "--operation-id", str(uuid4())],
        ["--plan", "--confirm-production-write"],
        ["--token", "private-token-canary"],
    ],
)
def test_write_or_credential_argument_mistakes_are_safe_no_client(monkeypatch, capsys, arguments):
    monkeypatch.setattr(cli.OperatorHTTP, "from_environment", lambda: pytest.fail("HTTP created"))
    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    assert error.value.code == 2
    output = capsys.readouterr()
    assert "private-token-canary" not in output.err + output.out


@pytest.mark.parametrize(
    "error,reason",
    [
        (OperatorHTTPError("rate_limited"), "rate_limited"),
        (OperatorHTTPError("transport_unavailable", outcome_unknown=True), "transport_unavailable"),
        (ValueError("private-exception-canary"), "operator_unavailable"),
    ],
)
def test_failures_never_dump_exception_or_response(monkeypatch, capsys, error, reason):
    def unavailable():
        raise error

    monkeypatch.setattr(cli.OperatorHTTP, "from_environment", unavailable)
    assert (
        cli.main(
            [
                "--publish-initial",
                "--operation-id",
                str(uuid4()),
                "--confirm-production-write",
            ]
        )
        == 1
    )
    output = capsys.readouterr().out
    assert json.loads(output)["reason"] == reason
    assert "private-exception-canary" not in output
