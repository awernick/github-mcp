"""Tests for the httpx GitHub client (HTTP mocked via respx)."""

import httpx
import pytest
import respx

from gh_client import ApiClientError, GitHubClient

BASE = "https://api.github.com"


@pytest.fixture
def gh():
    return GitHubClient("test-token")


def test_get_returns_parsed_json_and_sends_auth_header(gh):
    with respx.mock(base_url=BASE) as router:
        route = router.get("/user").mock(
            return_value=httpx.Response(200, json={"login": "octocat"})
        )
        assert gh.get("/user") == {"login": "octocat"}
        request = route.calls.last.request
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.headers["Accept"] == "application/vnd.github+json"


def test_404_raises_with_path(gh):
    with respx.mock(base_url=BASE) as router:
        router.get("/repos/awernick/nope").mock(
            return_value=httpx.Response(404, json={})
        )
        with pytest.raises(ApiClientError, match=r"404"):
            gh.get("/repos/awernick/nope")


def test_401_mentions_token(gh):
    with respx.mock(base_url=BASE) as router:
        router.get("/user").mock(return_value=httpx.Response(401, json={}))
        with pytest.raises(ApiClientError, match="PERSONAL_ACCESS_TOKEN"):
            gh.get("/user")


def test_422_includes_response_body(gh):
    with respx.mock(base_url=BASE) as router:
        router.post("/repos/a/b/issues").mock(
            return_value=httpx.Response(422, json={"message": "Validation Failed"})
        )
        with pytest.raises(ApiClientError, match="Validation Failed"):
            gh.post("/repos/a/b/issues", json_body={"title": "x"})


def test_raw_returns_text(gh):
    with respx.mock(base_url=BASE) as router:
        route = router.get("/repos/a/b/contents/f.py").mock(
            return_value=httpx.Response(200, text="print('hi')\n")
        )
        assert gh.get("/repos/a/b/contents/f.py", raw=True) == "print('hi')\n"
        assert route.calls.last.request.headers["Accept"] == "application/vnd.github.raw"
