"""End-to-end tests for the MCP tools (HTTP mocked via respx)."""

import json

import httpx
import pytest
import respx

import server as server

BASE = "https://api.github.com"
ISSUE = {
    "number": 7,
    "title": "Bug: login redirect",
    "state": "open",
    "user": {"login": "octocat"},
    "labels": [{"name": "bug"}],
    "assignees": [{"login": "octocat"}],
    "comments": 2,
    "created_at": "2026-08-01T00:00:00Z",
    "updated_at": "2026-08-02T00:00:00Z",
    "html_url": "https://github.com/a/b/issues/7",
    "body": "Steps to reproduce",
}
PR = {
    "number": 9,
    "title": "feat: add cache",
    "state": "open",
    "draft": False,
    "user": {"login": "octocat"},
    "head": {"ref": "feat/cache", "sha": "abc123"},
    "base": {"ref": "main"},
    "created_at": "2026-08-01T00:00:00Z",
    "updated_at": "2026-08-02T00:00:00Z",
    "html_url": "https://github.com/a/b/pull/9",
    "body": "Adds a cache",
    "mergeable": True,
    "additions": 40,
    "deletions": 3,
    "changed_files": 2,
}


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", "test-token")


@pytest.fixture
def rx():
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        yield mock


def test_no_token_is_error_json(monkeypatch):
    monkeypatch.delenv("GITHUB_PERSONAL_ACCESS_TOKEN", raising=False)
    result = json.loads(server.get_me())
    assert "error" in result


def test_get_me(token, rx):
    rx.get("/user").mock(
        return_value=httpx.Response(200, json={"login": "awernick", "name": "A", "html_url": "u"})
    )
    assert json.loads(server.get_me()) == {"login": "awernick", "name": "A", "html_url": "u"}


def test_list_issues_filters_pull_requests(token, rx):
    issue_with_pr = {**ISSUE, "number": 8, "pull_request": {"url": "https://x"}}
    route = rx.get("/repos/a/b/issues").mock(
        return_value=httpx.Response(200, json=[ISSUE, issue_with_pr])
    )
    result = json.loads(server.list_issues("a/b"))
    assert [i["number"] for i in result] == [7]
    assert result[0]["labels"] == ["bug"]
    assert route.calls.last.request.url.params["state"] == "open"


def test_search_issues_adds_repo_qualifier(token, rx):
    route = rx.get("/search/issues").mock(
        return_value=httpx.Response(200, json={"total_count": 1, "items": [ISSUE]})
    )
    result = json.loads(server.search_issues("is:open login", repo="a/b"))
    assert route.calls.last.request.url.params["q"] == "repo:a/b is:open login"
    assert result["total_count"] == 1
    assert result["items"][0]["is_pull_request"] is False


def test_get_issue_with_comments(token, rx):
    rx.get("/repos/a/b/issues/7").mock(return_value=httpx.Response(200, json=ISSUE))
    rx.get("/repos/a/b/issues/7/comments").mock(
        return_value=httpx.Response(
            200, json=[{"user": {"login": "u"}, "created_at": "t", "body": "confirmed"}]
        )
    )
    result = json.loads(server.get_issue("a/b", 7))
    assert result["body"] == "Steps to reproduce"
    assert result["comment_list"][0]["body"] == "confirmed"


def test_create_issue_posts_trimmed_payload(token, rx):
    route = rx.post("/repos/a/b/issues").mock(return_value=httpx.Response(201, json=ISSUE))
    result = json.loads(
        server.create_issue("a/b", "Bug: login redirect", labels="bug, high-priority")
    )
    assert result["number"] == 7
    body = json.loads(route.calls.last.request.content)
    assert body["title"] == "Bug: login redirect"
    assert body["labels"] == ["bug", "high-priority"]


def test_update_issue_rejects_invalid_state(token):
    result = json.loads(server.update_issue("a/b", 7, state="maybe"))
    assert "error" in result


def test_update_issue_requires_a_change(token):
    result = json.loads(server.update_issue("a/b", 7))
    assert "nothing to update" in result["error"]


def test_add_issue_comment(token, rx):
    rx.post("/repos/a/b/issues/7/comments").mock(
        return_value=httpx.Response(201, json={"id": 101, "html_url": "https://x#c101"})
    )
    assert json.loads(server.add_issue_comment("a/b", 7, "hi"))["id"] == 101


def test_list_pull_requests(token, rx):
    rx.get("/repos/a/b/pulls").mock(return_value=httpx.Response(200, json=[PR]))
    result = json.loads(server.list_pull_requests("a/b"))
    assert result[0]["head"] == "feat/cache"
    assert result[0]["base"] == "main"


def test_get_pull_request_aggregates_files_and_checks(token, rx):
    rx.get("/repos/a/b/pulls/9").mock(return_value=httpx.Response(200, json=PR))
    rx.get("/repos/a/b/pulls/9/files").mock(
        return_value=httpx.Response(
            200,
            json=[{"filename": "src/cache.py", "status": "added", "additions": 40, "deletions": 0}],
        )
    )
    rx.get("/repos/a/b/commits/abc123/check-runs").mock(
        return_value=httpx.Response(
            200,
            json={
                "total_count": 1,
                "check_runs": [
                    {"name": "pytest", "status": "completed", "conclusion": "success"}
                ],
            },
        )
    )
    result = json.loads(server.get_pull_request("a/b", 9))
    assert result["files"] == [
        {"filename": "src/cache.py", "status": "added", "additions": 40, "deletions": 0}
    ]
    assert result["files_truncated"] is False
    assert result["checks"][0]["conclusion"] == "success"


def test_create_pull_request_resolves_default_branch(token, rx):
    rx.get("/repos/a/b").mock(
        return_value=httpx.Response(200, json={"default_branch": "main"})
    )
    route = rx.post("/repos/a/b/pulls").mock(return_value=httpx.Response(201, json=PR))
    result = json.loads(server.create_pull_request("a/b", "feat: add cache", "feat/cache"))
    body = json.loads(route.calls.last.request.content)
    assert body["base"] == "main"
    assert result["number"] == 9


def test_get_file_contents_returns_raw_text(token, rx):
    rx.get("/repos/a/b/contents/src/server.py").mock(
        return_value=httpx.Response(200, text="print('hi')\n")
    )
    result = json.loads(server.get_file_contents("a/b", "src/server.py"))
    assert result["content"] == "print('hi')\n"


def test_get_file_contents_refuses_oversized_files(token, rx):
    rx.get("/repos/a/b/contents/big.txt").mock(
        return_value=httpx.Response(200, text="x" * 100_001)
    )
    result = json.loads(server.get_file_contents("a/b", "big.txt"))
    assert "limit" in result["error"]


def test_search_code_adds_repo_qualifier(token, rx):
    route = rx.get("/search/code").mock(
        return_value=httpx.Response(
            200,
            json={
                "total_count": 1,
                "items": [
                    {
                        "name": "server.py",
                        "path": "src/server.py",
                        "repository": {"full_name": "a/b"},
                        "html_url": "https://x",
                    }
                ],
            },
        )
    )
    result = json.loads(server.search_code("RepoNotFound", repo="a/b"))
    assert route.calls.last.request.url.params["q"] == "repo:a/b RepoNotFound"
    assert result["items"][0]["path"] == "src/server.py"


def test_api_failure_returns_error_json(token, rx):
    rx.get("/repos/a/b/issues").mock(return_value=httpx.Response(500, text="boom"))
    result = json.loads(server.list_issues("a/b"))
    assert "error" in result
