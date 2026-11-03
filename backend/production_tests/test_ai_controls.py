"""Execute every durable accounting/admission contract on actual PostgreSQL."""

import inspect

import pytest

from tests.integration import test_ai_controls as checks


@pytest.mark.parametrize("name", sorted(name for name in vars(checks) if name.startswith("test_")))
def test_controls_on_postgresql(name, request):
    contract = getattr(checks, name)
    parameters = {
        key: request.getfixturevalue(key) for key in inspect.signature(contract).parameters
    }
    contract(**parameters)
