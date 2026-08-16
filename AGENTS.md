# github-mcp Agent Notes

- Package: flat `src/` layout with `py-modules` (mirrors awernick/retail-deals-mcp).
- Commands: `uv run pytest` (tests), `uv run ruff check .` (lint).
- All MCP tools return JSON **strings**; errors are `{"error": ...}` JSON,
  never exceptions. Keep tool arguments flat scalars (comma-separated strings
  instead of arrays) so small local models can call them.
- Tests mock HTTP with respx at `https://api.github.com`; fixtures in
  `tests/conftest.py` reset the client singleton.
- Do not log or echo `GITHUB_PERSONAL_ACCESS_TOKEN`; the PAT ships in a
  server-side `.env` on robusto, never in client config.
