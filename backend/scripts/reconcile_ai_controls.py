"""Explicit authenticated administrator recovery; never an automatic quota reset."""

import argparse
import getpass
import os
import sys
from typing import Literal, cast
from uuid import UUID

from app.auth.jwt import JwtVerifier
from app.core.accounting_settings import AccountingSettings
from app.core.settings import Settings
from app.db.accounting import SqlAIControls
from app.db.accounts import SqlAccountRepository
from app.db.session import Database
from app.services.accounts import AccountService


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile an operator-confirmed stopped AI operation"
    )
    parser.add_argument("kind", choices=("provider", "admission"))
    parser.add_argument("id", type=UUID)
    parser.add_argument("--confirm-stopped", action="store_true")
    args = parser.parse_args()
    if not args.confirm_stopped:
        print("Confirm the operation actually stopped before reconciliation.", file=sys.stderr)
        return 2
    database = None
    try:
        accounting = AccountingSettings(_env_file=None)
        if accounting.mode != "durable" or not os.environ.get("TRACE_DATABASE_URL"):
            raise ValueError("Configure the intended durable database explicitly")
        settings = Settings(_env_file=None)
        database = Database(settings)
        token = getpass.getpass("Trace administrator bearer token (not echoed): ")
        verifier = JwtVerifier(settings)
        try:
            identity = verifier.verify(token)
            account = AccountService(SqlAccountRepository(database)).bootstrap(identity)
            account.require_role("admin")
            SqlAIControls(database).reconcile(
                cast(Literal["provider", "admission"], args.kind), args.id, account.id
            )
        finally:
            verifier.close()
        print("Reconciliation recorded; cumulative allowance was not refunded or reset.")
        return 0
    except Exception:
        print(
            "Reconciliation failed; inspect authorization and operation state privately.",
            file=sys.stderr,
        )
        return 1
    finally:
        if database is not None:
            database.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
