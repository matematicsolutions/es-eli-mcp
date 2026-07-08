"""Offline tests for the TEAC (DYCTEA) HTML parsers - no network calls.

Uses saved fixtures (real pages fetched during discovery, 2026-07-08) and
monkeypatches ``TeacClient._request`` to serve them.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from es_eli_mcp.cache import HttpCache
from es_eli_mcp.citations import teac_human_citation
from es_eli_mcp.teac_client import TeacClient, TeacNotFoundError, is_valid_criterio_id

FIXTURES = Path(__file__).parent / "fixtures"


def _fake_response(html: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=html, request=httpx.Request("GET", "https://example.test"))


@pytest.mark.asyncio
async def test_parses_search_page(tmp_path: Path) -> None:
    html = (FIXTURES / "teac_search_07082_2025.html").read_text(encoding="utf-8")

    async with TeacClient(cache=HttpCache(cache_dir=tmp_path)) as client:
        async def fake_request(url: str) -> httpx.Response:
            return _fake_response(html)

        client._request = fake_request  # type: ignore[method-assign]
        page = await client.search(sede="00", numero="07082", anno="2025")

    assert page.total == 1
    assert len(page.hits) == 1
    hit = page.hits[0]
    assert hit.criterio_id == "00/07082/2025/00/0/1"
    assert hit.title is not None and "00/07082/2025" in hit.title
    assert hit.snippet is not None and "IRPF" in hit.snippet


@pytest.mark.asyncio
async def test_parses_criterio_page(tmp_path: Path) -> None:
    html = (FIXTURES / "teac_criterio_07082.html").read_text(encoding="utf-8")

    async with TeacClient(cache=HttpCache(cache_dir=tmp_path)) as client:
        async def fake_request(url: str) -> httpx.Response:
            return _fake_response(html)

        client._request = fake_request  # type: ignore[method-assign]
        criterio = await client.get_criterio("00/07082/2025/00/0/1")

    assert criterio.rg == "00/07082/2025/00/00"
    assert criterio.calificacion == "Doctrina"
    assert criterio.unidad_resolutoria == "TEAC"
    assert criterio.fecha_resolucion == "24/06/2026"
    assert criterio.asunto is not None and "IRPF" in criterio.asunto
    assert criterio.criterio is not None and "primas de seguros" in criterio.criterio
    normas = criterio.referencias_normativas
    assert normas is not None and "35/2006" in normas
    assert criterio.texto_resolucion is not None and len(criterio.texto_resolucion) > 5000
    assert criterio.source_url.endswith("criterio.aspx?id=00/07082/2025/00/0/1")


@pytest.mark.asyncio
async def test_criterio_not_found(tmp_path: Path) -> None:
    html = (FIXTURES / "teac_criterio_notfound.html").read_text(encoding="utf-8")

    async with TeacClient(cache=HttpCache(cache_dir=tmp_path)) as client:
        async def fake_request(url: str) -> httpx.Response:
            return _fake_response(html)

        client._request = fake_request  # type: ignore[method-assign]
        with pytest.raises(TeacNotFoundError):
            await client.get_criterio("99/99999/2099/99/9/9")


def test_is_valid_criterio_id() -> None:
    assert is_valid_criterio_id("00/07082/2025/00/0/1")
    assert is_valid_criterio_id("99/99999/2099/99/9/9")
    assert not is_valid_criterio_id("00/07082/2025")
    assert not is_valid_criterio_id("gibberish")
    assert not is_valid_criterio_id("")


def test_teac_human_citation() -> None:
    assert teac_human_citation("00/07082/2025/00/00", "24/06/2026", "TEAC") == (
        "Resolución del TEAC de 24 de junio de 2026, RG 00/07082/2025/00/00"
    )
    assert teac_human_citation(None, None, None) is None
