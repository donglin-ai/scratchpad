from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_HEADERS = {
    "User-Agent": "paper-reader/0.2",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def fetch_text(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> str:
    request = Request(url, headers={**DEFAULT_HEADERS, **(headers or {})})
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def fetch_bytes(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> bytes:
    request = Request(url, headers={**DEFAULT_HEADERS, **(headers or {})})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def post_json(url: str, payload: dict, headers: dict[str, str] | None = None, timeout: int = 60) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **DEFAULT_HEADERS, **(headers or {})},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset, errors="replace"))


__all__ = ["HTTPError", "URLError", "fetch_bytes", "fetch_text", "post_json"]
