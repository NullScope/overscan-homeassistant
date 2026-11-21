"""Fixtures for the Overscan tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest

from .mock_tv import MockTv


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/overscan."""


@pytest.fixture
async def mock_tv(socket_enabled: None) -> AsyncGenerator[MockTv]:
    """A mock TV on a free port of 127.0.0.1."""
    tv = MockTv()
    await tv.start()
    yield tv
    await tv.close()


@pytest.fixture
async def mock_tv_default_port(socket_enabled: None) -> AsyncGenerator[MockTv]:
    """A mock TV on 127.0.0.1:8765, the port the config flow always uses."""
    tv = MockTv()
    await tv.start(8765)
    yield tv
    await tv.close()
