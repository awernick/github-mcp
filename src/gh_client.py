"""Thin httpx-based GitHub REST API client.

Mirrors the client conventions in awernick/retail-deals-mcp: a small
synchronous wrapper, ApiClientError for every failure mode, and no response
models (tools trim raw JSON to what the LLM needs).
"""

from __future__ import annotations

from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.github.com"


class ApiClientError(Exception):
    """Raised for any GitHub API failure (network, auth, 4xx/5xx)."""


class GitHubClient:
    def __init__(self, token: str, base_url: str = DEFAULT_BASE_URL) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        raw: bool = False,
    ) -> Any:
        """Perform a GitHub REST request.

        With raw=True, requests the raw body (Accept: application/vnd.github.raw)
        and returns response text; otherwise returns parsed JSON.
        """
        headers = {"Accept": "application/vnd.github.raw"} if raw else None
        try:
            resp = self._http.request(
                method, path, params=params, json=json_body, headers=headers
            )
        except httpx.HTTPError as e:
            raise ApiClientError(f"GitHub request failed: {e}") from e

        if resp.status_code == 401:
            raise ApiClientError(
                "GitHub authentication failed (401): check GITHUB_PERSONAL_ACCESS_TOKEN"
            )
        if resp.status_code == 403:
            raise ApiClientError(
                "GitHub forbidden (403): insufficient PAT permissions or rate limited"
            )
        if resp.status_code == 404:
            raise ApiClientError(f"Not found: {method} {path} (404)")
        if resp.status_code == 422:
            raise ApiClientError(f"GitHub rejected the request (422): {resp.text[:500]}")
        if resp.status_code >= 400:
            raise ApiClientError(f"GitHub error {resp.status_code}: {resp.text[:500]}")

        return resp.text if raw else resp.json()

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Any:
        return self.request("PATCH", path, **kwargs)
