"""Shared fixtures."""

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _allow_local_sockets(socket_enabled):
    """Transport tests run real aiohttp servers on localhost."""


@pytest.fixture
def hass(hass, tmp_path):
    """Keep blueprint/storage writes out of the installed test-helper package."""
    hass.config.config_dir = str(tmp_path)
    return hass


def pytest_sessionfinish(session, exitstatus):
    """Write browser JS coverage after all modules using the shared page fixture."""
    output = os.environ.get("UAP_CARD_LCOV_PATH")
    if not output:
        return
    from test_card_browser import _CARD_COVERAGE_PROFILES, _lcov

    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_lcov(_CARD_COVERAGE_PROFILES))
