"""Async httpx client for the AEPD resolutions search (Agencia Espanola de Proteccion
de Datos, ``www.aepd.es/informes-y-resoluciones/resoluciones``).

The site is Drupal with a Solr-backed view whose exposed filters are plain GET
parameters - a stable machine path without any token or session:

- ``GET /informes-y-resoluciones/resoluciones?search_api_fulltext=...&``
  ``fecha_firma_desde=...&fecha_firma_hasta=...&page=N`` - full-text search over the
  resolution corpus. The dedicated total field is "N resultados"; the empty-result
  marker is "No se encontraron resultados". Dates are ``dd/mm/aaaa``; ``page`` is
  0-based (Drupal pager).
- Every hit carries the expediente number as its title (e.g. ``PS-00615-2025``), a
  body snippet, the signature date, and a deterministic PDF permalink
  ``/documento/{slug}.pdf`` (the full resolution text).

Verified live 2026-07-08: 46 767 resoluciones unfiltered; full-text narrows
("videovigilancia" -> 7 818); an exact expediente number as the full-text query
returns exactly its one resolution. Keyless, no CAPTCHA; Spanish PSI open data.
"""

from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass, field
from urllib.parse import urlencode

import anyio
import httpx

from .cache import HttpCache

DEFAULT_AEPD_BASE_URL = "https://www.aepd.es"
DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
USER_AGENT = "es-eli-mcp/0.3.0 (+https://github.com/matematicsolutions/es-eli-mcp)"

# The AEPD search intermittently sheds load with per-query 503s (observed live
# 2026-07-08: the same query flips 503 -> 200 within a minute, independent of the
# client), so retries are more patient here than in the sibling clients.
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 4

_TOTAL_RE = re.compile(r"([\d.,]+)\s*resultados")
_NO_RESULTS_MARKER = "No se encontraron resultados"
_TITLE_RE = re.compile(r"field--name-title[^>]*><h2>([^<]+)</h2>")
_PDF_RE = re.compile(r'href="(/documento/[^"]+\.pdf)"')
_FECHA_RE = re.compile(r'<time datetime="([^"]+)"')
_BODY_RE = re.compile(r"field--name-body[^>]*>\s*<p>(.*?)</p>", re.DOTALL)


class AepdError(Exception):
    """Raised on an upstream AEPD HTTP/parse error."""


class AepdNotFoundError(AepdError):
    """Raised when an expediente number does not resolve to a resolution."""


def _strip_tags(raw_html: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw_html)
    text = html_module.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_total(html: str) -> int:
    if _NO_RESULTS_MARKER in html:
        return 0
    m = _TOTAL_RE.search(html)
    if not m:
        return 0
    return int(m.group(1).replace(".", "").replace(",", ""))


@dataclass
class AepdResolutionHit:
    """One resolution teaser on an AEPD results page."""

    expediente: str  # e.g. "PS-00615-2025"
    pdf_url: str | None = None  # absolute URL of the full-text PDF
    fecha_firma: str | None = None  # ISO date (from the page's <time datetime>)
    snippet: str | None = None


@dataclass
class AepdSearchPage:
    """A parsed AEPD results page."""

    total: int
    page: int  # 1-based, as exposed to the tools
    hits: list[AepdResolutionHit] = field(default_factory=list)


class AepdClient:
    """Async client. Use as ``async with AepdClient() as c: ...``."""

    def __init__(
        self,
        base_url: str = DEFAULT_AEPD_BASE_URL,
        cache: HttpCache | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._cache = cache or HttpCache()
        self._http = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
            follow_redirects=True,
        )

    async def __aenter__(self) -> AepdClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()
        self._cache.close()

    # ----- low-level -----------------------------------------------------

    async def _request(self, url: str) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = await self._http.get(url)
                if resp.status_code in _RETRY_STATUS and attempt < _MAX_ATTEMPTS - 1:
                    await anyio.sleep(1.0 * (2**attempt))
                    continue
                return resp
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt == _MAX_ATTEMPTS - 1:
                    raise
                await anyio.sleep(1.0 * (2**attempt))
        assert last_exc is not None
        raise last_exc

    # ----- search ----------------------------------------------------------

    def _parse_search(self, html: str, page: int) -> AepdSearchPage:
        total = _parse_total(html)
        hits: list[AepdResolutionHit] = []
        # Hits are <article> teasers; walk them one by one so fields stay paired.
        for block in re.split(r"<article", html)[1:]:
            title_m = _TITLE_RE.search(block)
            if not title_m:
                continue
            pdf_m = _PDF_RE.search(block)
            fecha_m = _FECHA_RE.search(block)
            body_m = _BODY_RE.search(block)
            hits.append(
                AepdResolutionHit(
                    expediente=html_module.unescape(title_m.group(1)).strip(),
                    pdf_url=(self.base_url + pdf_m.group(1)) if pdf_m else None,
                    fecha_firma=fecha_m.group(1)[:10] if fecha_m else None,
                    snippet=_strip_tags(body_m.group(1)) if body_m else None,
                )
            )
        return AepdSearchPage(total=total, page=page, hits=hits)

    async def search(
        self,
        *,
        texto: str | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        page: int = 1,
    ) -> AepdSearchPage:
        """Full-text search over AEPD resolutions. Dates are ``dd/mm/aaaa``;
        ``page`` is 1-based here (mapped to Drupal's 0-based pager)."""
        params: dict[str, str] = {"sort_bef_combine": "fecha_firma_DESC"}
        if texto:
            params["search_api_fulltext"] = texto.strip()
        if fecha_desde:
            params["fecha_firma_desde"] = fecha_desde.strip()
        if fecha_hasta:
            params["fecha_firma_hasta"] = fecha_hasta.strip()
        if page > 1:
            params["page"] = str(page - 1)
        url = f"{self.base_url}/informes-y-resoluciones/resoluciones?{urlencode(params)}"
        cache_key = "aepd-search::" + url
        cached = self._cache.get(cache_key)
        if cached is not None:
            return AepdSearchPage(
                total=cached["total"],
                page=cached["page"],
                hits=[AepdResolutionHit(**h) for h in cached["hits"]],
            )
        resp = await self._request(url)
        if resp.status_code >= 400:
            raise AepdError(f"HTTP {resp.status_code} from AEPD search.")
        result = self._parse_search(resp.text, page)
        self._cache.set(
            cache_key,
            {"total": result.total, "page": result.page, "hits": [h.__dict__ for h in result.hits]},
            ttl=HttpCache.ttl_for("search"),
        )
        return result

    # ----- one resolution by expediente ---------------------------------------

    async def get_resolution(self, expediente: str) -> AepdResolutionHit:
        """Resolve an expediente number (e.g. ``"PS-00615-2025"``) to its resolution
        teaser + PDF permalink via an exact full-text query.

        When the search endpoint is shedding load (intermittent 503), fall back to the
        deterministic PDF permalink ``/documento/{expediente-lowercase}.pdf`` and verify
        it live with a HEAD request before returning it.
        """
        exp = expediente.strip().upper()
        cache_key = f"aepd-resolution::{exp}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return AepdResolutionHit(**cached)
        try:
            page = await self.search(texto=exp)
        except AepdError:
            hit = await self._resolution_via_pdf_head(exp)
            self._cache.set(cache_key, hit.__dict__, ttl=HttpCache.ttl_for("act"))
            return hit
        for hit in page.hits:
            if hit.expediente.upper() == exp:
                self._cache.set(cache_key, hit.__dict__, ttl=HttpCache.ttl_for("act"))
                return hit
        raise AepdNotFoundError(f"No AEPD resolution found for expediente {exp!r}.")

    async def _resolution_via_pdf_head(self, exp: str) -> AepdResolutionHit:
        """Verify the deterministic PDF permalink with a HEAD request (search is down)."""
        pdf_url = f"{self.base_url}/documento/{exp.lower()}.pdf"
        try:
            resp = await self._http.head(pdf_url)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            raise AepdError(f"AEPD search unavailable and PDF probe failed: {exc}") from exc
        if resp.status_code == 200:
            return AepdResolutionHit(expediente=exp, pdf_url=pdf_url)
        if resp.status_code == 404:
            raise AepdNotFoundError(f"No AEPD resolution found for expediente {exp!r}.")
        raise AepdError(
            f"AEPD search unavailable and PDF probe returned HTTP {resp.status_code}."
        )


__all__ = [
    "DEFAULT_AEPD_BASE_URL",
    "AepdClient",
    "AepdError",
    "AepdNotFoundError",
    "AepdResolutionHit",
    "AepdSearchPage",
]
