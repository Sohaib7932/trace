import socket

import pytest
from pytest_socket import SocketConnectBlockedError


def test_external_connection_is_blocked_before_network_io() -> None:
    # TEST-NET-3 numeric address avoids DNS and is rejected by pytest-socket.
    with pytest.warns(UserWarning, match="connect"), pytest.raises(SocketConnectBlockedError):
        socket.create_connection(("203.0.113.1", 443), timeout=0.01)
