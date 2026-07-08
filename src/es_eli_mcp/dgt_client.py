"""Async httpx client for the DGT tax-rulings search engine (Consultas de la Direccion
General de Tributos, ``petete.tributos.hacienda.gob.es``).

There is no JSON API: the site is a jQuery front-end over two server-side endpoints
(the same ones the public search form drives):

- ``GET /consultas/do/search`` - form-serialized filter params (``NMCMP_n``/``VLCMP_n``
  field pairs, ``type1``/``type2`` database checkboxes, ``tab``, ``page``). Returns an
  HTML fragment with the hit total (``updateNumResults``), the effective query string
  (hidden ``#query`` input) and one table row per hit (``doc_{id}``).
- ``GET /consultas/do/document`` - the ``query`` from the search response + ``doc`` +
  ``tab``. Returns the full ruling as an HTML fragment (field/value table rows).

Both requests must share one cookie session and carry ``Referer`` +
``X-Requested-With: XMLHttpRequest`` headers; the ``query`` parameter must be encoded
like JavaScript ``encodeURI`` (space -> ``%20``, parentheses literal) - anything else
is answered with HTTP 401. No CAPTCHA, no auth: this is the same public form a human
visitor uses. Data is Spanish PSI open data (~69 500 consultas vinculantes + ~19 700
consultas generales, live-counted 2026-07-08).
"""

from __future__ import annotations

import html as html_module
import re
import ssl
from dataclasses import dataclass, field
from urllib.parse import quote

import anyio
import httpx

from .cache import HttpCache


def _tls_verify() -> ssl.SSLContext | bool:
    """petete.tributos.hacienda.gob.es serves an incomplete certificate chain, so
    certifi-based verification fails while OS trust stores (which fetch the missing
    intermediate) succeed. Prefer the OS store via truststore; never disable
    verification."""
    try:
        import truststore
    except ImportError:  # pragma: no cover - truststore is a declared dependency
        return True
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

DEFAULT_DGT_BASE_URL = "https://petete.tributos.hacienda.gob.es"
DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
USER_AGENT = "es-eli-mcp/0.3.0 (+https://github.com/matematicsolutions/es-eli-mcp)"

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3

# Tab 1 = "Consultas generales", tab 2 = "Consultas vinculantes" (site's own numbering).
TAB_GENERALES = "1"
TAB_VINCULANTES = "2"

_TOTAL_RE = re.compile(r'updateNumResults\("\d",\s*"([\d.,]+)"\)')
_QUERY_RE = re.compile(r'id="query" value="([^"]*)"')
_TOTAL_PAGES_RE = re.compile(r'id="total_pages">(\d+)<')
_ROW_RE = re.compile(r'id="doc_(\d+)"[^>]*>(.*?)</td>', re.DOTALL)
_ROW_FIELD_RE = re.compile(r'<span class="([A-Z-]+)">(.*?)</span>', re.DOTALL)
_DOC_FIELD_RE = re.compile(
    r'<tr class="([A-Z-]+)">.*?<td class="value">(.*?)</td>', re.DOTALL
)
_NO_RESULTS_MARKER = "noResults()"


class DgtError(Exception):
    """Raised on an upstream DGT (petete) HTTP/session error."""


class DgtNotFoundError(DgtError):
    """Raised when a search or a consulta number does not resolve to a record."""


def _strip_tags(raw_html: str) -> str:
    """Minimal tag stripper for prose fields (no external HTML parser dependency)."""
    text = re.sub(r"<br\s*/?>", "\n", raw_html)
    text = re.sub(r"</p>\s*", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_module.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _parse_total(html: str) -> int:
    m = _TOTAL_RE.search(html)
    if not m:
        return 0
    return int(m.group(1).replace(".", "").replace(",", ""))


@dataclass
class DgtSearchHit:
    """One row of a DGT search-results fragment."""

    doc_id: str
    num_consulta: str | None = None
    descripcion_hechos: str | None = None
    cuestion_planteada: str | None = None


@dataclass
class DgtSearchPage:
    """A parsed DGT search-results fragment."""

    total: int
    total_pages: int
    page: int
    query: str  # the server's effective query string, needed to open a document
    hits: list[DgtSearchHit] = field(default_factory=list)


@dataclass
class DgtRuling:
    """A parsed DGT ruling document (all field/value rows of the document table)."""

    doc_id: str
    num_consulta: str | None
    organo: str | None
    fecha_salida: str | None
    normativa: str | None
    descripcion_hechos: str | None
    cuestion_planteada: str | None
    contestacion: str | None
    source_url: str


class DgtClient:
    """Async client. Use as ``async with DgtClient() as c: ...``.

    Search and document retrieval share this client's cookie jar - fetch a document
    with the same client instance that ran the search.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_DGT_BASE_URL,
        cache: HttpCache | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._cache = cache or HttpCache()
        self._http = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Referer": f"{self.base_url}/consultas",
                "X-Requested-With": "XMLHttpRequest",
            },
            follow_redirects=False,
            verify=_tls_verify(),
        )

    async def __aenter__(self) -> DgtClient:
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

    # ----- search ----------------------------------------------------------

    def _build_search_qs(
        self,
        *,
        tab: str,
        page: int,
        num_consulta: str | None,
        texto: str | None,
        fecha_desde: str | None,
        fecha_hasta: str | None,
    ) -> str:
        """Serialize the site's search form the way the browser does."""
        fecha = ""
        if fecha_desde:
            fecha = fecha_desde + (f"..{fecha_hasta}" if fecha_hasta else "")
        pairs: list[tuple[str, str]] = [
            ("type1" if tab == TAB_GENERALES else "type2", "on"),
            ("NMCMP_1", "NUM-CONSULTA"),
            ("VLCMP_1", num_consulta or ""),
            ("OPCMP_1", ".Y"),
            ("NMCMP_2", "FECHA-SALIDA"),
            ("VLCMP_2", fecha),
            ("OPCMP_2", ".Y"),
            ("NMCMP_6", "FreeText"),
            ("VLCMP_6", texto or ""),
            ("OPCMP_6", ".Y"),
            ("cmpOrder", "FECHA-SALIDA"),
            ("dirOrder", "1"),
            ("tab", tab),
            ("page", str(page)),
        ]
        return "&".join(f"{k}={quote(v, safe='()')}" for k, v in pairs)

    def _parse_search(self, html: str, page: int) -> DgtSearchPage:
        total = _parse_total(html)
        if _NO_RESULTS_MARKER in html or total == 0:
            return DgtSearchPage(total=0, total_pages=0, page=page, query="", hits=[])
        query_m = _QUERY_RE.search(html)
        pages_m = _TOTAL_PAGES_RE.search(html)
        hits: list[DgtSearchHit] = []
        for row in _ROW_RE.finditer(html):
            doc_id, cell = row.group(1), row.group(2)
            fields = {m.group(1): _strip_tags(m.group(2)) for m in _ROW_FIELD_RE.finditer(cell)}
            hits.append(
                DgtSearchHit(
                    doc_id=doc_id,
                    num_consulta=fields.get("NUM-CONSULTA"),
                    descripcion_hechos=fields.get("DESCRIPCION-HECHOS"),
                    cuestion_planteada=fields.get("CUESTION-PLANTEADA"),
                )
            )
        return DgtSearchPage(
            total=total,
            total_pages=int(pages_m.group(1)) if pages_m else 1,
            page=page,
            query=html_module.unescape(query_m.group(1)) if query_m else "",
            hits=hits,
        )

    async def search(
        self,
        *,
        vinculantes: bool = True,
        num_consulta: str | None = None,
        texto: str | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        page: int = 1,
    ) -> DgtSearchPage:
        """Run the DGT search form. Dates are ``dd/mm/aaaa``.

        ``vinculantes=True`` searches the "Consultas vinculantes" database (V-numbers),
        ``False`` the "Consultas generales" database.
        """
        tab = TAB_VINCULANTES if vinculantes else TAB_GENERALES
        qs = self._build_search_qs(
            tab=tab,
            page=page,
            num_consulta=num_consulta,
            texto=texto,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
        resp = await self._request(f"{self.base_url}/consultas/do/search?{qs}")
        if resp.status_code >= 400:
            raise DgtError(f"HTTP {resp.status_code} from DGT search.")
        return self._parse_search(resp.text, page)

    # ----- document --------------------------------------------------------

    def _parse_document(self, html: str, doc_id: str, num_consulta_hint: str | None) -> DgtRuling:
        fields: dict[str, str] = {}
        for m in _DOC_FIELD_RE.finditer(html):
            fields[m.group(1)] = _strip_tags(m.group(2))
        num = fields.get("NUM-CONSULTA") or num_consulta_hint
        # The site's own shareable permalink form (checkNumConsulta in its JS).
        source_url = f"{self.base_url}/consultas/?num_consulta={quote(num or '')}"
        # The full answer row is classed CONTESTACION-COMPL (truncated class attr upstream).
        contestacion = next(
            (v for k, v in fields.items() if k.startswith("CONTESTACION")), None
        )
        return DgtRuling(
            doc_id=doc_id,
            num_consulta=num,
            organo=fields.get("ORGANO"),
            fecha_salida=fields.get("FECHA-SALIDA"),
            normativa=fields.get("NORMATIVA"),
            descripcion_hechos=fields.get("DESCRIPCION-HECHOS"),
            cuestion_planteada=fields.get("CUESTION-PLANTEADA"),
            contestacion=contestacion,
            source_url=source_url,
        )

    async def get_document(
        self, query: str, doc_id: str, *, vinculantes: bool = True,
        num_consulta_hint: str | None = None,
    ) -> DgtRuling:
        """Fetch one ruling. ``query`` is ``DgtSearchPage.query`` from a search run on
        THIS client instance (the endpoint is session-bound)."""
        tab = TAB_VINCULANTES if vinculantes else TAB_GENERALES
        url = (
            f"{self.base_url}/consultas/do/document"
            f"?query={quote(query, safe='()')}&doc={quote(doc_id)}&tab={tab}"
        )
        resp = await self._request(url)
        if resp.status_code == 401:
            raise DgtError(
                "HTTP 401 from DGT document endpoint - the query/session pair is invalid "
                "(a document must be fetched with the same client session as its search)."
            )
        if resp.status_code >= 400:
            raise DgtError(f"HTTP {resp.status_code} from DGT document endpoint.")
        return self._parse_document(resp.text, doc_id, num_consulta_hint)

    # ----- high-level: one ruling by its official number ---------------------

    async def get_ruling_by_number(self, num_consulta: str) -> DgtRuling:
        """Resolve an official consulta number ("V0001-25" or "0001-03") to the full
        ruling. V-prefixed numbers live in the vinculantes database, the rest in
        generales (the site's own routing rule)."""
        num = num_consulta.strip().upper()
        cache_key = f"dgt-ruling::{num}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return DgtRuling(**cached)

        vinculantes = num.startswith("V")
        page = await self.search(vinculantes=vinculantes, num_consulta=num)
        if page.total == 0 or not page.hits:
            raise DgtNotFoundError(f"No DGT consulta found for number {num!r}.")
        hit = next((h for h in page.hits if (h.num_consulta or "").upper() == num), page.hits[0])
        ruling = await self.get_document(
            page.query, hit.doc_id, vinculantes=vinculantes, num_consulta_hint=num
        )
        self._cache.set(cache_key, ruling.__dict__, ttl=HttpCache.ttl_for("act"))
        return ruling


def parse_total_for_tests(html: str) -> int:
    """Exposed for offline tests."""
    return _parse_total(html)


def strip_tags_for_tests(raw: str) -> str:
    """Exposed for offline tests."""
    return _strip_tags(raw)


__all__ = [
    "DEFAULT_DGT_BASE_URL",
    "DgtClient",
    "DgtError",
    "DgtNotFoundError",
    "DgtRuling",
    "DgtSearchHit",
    "DgtSearchPage",
]
