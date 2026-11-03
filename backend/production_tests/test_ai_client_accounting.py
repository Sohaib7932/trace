"""Reuse shared-client durability and failure contracts against PostgreSQL."""

import inspect

import pytest

from tests.integration import test_ai_client_accounting as checks


@pytest.mark.parametrize("name", sorted(name for name in vars(checks) if name.startswith("test_")))
def test_client_controls_on_postgresql(name, request):
    contract = getattr(checks, name)
    parameters = {
        key: request.getfixturevalue(key) for key in inspect.signature(contract).parameters
    }
    contract(**parameters)
