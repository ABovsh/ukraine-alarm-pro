"""Shared fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _allow_local_sockets(socket_enabled):
    """Transport tests run real aiohttp servers on localhost."""
