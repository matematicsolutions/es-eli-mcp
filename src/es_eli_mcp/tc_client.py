"""Async httpx client for the Spanish Constitutional Court jurisprudence search engine
(``hj.tribunalconstitucional.es`` - "Sistema HJ / Buscador de jurisprudencia constitucional").

There is no JSON API: the site is a classic ASP.NET MVC app rendering server-side HTML. Two
flows are used:

- **Direct lookup by internal id** - ``GET /es/Resolucion/Show/{id}`` (sequential ids, no
  auth). A not-found id 302s/renders the search-form page instead of the resolution page; we
  detect that by title.
- **Lookup by human citation (e.g. "STC 31/2010")** - the site has no by-number permalink,
  so we drive the actual HTML search form: fetch the anti-forgery token + session cookie from
  ``/es/Busqueda/Index``, ``POST`` ``NUMERO_RESOLUCION`` + ``ANNO_RESOLUCION`` +
  ``TIPO_RESOLUCION`` to ``/es/Busqueda/Buscar`` (302 redirect, results kept server-side in
  session), then ``GET /es/Resolucion/List`` with the same cookies to read the one matching
  internal id out of the result list.

No CAPTCHA, no robots.txt disallow, no ToS-gated endpoint - this is the same public form a
human visitor uses. Data is Spanish PSI (public-sector information) open data.
"""

from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass
from typing import Any

import anyio
import httpx

from .cache import HttpCache

DEFAULT_TC_BASE_URL = "https://hj.tribunalconstitucional.es"
DEFAULT_TIMEOUT = httpx.Timeout(40.0, connect=10.0)
USER_AGENT = "es-eli-mcp/0.2.0 (+https://github.com/matematicsolutions/es-eli-mcp)"

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3

_NOT_FOUND_TITLE = "Buscador de jurisprudencia constitucional"

_TOKEN_RE = re.compile(
    r'name="__RequestVerificationToken"\s+type="hidden"\s+value="([^"]*)"'
)
_TITLE_RE = re.compile(r"<title>([^<]*)</title>")
_HEADING_RE = re.compile(
    r'<li id="resolucion-identifier">\s*<h2>\s*([^<]*?)\s*(?:<span|</h2>)', re.DOTALL
)
_ECLI_RE = re.compile(r'<label class="ecli">\s*([^<]*?)\s*</label>')
_SENTENCIA_RE = re.compile(r"<p id=\"resolucion-sentencia\">(.*?)</p>", re.DOTALL)
_FALLO_RE = re.compile(r'<p id="dictamen-texto">(.*?)(?:</div>|$)', re.DOTALL)
_SALA_RE = re.compile(r"(Pleno|Sala Primera|Sala Segunda)")
_SHOW_ID_RE = re.compile(r"Resolucion/Show/(\d+)")


class TcError(Exception):
    """Raised on an upstream Tribunal Constitucional HTML/session error."""


class TcNotFoundError(TcError):
    """Raised when a resolution id or citation does not resolve to a real record."""


def _strip_tags(raw_html: str) -> str:
    """Minimal tag stripper for prose fields (no external HTML parser dependency)."""
    text = re.sub(r"<br\s*/?>", "\n", raw_html)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_module.unescape(text)
    return re.sub(r"[ \t]+", " ", text).strip()


@dataclass
class TcResolution:
    """A parsed Tribunal Constitucional resolution page."""

    id: str
    title: str | None  # e.g. "SENTENCIA 117/2016, de 20 de junio"
    ecli: str | None  # e.g. "ECLI:ES:TC:2016:117"
    sala: str | None  # "Pleno" | "Sala Primera" | "Sala Segunda"
    encabezamiento: str | None
    fallo: str | None
    source_url: str


class TcClient:
    """Async client. Use as ``async with TcClient() as c: ...``."""

    def __init__(
        self,
        base_url: str = DEFAULT_TC_BASE_URL,
        cache: HttpCache | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._cache = cache or HttpCache()
        self._http = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=False,
        )

    async def __aenter__(self) -> TcClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()
        self._cache.close()

    # ----- low-level -----------------------------------------------------

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = await self._http.request(method, url, **kwargs)
                if resp.status_code in _RETRY_STATUS and attempt < _MAX_ATTEMPTS - 1:
                    await anyio.sleep(0.5 * (2**attempt))
                    continue
                return resp
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt == _MAX_ATTEMPTS - 1:
                    raise
                await anyio.sleep(0.5 * (2**attempt))
        assert last_exc is not None
        raise last_exc

    # ----- resolution by internal id --------------------------------------

    async def get_resolution(self, resolution_id: str) -> TcResolution:
        """Fetch and parse a resolution page by its internal sequential id."""
        url = f"{self.base_url}/es/Resolucion/Show/{resolution_id}"
        cache_key = "tc::" + url
        cached = self._cache.get(cache_key)
        if cached is not None:
            return TcResolution(**cached)

        resp = await self._request("GET", url, headers={"Accept": "text/html"})
        if resp.status_code >= 400:
            raise TcError(f"HTTP {resp.status_code} fetching {url}")
        html = resp.text

        title_match = _TITLE_RE.search(html)
        page_title = html_module.unescape(title_match.group(1).strip()) if title_match else ""
        # Real resolution pages title as "Sistema HJ - Resolución: SENTENCIA N/YYYY, de ...".
        # A not-found/unresolved id redirects to the search-form page instead, titled
        # "Sistema HJ - Buscador de jurisprudencia constitucional" - no "Resolución:" segment.
        if _NOT_FOUND_TITLE in page_title or "Resoluci" not in page_title or ":" not in page_title:
            raise TcNotFoundError(f"No resolution found for id {resolution_id!r}.")

        ecli_match = _ECLI_RE.search(html)
        sentencia_match = _SENTENCIA_RE.search(html)
        fallo_match = _FALLO_RE.search(html)
        sala_match = _SALA_RE.search(html)
        heading_match = _HEADING_RE.search(html)

        if heading_match:
            display_title = html_module.unescape(heading_match.group(1)).strip()
        elif ":" in page_title:
            display_title = page_title.split(":", 1)[-1].strip()
        else:
            display_title = None

        result = TcResolution(
            id=resolution_id,
            title=display_title or None,
            ecli=ecli_match.group(1).strip() if ecli_match else None,
            sala=sala_match.group(1) if sala_match else None,
            encabezamiento=_strip_tags(sentencia_match.group(1)) if sentencia_match else None,
            fallo=_strip_tags(fallo_match.group(1)) if fallo_match else None,
            source_url=url,
        )
        self._cache.set(cache_key, result.__dict__, ttl=HttpCache.ttl_for("act"))
        return result

    # ----- lookup by human citation (numero + anno [+ tipo]) --------------

    async def find_id_by_citation(
        self, numero: str, anno: str, tipo: str = "SENTENCIA"
    ) -> str:
        """Resolve (numero, anno, tipo) -> internal resolution id via the live search form.

        ``tipo`` is one of ``SENTENCIA`` | ``AUTO`` | ``DECLARACION`` (site's checkbox
        values). Raises ``TcNotFoundError`` if the search returns no match.
        """
        cache_key = f"tc-search::{tipo}::{numero}::{anno}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return str(cached)

        # This is a 3-request session flow (form token -> POST search -> GET results), so
        # cookies are kept on the shared client's own jar rather than passed per-request.
        index_url = f"{self.base_url}/es/Busqueda/Index"
        index_resp = await self._request("GET", index_url, headers={"Accept": "text/html"})
        if index_resp.status_code >= 400:
            raise TcError(f"HTTP {index_resp.status_code} fetching {index_url}")
        token_match = _TOKEN_RE.search(index_resp.text)
        if not token_match:
            raise TcError("Could not find __RequestVerificationToken on search form.")
        token = token_match.group(1)

        search_url = f"{self.base_url}/es/Busqueda/Buscar"
        body = (
            f"__RequestVerificationToken={token}"
            f"&TIPO_RESOLUCION={tipo}"
            f"&NUMERO_RESOLUCION={numero}"
            f"&ANNO_RESOLUCION={anno}"
        )
        search_resp = await self._request(
            "POST",
            search_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            content=body,
        )
        if search_resp.status_code not in (200, 302):
            raise TcError(f"HTTP {search_resp.status_code} posting search form.")

        list_url = f"{self.base_url}/es/Resolucion/List"
        list_resp = await self._request("GET", list_url, headers={"Accept": "text/html"})
        if list_resp.status_code >= 400:
            raise TcError(f"HTTP {list_resp.status_code} fetching {list_url}")

        expected_label = f"{tipo} {numero}/{anno}"
        html = list_resp.text
        # Find "<a ... Resolucion/Show/{id} ...> ... TIPO NUMERO/ANNO ...</a>"-style blocks.
        for match in re.finditer(
            r'href="[^"]*Resolucion/Show/(\d+)"[^>]*>\s*([^<]*)', html
        ):
            candidate_id, label = match.group(1), match.group(2)
            if expected_label in label or f"{numero}/{anno}" in label:
                self._cache.set(cache_key, candidate_id, ttl=HttpCache.ttl_for("act"))
                return candidate_id

        raise TcNotFoundError(
            f"No {tipo} {numero}/{anno} found via Tribunal Constitucional search."
        )
