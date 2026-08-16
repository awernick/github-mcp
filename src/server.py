"""FastMCP server exposing flat GitHub tools (issues, PRs, code browsing).

Purpose-built for local LLM clients (Open WebUI on llama-swap, OpenCode):
flat scalar arguments, comma-separated strings instead of JSON arrays, and
trimmed JSON-string responses. This deliberately covers only the workflows
needed for planning features and bug fixes in chat (issues, PRs, code
browsing); the official github-mcp-server covers the rest at a much larger
schema cost.

Auth: a single fine-grained PAT from GITHUB_PERSONAL_ACCESS_TOKEN (Issues
r/w, Pull requests r/w, Contents r, Checks r for the CI summary, Metadata
r). Transport is
stdio by default; set MCP_TRANSPORT=http for streamable-http (Docker),
with MCP_HOST/MCP_PORT overrides. A local .env file is loaded if present.
Every tool returns a JSON string and isolates failures as {"error": ...}.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from dotenv import load_dotenv
from fastmcp import FastMCP

from gh_client import ApiClientError, GitHubClient

load_dotenv()

mcp = FastMCP("GitHub")

MAX_FILE_CHARS = 100_000

_client: GitHubClient | None = None


def get_client() -> GitHubClient | None:
    """Lazily create the shared client; None when the PAT is not set."""
    global _client
    token = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "").strip()
    if not token:
        return None
    if _client is None:
        _client = GitHubClient(token)
    return _client


def _json(data: Any) -> str:
    return json.dumps(data, indent=2)


def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
    gh = get_client()
    if gh is None:
        return _json({"error": "GITHUB_PERSONAL_ACCESS_TOKEN is not set"})
    try:
        return _json(fn(gh, *args, **kwargs))
    except ApiClientError as e:
        return _json({"error": str(e)})


def _split_csv(value: str | None) -> list[str] | None:
    """Split a comma-separated argument into a list, or None if empty."""
    if value is None:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _trim_issue(issue: dict) -> dict:
    return {
        "number": issue["number"],
        "title": issue["title"],
        "state": issue["state"],
        "user": issue["user"]["login"],
        "labels": [label["name"] for label in issue.get("labels", [])],
        "assignees": [a["login"] for a in issue.get("assignees", [])],
        "comments": issue.get("comments", 0),
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "html_url": issue["html_url"],
    }


def _trim_pull_request(pr: dict) -> dict:
    return {
        "number": pr["number"],
        "title": pr["title"],
        "state": pr["state"],
        "draft": pr.get("draft", False),
        "user": pr["user"]["login"],
        "head": pr["head"]["ref"],
        "base": pr["base"]["ref"],
        "created_at": pr.get("created_at"),
        "updated_at": pr.get("updated_at"),
        "html_url": pr["html_url"],
    }


# --------------------------------------------------------------------------
# Identity


@mcp.tool
def get_me() -> str:
    """Get the authenticated GitHub user (login, name, profile URL)."""
    def run(gh: GitHubClient) -> dict:
        user = gh.get("/user")
        return {
            "login": user["login"],
            "name": user.get("name"),
            "html_url": user["html_url"],
        }

    return _call(run)


# --------------------------------------------------------------------------
# Issues


@mcp.tool
def list_issues(
    repo: str,
    state: str = "open",
    labels: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> str:
    """List issues in a repository.

    Args:
        repo: Repository as "owner/repo".
        state: "open", "closed", or "all" (default "open").
        labels: Optional comma-separated label names to filter by.
        page: Page number (default 1).
        per_page: Results per page, max 100 (default 20).
    """
    def run(gh: GitHubClient) -> list:
        items = gh.get(
            f"/repos/{repo}/issues",
            params={
                "state": state,
                "labels": labels,
                "page": page,
                "per_page": min(per_page, 100),
            },
        )
        # The Issues API returns pull requests too; drop them.
        return [_trim_issue(i) for i in items if "pull_request" not in i]

    return _call(run)


@mcp.tool
def search_issues(query: str, repo: str | None = None, per_page: int = 20) -> str:
    """Search issues and pull requests with GitHub search syntax.

    Args:
        query: Search query, e.g. "is:open login bug" (qualifiers like
            is:open, label:bug, assignee:user are supported).
        repo: Optional "owner/repo" to restrict the search to one repository.
        per_page: Results per page, max 100 (default 20).
    """
    def run(gh: GitHubClient) -> dict:
        q = f"repo:{repo} {query}" if repo else query
        result = gh.get(
            "/search/issues", params={"q": q, "per_page": min(per_page, 100)}
        )
        return {
            "total_count": result["total_count"],
            "items": [
                {
                    **_trim_issue(i),
                    "is_pull_request": "pull_request" in i,
                }
                for i in result["items"]
            ],
        }

    return _call(run)


@mcp.tool
def get_issue(repo: str, number: int, include_comments: bool = True) -> str:
    """Get a single issue with its body and (optionally) its comments.

    Args:
        repo: Repository as "owner/repo".
        number: Issue number.
        include_comments: Also fetch up to 50 comments (default true).
    """
    def run(gh: GitHubClient) -> dict:
        issue = gh.get(f"/repos/{repo}/issues/{number}")
        result: dict[str, Any] = {**_trim_issue(issue), "body": issue.get("body")}
        if include_comments:
            comments = gh.get(
                f"/repos/{repo}/issues/{number}/comments", params={"per_page": 50}
            )
            result["comment_list"] = [
                {
                    "user": c["user"]["login"],
                    "created_at": c["created_at"],
                    "body": c["body"],
                }
                for c in comments
            ]
        return result

    return _call(run)


@mcp.tool
def create_issue(
    repo: str,
    title: str,
    body: str = "",
    labels: str | None = None,
    assignees: str | None = None,
) -> str:
    """Create an issue.

    Args:
        repo: Repository as "owner/repo".
        title: Issue title.
        body: Issue body in Markdown (optional).
        labels: Optional comma-separated label names.
        assignees: Optional comma-separated GitHub usernames.
    """
    def run(gh: GitHubClient) -> dict:
        payload: dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = _split_csv(labels)
        if assignees:
            payload["assignees"] = _split_csv(assignees)
        created = gh.post(f"/repos/{repo}/issues", json_body=payload)
        return _trim_issue(created)

    return _call(run)


@mcp.tool
def update_issue(
    repo: str,
    number: int,
    title: str | None = None,
    body: str | None = None,
    state: str | None = None,
) -> str:
    """Update an issue's title, body, or state. Title/body replace in full.

    Args:
        repo: Repository as "owner/repo".
        number: Issue number.
        title: New title (omit to keep current).
        body: New Markdown body, replacing the old one (omit to keep current).
        state: "open" or "closed" (omit to keep current).
    """
    def run(gh: GitHubClient) -> dict:
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if state is not None:
            if state not in ("open", "closed"):
                raise ApiClientError('state must be "open" or "closed"')
            payload["state"] = state
        if not payload:
            raise ApiClientError("nothing to update: pass title, body, or state")
        updated = gh.patch(f"/repos/{repo}/issues/{number}", json_body=payload)
        return _trim_issue(updated)

    return _call(run)


@mcp.tool
def add_issue_comment(repo: str, number: int, body: str) -> str:
    """Comment on an issue. Also works on pull requests.

    Args:
        repo: Repository as "owner/repo".
        number: Issue number.
        body: Comment text in Markdown.
    """
    def run(gh: GitHubClient) -> dict:
        comment = gh.post(
            f"/repos/{repo}/issues/{number}/comments", json_body={"body": body}
        )
        return {"id": comment["id"], "html_url": comment["html_url"]}

    return _call(run)


# --------------------------------------------------------------------------
# Pull requests


@mcp.tool
def list_pull_requests(
    repo: str, state: str = "open", page: int = 1, per_page: int = 20
) -> str:
    """List pull requests in a repository.

    Args:
        repo: Repository as "owner/repo".
        state: "open", "closed", or "all" (default "open").
        page: Page number (default 1).
        per_page: Results per page, max 100 (default 20).
    """
    def run(gh: GitHubClient) -> list:
        items = gh.get(
            f"/repos/{repo}/pulls",
            params={"state": state, "page": page, "per_page": min(per_page, 100)},
        )
        return [_trim_pull_request(pr) for pr in items]

    return _call(run)


@mcp.tool
def get_pull_request(repo: str, number: int) -> str:
    """Get a pull request with its changed files and CI check summary.

    Files are capped at the first 100; files_truncated is true when the PR
    has more. Checks summarize GitHub Actions runs on the head commit.

    Args:
        repo: Repository as "owner/repo".
        number: Pull request number.
    """
    def run(gh: GitHubClient) -> dict:
        pr = gh.get(f"/repos/{repo}/pulls/{number}")
        files = gh.get(f"/repos/{repo}/pulls/{number}/files", params={"per_page": 100})
        # CI summary is optional: check-runs requires Checks: read on the
        # token; a 403 means the grant is missing, not that the call failed.
        checks_error = None
        try:
            check_runs = gh.get(
                f"/repos/{repo}/commits/{pr['head']['sha']}/check-runs",
                params={"per_page": 100},
            ).get("check_runs", [])
            checks: Any = [
                {"name": c["name"], "status": c["status"], "conclusion": c.get("conclusion")}
                for c in check_runs
            ]
        except ApiClientError:
            checks = None
            checks_error = "CI summary unavailable: grant Checks: read on the PAT"
        result: dict[str, Any] = {
            "pull_request": {
                **_trim_pull_request(pr),
                "body": pr.get("body"),
                "mergeable": pr.get("mergeable"),
                "additions": pr.get("additions"),
                "deletions": pr.get("deletions"),
            },
            "files": [
                {
                    "filename": f["filename"],
                    "status": f["status"],
                    "additions": f["additions"],
                    "deletions": f["deletions"],
                }
                for f in files
            ],
            "files_truncated": pr.get("changed_files", 0) > 100,
            "checks": checks,
        }
        if checks_error:
            result["checks_error"] = checks_error
        return result

    return _call(run)


@mcp.tool
def create_pull_request(
    repo: str,
    title: str,
    head: str,
    base: str | None = None,
    body: str = "",
    draft: bool = False,
) -> str:
    """Create a pull request.

    Args:
        repo: Repository as "owner/repo".
        title: PR title.
        head: Branch containing the changes ("branch", or "owner:branch" for forks).
        base: Branch to merge into (defaults to the repository's default branch).
        body: PR body in Markdown (optional).
        draft: Create as a draft PR (default false).
    """
    def run(gh: GitHubClient) -> dict:
        target_base = base or gh.get(f"/repos/{repo}")["default_branch"]
        created = gh.post(
            f"/repos/{repo}/pulls",
            json_body={
                "title": title,
                "head": head,
                "base": target_base,
                "body": body,
                "draft": draft,
            },
        )
        return _trim_pull_request(created)

    return _call(run)


@mcp.tool
def add_pr_comment(repo: str, number: int, body: str) -> str:
    """Comment on a pull request (general conversation, not a code review).

    Args:
        repo: Repository as "owner/repo".
        number: Pull request number.
        body: Comment text in Markdown.
    """
    def run(gh: GitHubClient) -> dict:
        comment = gh.post(
            f"/repos/{repo}/issues/{number}/comments", json_body={"body": body}
        )
        return {"id": comment["id"], "html_url": comment["html_url"]}

    return _call(run)


# --------------------------------------------------------------------------
# Repository discovery


def _trim_repo(repo: dict) -> dict:
    return {
        "full_name": repo["full_name"],
        "description": repo.get("description"),
        "stars": repo.get("stargazers_count", 0),
        "forks": repo.get("forks_count", 0),
        "open_issues": repo.get("open_issues_count", 0),
        "language": repo.get("language"),
        "topics": repo.get("topics", []),
        "license": (repo.get("license") or {}).get("spdx_id"),
        "default_branch": repo.get("default_branch"),
        "archived": repo.get("archived", False),
        "pushed_at": repo.get("pushed_at"),
        "created_at": repo.get("created_at"),
        "html_url": repo["html_url"],
    }


@mcp.tool
def search_repositories(
    query: str,
    language: str | None = None,
    min_stars: int | None = None,
    page: int = 1,
    per_page: int = 20,
) -> str:
    """Search repositories, sorted by popularity (stars) descending.

    Use this to explore existing repos and projects, e.g. find the most
    starred implementations of a tool or library.

    Args:
        query: Repository search text, e.g. "mcp server" or "typo checker".
        language: Optional language filter, e.g. "python", "typescript".
        min_stars: Only include repos with at least this many stars.
        page: Page number (default 1).
        per_page: Results per page, max 100 (default 20).
    """
    def run(gh: GitHubClient) -> dict:
        parts = [query]
        if language:
            parts.append(f"language:{language}")
        if min_stars is not None and min_stars > 0:
            parts.append(f"stars:>={min_stars}")
        result = gh.get(
            "/search/repositories",
            params={
                "q": " ".join(parts),
                "sort": "stars",
                "order": "desc",
                "page": page,
                "per_page": min(per_page, 100),
            },
        )
        return {
            "total_count": result["total_count"],
            "items": [_trim_repo(i) for i in result["items"]],
        }

    return _call(run)


@mcp.tool
def get_repo(repo: str) -> str:
    """Get a repository's summary card (stars, forks, language, topics).
    Use with search_repositories to evaluate repos found by popularity.

    Args:
        repo: Repository as "owner/repo".
    """
    def run(gh: GitHubClient) -> dict:
        repo_data = gh.get(f"/repos/{repo}")
        trimmed = _trim_repo(repo_data)
        trimmed["homepage"] = repo_data.get("homepage")
        return trimmed

    return _call(run)


# --------------------------------------------------------------------------
# Code browsing


@mcp.tool
def get_file_contents(repo: str, path: str, ref: str | None = None) -> str:
    """Get the raw text contents of a file in a repository.

    Files larger than 100,000 characters are refused to protect the context
    window; fetch a narrower path instead.

    Args:
        repo: Repository as "owner/repo".
        path: File path within the repository, e.g. "src/server.py".
        ref: Branch, tag, or commit SHA (defaults to the default branch).
    """
    def run(gh: GitHubClient) -> dict:
        params = {"ref": ref} if ref else None
        text = gh.get(f"/repos/{repo}/contents/{path}", params=params, raw=True)
        if len(text) > MAX_FILE_CHARS:
            raise ApiClientError(
                f"file is {len(text)} chars (limit {MAX_FILE_CHARS}); fetch a smaller file"
            )
        return {"repo": repo, "path": path, "ref": ref, "content": text}

    return _call(run)


@mcp.tool
def search_code(query: str, repo: str | None = None, per_page: int = 20) -> str:
    """Search code with GitHub code search syntax.

    Args:
        query: Code search query, e.g. "addEventListener language:python".
        repo: Optional "owner/repo" to restrict the search to one repository.
        per_page: Results per page, max 100 (default 20).
    """
    def run(gh: GitHubClient) -> dict:
        q = f"repo:{repo} {query}" if repo else query
        result = gh.get("/search/code", params={"q": q, "per_page": min(per_page, 100)})
        return {
            "total_count": result["total_count"],
            "items": [
                {
                    "name": item["name"],
                    "path": item["path"],
                    "repository": item["repository"]["full_name"],
                    "html_url": item["html_url"],
                }
                for item in result["items"]
            ],
        }

    return _call(run)


# --------------------------------------------------------------------------
# Entrypoint


def main() -> None:
    """Run the MCP server.

    Default is stdio (local MCP clients). Set MCP_TRANSPORT=http to serve
    streamable-http (used by the Docker image); MCP_HOST/MCP_PORT override
    bind address and port.
    """
    transport = os.environ.get("MCP_TRANSPORT", "stdio").strip().lower()
    if transport in ("http", "streamable-http", "sse"):
        mcp.run(
            transport="streamable-http" if transport != "sse" else "sse",
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "3102")),
        )
    else:
        mcp.run()


if __name__ == "__main__":
    main()
