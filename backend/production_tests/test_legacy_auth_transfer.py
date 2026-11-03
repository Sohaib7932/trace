"""Legacy Tasks/retrieval/auth ownership contracts on PostgreSQL."""

from tests.integration import test_accounts as accounts
from tests.integration import test_transfer_retrieval as transfer


def test_nested_tasks_and_one_seven_day_schedule(
    learner, database, investigated, clock, monkeypatch
):
    transfer.test_real_nested_verification_isolated_fresh_read_and_atomic_schedule(
        learner, database, investigated, clock, monkeypatch
    )


def test_signed_in_history_and_cross_account_isolation(learner, auth, database):
    accounts.test_new_authenticated_learner_without_cookie_can_learn_and_resume(
        learner, auth, database
    )


def test_guest_claim_has_one_owner_across_concurrent_accounts(learner, auth, database):
    accounts.test_concurrent_claims_have_one_owner(learner, auth, database, False)


def test_guest_claim_retry_keeps_one_owner(learner, auth, database):
    accounts.test_concurrent_claims_have_one_owner(learner, auth, database, True)
