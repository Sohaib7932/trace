"""Operator-only local CLI. Requires filesystem/DB access; never exposed over HTTP."""

import argparse
import getpass
from typing import cast
from uuid import UUID

from app.core.settings import Settings
from app.db.accounts import SqlAccountRepository
from app.db.session import Database
from app.domain.accounts import Role
from app.domain.learning import LearningError
from app.services.accounts import AccountService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", type=UUID, required=True)
    parser.add_argument("--role", choices=("creator", "admin"), required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    database = Database(Settings())
    try:
        changed = AccountService(SqlAccountRepository(database)).grant(
            args.user_id, cast(Role, args.role), getpass.getuser(), args.reason
        )
        print("Role granted; audit recorded." if changed else "Role already granted; no change.")
    except (LearningError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
