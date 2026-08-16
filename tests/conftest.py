"""Shared fixtures: reset the client singleton between tests."""

import pytest

import server as server


@pytest.fixture(autouse=True)
def _clean_state():
    server._client = None
    yield
    server._client = None
