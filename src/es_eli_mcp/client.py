"""Async httpx client for the Spanish BOE open-data API (boe.es) with cache.

BOE is keyless. Metadata / index / gazette are JSON (wrapped in ``{status, data}``); the
consolidated text blocks are served as XML only. Note: the BOE keyword-search endpoint
(/legislacion-consolidada) returns HTTP 500 server-side, so it is not wrapped here.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import anyio
import httpx

from .cache import HttpCache

DEFAULT_BASE_URL = "https://www.boe.es/datosabiertos/api"
DEFAULT_TIMEOUT = httpx.Timeout(40.0, connect=10.0)
USER_AGENT = "es-eli-mcp/0.1.0 (+https://github.com/matematicsolutions/es-eli-mcp)"

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3
_LEG = "/legislacion-consolidada/id"


class BoeError(Exception):
    """Raised when BOE returns a non-ok status envelope."""


class BoeClient:
    """Async client. Use as ``async with BoeClient() as c: ...``."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        cache: HttpCache | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._cache = cache or HttpCache()
        self._http = httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT})

    async def __aenter__(self) -> BoeClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()
        self._cache.close()

    # ----- low-level ---------------------------------------------------------

    async def _request(self, url: str, *, accept: str) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = await self._http.get(url, headers={"Accept": accept})
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code not in _RETRY_STATUS or attempt == _MAX_ATTEMPTS - 1:
                    raise
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt == _MAX_ATTEMPTS - 1:
                    raise
            await anyio.sleep(0.5 * (2**attempt))
        assert last_exc is not None
        raise last_exc

    async def _get_json(self, path: str, *, category: str) -> Any:
        url = f"{self.base_url}{path}"
        cached = self._cache.get(url)
        if cached is not None:
            return cached
        resp = await self._request(url, accept="application/json")
        data = resp.json()
        self._cache.set(url, data, ttl=HttpCache.ttl_for(category))
        return data

    @staticmethod
    def _unwrap(payload: Any) -> Any:
        """Return the ``data`` of a BOE envelope; raise BoeError on a non-ok status."""
        if isinstance(payload, dict):
            status = payload.get("status")
            if isinstance(status, dict) and str(status.get("code")) not in ("200", "None"):
                raise BoeError(str(status.get("text", "BOE error")))
            return payload.get("data", payload)
        return payload

    # ----- typed endpoints ---------------------------------------------------

    async def metadatos(self, boe_id: str) -> dict[str, Any]:
        raw = await self._get_json(f"{_LEG}/{quote(boe_id)}/metadatos", category="act")
        data = self._unwrap(raw)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        if isinstance(data, dict):
            return data
        raise BoeError(f"Unexpected metadatos shape for {boe_id}")

    async def indice(self, boe_id: str) -> list[dict[str, Any]]:
        data = self._unwrap(
            await self._get_json(f"{_LEG}/{quote(boe_id)}/texto/indice", category="act")
        )
        first = data[0] if isinstance(data, list) and data else data
        blocks = first.get("bloque") if isinstance(first, dict) else None
        return [b for b in blocks if isinstance(b, dict)] if isinstance(blocks, list) else []

    async def texto(self, boe_id: str, block_id: str | None = None) -> tuple[str, str | None]:
        suffix = f"/texto/bloque/{quote(block_id)}" if block_id else "/texto"
        url = f"{self.base_url}{_LEG}/{quote(boe_id)}{suffix}"
        key = "xml::" + url
        cached = self._cache.get(key)
        if cached is not None and isinstance(cached, list) and len(cached) == 2:
            return cached[0], cached[1]
        resp = await self._request(url, accept="application/xml")
        text = resp.text
        ct = resp.headers.get("content-type")
        self._cache.set(key, [text, ct], ttl=HttpCache.ttl_for("act"))
        return text, ct

    async def sumario(self, date_yyyymmdd: str) -> Any:
        return self._unwrap(
            await self._get_json(f"/boe/sumario/{quote(date_yyyymmdd)}", category="changes")
        )
