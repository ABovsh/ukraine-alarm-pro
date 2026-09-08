"""Shared fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _allow_local_sockets(socket_enabled):
    """Transport tests run real aiohttp servers on localhost."""


@pytest.fixture
def hass(hass, tmp_path):
    """Keep blueprint/storage writes out of the installed test-helper package."""
    hass.config.config_dir = str(tmp_path)
    return hass
