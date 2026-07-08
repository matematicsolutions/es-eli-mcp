"""Async httpx client for DYCTEA - Doctrina y Criterios de los Tribunales
Economico-Administrativos (``serviciostelematicosext.hacienda.gob.es/TEAC/DYCTEA``).

The application is ASP.NET WebForms, but its results page accepts plain GET query
parameters (the same ones its own result links carry), so no VIEWSTATE round-trip is
needed:

- ``GET /TEAC/DYCTEA/Criterios.aspx?rs=&rn=&ra=&fd=&fh=&pg=`` - search. ``rs``/``rn``/
  ``ra`` are the three segments of the RG claim number (sede/numero/anno), ``fd``/``fh``
  a resolution-date range (``dd/mm/aaaa``), ``pg`` the page. The dedicated total field
  is "Se han obtenido N resultados".
- ``GET /TEAC/DYCTEA/criterio.aspx?id=SS/NNNNN/AAAA/RR/S/C`` - one criterio permalink
  with the criterio text AND the full resolution text inline. A wrong id renders
  "El criterio no existe.".

Verified live 2026-07-08: ``rs``/``rn``/``ra``/``fd``/``fh`` narrow the result set;
the free-text-looking parameters (``c``, ``c1``, ``tf``, ...) are accepted but DO NOT
filter (silent no-ops), so this client deliberately does not expose them. Total at
check: 6 502 criterios. Keyless, no CAPTCHA; Spanish PSI open data.
"""

from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass, field

import anyio
import httpx

from .cache import HttpCache

DEFAULT_TEAC_BASE_URL = "https://serviciostelematicosext.hacienda.gob.es/TEAC/DYCTEA"
DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
USER_AGENT = "es-eli-mcp/0.3.0 (+https://github.com/matematicsolutions/es-eli-mcp)"

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3

_NOT_FOUND_MARKER = "El criterio no existe."
_TOTAL_RE = re.compile(r"Se han obtenido ([\d.,]+) resultados")
_ITEM_RE = re.compile(
    r"<a href='criterio\.aspx\?id=([^&']*)[^']*'>\s*(.*?)\s*</a>.*?"
    r"<span class='resultadoCriterioTexto'>\s*(.*?)\s*</span>",
    re.DOTALL,
)
_DATO_RE = re.compile(
    r"criterioDatos(\w+)' class='criterioDatosFila'>\s*(.*?)\s*</div>", re.DOTALL
)
_RESOLUCION_RE = re.compile(
    r"criterioDatosResolucion'[^>]*>\s*<span class='criterioNegrita'>"
    r"Texto de la resoluci(?:ón|&oacute;n):\s*</span>(.*?)<div class='containerBack'>",
    re.DOTALL,
)
_CRITERIO_ID_RE = re.compile(r"^\d{2}/\d{1,5}/\d{4}/\d{2}/\d{1,2}/\d{1,2}$")


class TeacError(Exception):
    """Raised on an upstream DYCTEA HTTP/parse error."""


class TeacNotFoundError(TeacError):
    """Raised when a criterio id does not resolve to a real record."""


def _strip_tags(raw_html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", raw_html)
    text = re.sub(r"</p>\s*", "\n", text)
    text = re.sub(r"</li>\s*", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_module.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _parse_total(html: str) -> int:
    m = _TOTAL_RE.search(html)
    if not m:
        return 0
    return int(m.group(1).replace(".", "").replace(",", ""))


def is_valid_criterio_id(criterio_id: str) -> bool:
    """DYCTEA criterio ids look like ``00/07082/2025/00/0/1``."""
    return bool(_CRITERIO_ID_RE.match(criterio_id.strip()))


@dataclass
class TeacSearchHit:
    """One row of a DYCTEA results page."""

    criterio_id: str  # e.g. "00/07082/2025/00/0/1"
    title: str | None = None  # "Criterio 1 de la resolución 00/07082/2025/00/00 del ..."
    snippet: str | None = None


@dataclass
class TeacSearchPage:
    """A parsed DYCTEA results page."""

    total: int
    page: int
    hits: list[TeacSearchHit] = field(default_factory=list)


@dataclass
class TeacCriterio:
    """A parsed DYCTEA criterio permalink page."""

    criterio_id: str
    rg: str | None  # claim number, e.g. "00/07082/2025/00/00"
    calificacion: str | None  # e.g. "Doctrina"
    unidad_resolutoria: str | None  # e.g. "TEAC"
    fecha_resolucion: str | None  # dd/mm/aaaa
    asunto: str | None
    criterio: str | None
    referencias_normativas: str | None
    texto_resolucion: str | None
    source_url: str


class TeacClient:
    """Async client. Use as ``async with TeacClient() as c: ...``."""

    def __init__(
        self,
        base_url: str = DEFAULT_TEAC_BASE_URL,
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

    async def __aenter__(self) -> TeacClient:
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

    def _parse_search(self, html: str, page: int) -> TeacSearchPage:
        total = _parse_total(html)
        hits: list[TeacSearchHit] = []
        for m in _ITEM_RE.finditer(html):
            hits.append(
                TeacSearchHit(
                    criterio_id=html_module.unescape(m.group(1)),
                    title=_strip_tags(m.group(2)) or None,
                    snippet=_strip_tags(m.group(3)) or None,
                )
            )
        return TeacSearchPage(total=total, page=page, hits=hits)

    async def search(
        self,
        *,
        sede: str | None = None,
        numero: str | None = None,
        anno: str | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        page: int = 1,
    ) -> TeacSearchPage:
        """Search DYCTEA criterios by RG segments and/or resolution-date range.

        ``sede``/``numero``/``anno`` are the segments of the RG claim number (e.g.
        ``"00"``, ``"07082"``, ``"2025"`` for RG 00/07082/2025). Dates are dd/mm/aaaa.
        """
        params: list[str] = ["s=1"]
        if sede:
            params.append(f"rs={sede.strip()}")
        if numero:
            params.append(f"rn={numero.strip()}")
        if anno:
            params.append(f"ra={anno.strip()}")
        if fecha_desde:
            params.append(f"fd={fecha_desde.strip()}")
        if fecha_hasta:
            params.append(f"fh={fecha_hasta.strip()}")
        if page > 1:
            params.append(f"pg={page}")
        url = f"{self.base_url}/Criterios.aspx?{'&'.join(params)}"
        cache_key = "teac-search::" + url
        cached = self._cache.get(cache_key)
        if cached is not None:
            return TeacSearchPage(
                total=cached["total"],
                page=cached["page"],
                hits=[TeacSearchHit(**h) for h in cached["hits"]],
            )
        resp = await self._request(url)
        if resp.status_code >= 400:
            raise TeacError(f"HTTP {resp.status_code} from DYCTEA search.")
        result = self._parse_search(resp.text, page)
        self._cache.set(
            cache_key,
            {"total": result.total, "page": result.page, "hits": [h.__dict__ for h in result.hits]},
            ttl=HttpCache.ttl_for("search"),
        )
        return result

    # ----- criterio permalink ------------------------------------------------

    def _parse_criterio(self, html: str, criterio_id: str, url: str) -> TeacCriterio:
        if _NOT_FOUND_MARKER in html:
            raise TeacNotFoundError(f"No DYCTEA criterio found for id {criterio_id!r}.")
        datos: dict[str, str] = {}
        for m in _DATO_RE.finditer(html):
            datos[m.group(1)] = _strip_tags(m.group(2))
        res_m = _RESOLUCION_RE.search(html)

        def _after_colon(value: str | None) -> str | None:
            if value and ":" in value:
                return value.split(":", 1)[1].strip() or None
            return value

        rg_m = re.search(r"de la resolución: (\S+)", datos.get("Titulo", ""))
        return TeacCriterio(
            criterio_id=criterio_id,
            rg=rg_m.group(1) if rg_m else None,
            calificacion=_after_colon(datos.get("Calificacion")),
            unidad_resolutoria=_after_colon(datos.get("Unidad")),
            fecha_resolucion=_after_colon(datos.get("Fecha")),
            asunto=_after_colon(datos.get("Asunto")),
            criterio=_after_colon(datos.get("Contenido")),
            referencias_normativas=_after_colon(datos.get("Normas")),
            texto_resolucion=_strip_tags(res_m.group(1)) if res_m else None,
            source_url=url,
        )

    async def get_criterio(self, criterio_id: str) -> TeacCriterio:
        """Fetch one criterio (with the full resolution text) by its DYCTEA id,
        e.g. ``"00/07082/2025/00/0/1"``."""
        cid = criterio_id.strip()
        url = f"{self.base_url}/criterio.aspx?id={cid}"
        cache_key = "teac-criterio::" + url
        cached = self._cache.get(cache_key)
        if cached is not None:
            return TeacCriterio(**cached)
        resp = await self._request(url)
        if resp.status_code >= 400:
            raise TeacError(f"HTTP {resp.status_code} fetching {url}")
        criterio = self._parse_criterio(resp.text, cid, url)
        self._cache.set(cache_key, criterio.__dict__, ttl=HttpCache.ttl_for("act"))
        return criterio


__all__ = [
    "DEFAULT_TEAC_BASE_URL",
    "TeacClient",
    "TeacCriterio",
    "TeacError",
    "TeacNotFoundError",
    "TeacSearchHit",
    "TeacSearchPage",
    "is_valid_criterio_id",
]
