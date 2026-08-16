# github-mcp

Thin [FastMCP](https://github.com/jlowin/fastmcp) server exposing flat GitHub
tools (issues, PRs, code browsing) over the GitHub REST API. Built for local
LLM clients: scalar arguments, comma-separated lists instead of JSON arrays,
trimmed JSON-string responses, and failures isolated as `{"error": ...}`.

Why not the official `github/github-mcp-server`? Its default toolset alone
registers 46 tools (~10-15k tokens of schema) with rich nested arguments,
and self-hosted it is stdio-only. This server keeps 15 flat tools (~2-3k
tokens) and speaks streamable HTTP natively, which Open WebUI consumes
directly. OpenCode terminal sessions continue to use the `gh` CLI.

## Tools

| Tool | Args | Notes |
|------|------|-------|
| `get_me` | | Authenticated user |
| `search_repositories` | query, language, min_stars, page, per_page | Sorted by stars desc; repo exploration by popularity |
| `get_repo` | repo | Summary card: stars, forks, language, topics, license |
| `list_issues` | repo, state, labels, page, per_page | PRs filtered out; labels comma-separated |
| `search_issues` | query, repo, per_page | GitHub search syntax; repo adds `repo:` qualifier |
| `get_issue` | repo, number, include_comments | Body + up to 50 comments |
| `create_issue` | repo, title, body, labels, assignees | Labels/assignees comma-separated |
| `update_issue` | repo, number, title, body, state | state: `open`/`closed` |
| `add_issue_comment` | repo, number, body | |
| `list_pull_requests` | repo, state, page, per_page | |
| `get_pull_request` | repo, number | Body, first 100 files, CI check summary |
| `create_pull_request` | repo, title, head, base, body, draft | base defaults to repo default branch |
| `add_pr_comment` | repo, number, body | General comment, not a code review |
| `get_file_contents` | repo, path, ref | Raw text, refused above 100k chars |
| `search_code` | query, repo, per_page | GitHub code search syntax |

`repo` arguments are always `"owner/repo"`.

## Auth

One fine-grained PAT in the environment (`GITHUB_PERSONAL_ACCESS_TOKEN`):
Issues r/w, Pull requests r/w, Contents r (also covers releases),
Metadata r (auto-granted; covers the check-run CI summary). Actions r is
not needed today, only if workflow-run tools are added later. A local
`.env` file is loaded if present.

## Run

```bash
# stdio (default, local MCP clients)
GITHUB_PERSONAL_ACCESS_TOKEN=... uv run github-mcp

# streamable-http (Docker does this via MCP_TRANSPORT=http)
MCP_TRANSPORT=http MCP_PORT=3102 uv run github-mcp
curl -s http://localhost:3102/mcp   # -> 406 (streamable-http requires MCP headers)
```

Docker image: `ghcr.io/awernick/github-mcp:main`, published on every push to
main. Deployed on robusto by awernick/picolino-config
(`robusto/github-mcp/`, port 3102); Open WebUI registers it as an external
tool server (Type: MCP Streamable HTTP) at `http://github-mcp:3102/mcp`.

## Development

```bash
uv sync --dev          # or: pip install -e ".[dev]"
uv run pytest
uv run ruff check .
```
