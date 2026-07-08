"""Offline tests for the DGT (petete) HTML parsers - no network calls.

Uses saved fixtures (real fragments fetched during discovery, 2026-07-08) and
monkeypatches ``DgtClient._request`` to serve them.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from es_eli_mcp.cache import HttpCache
from es_eli_mcp.citations import dgt_human_citation, spanish_date
from es_eli_mcp.dgt_client import DgtClient, DgtNotFoundError

FIXTURES = Path(__file__).parent / "fixtures"


def _fake_response(html: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=html, request=httpx.Request("GET", "https://example.test"))


@pytest.mark.asyncio
async def test_parses_search_fragment(tmp_path: Path) -> None:
    html = (FIXTURES / "dgt_search_v0001_25.html").read_text(encoding="utf-8")

    async with DgtClient(cache=HttpCache(cache_dir=tmp_path)) as client:
        async def fake_request(url: str) -> httpx.Response:
            return _fake_response(html)

        client._request = fake_request  # type: ignore[method-assign]
        page = await client.search(vinculantes=True, num_consulta="V0001-25")

    assert page.total == 1
    assert page.query == " .EN NUM-CONSULTA (V0001-25)"
    assert len(page.hits) == 1
    hit = page.hits[0]
    assert hit.doc_id == "71136"
    assert hit.num_consulta == "V0001-25"
    assert hit.descripcion_hechos is not None and "fotovoltaicas" in hit.descripcion_hechos


@pytest.mark.asyncio
async def test_parses_document_fragment(tmp_path: Path) -> None:
    html = (FIXTURES / "dgt_document_71136.html").read_text(encoding="utf-8")

    async with DgtClient(cache=HttpCache(cache_dir=tmp_path)) as client:
        async def fake_request(url: str) -> httpx.Response:
            return _fake_response(html)

        client._request = fake_request  # type: ignore[method-assign]
        ruling = await client.get_document(" .EN NUM-CONSULTA (V0001-25)", "71136")

    assert ruling.num_consulta == "V0001-25"
    assert ruling.organo is not None and "Renta de las Personas" in ruling.organo
    assert ruling.fecha_salida == "02/01/2025"
    assert ruling.normativa is not None and "35/2006" in ruling.normativa
    assert ruling.contestacion is not None and len(ruling.contestacion) > 5000
    assert ruling.source_url.endswith("num_consulta=V0001-25")


@pytest.mark.asyncio
async def test_ruling_by_number_not_found(tmp_path: Path) -> None:
    empty = '<div><script>noResults()</script>updateNumResults("2", "0");</div>'

    async with DgtClient(cache=HttpCache(cache_dir=tmp_path)) as client:
        async def fake_request(url: str) -> httpx.Response:
            return _fake_response(empty)

        client._request = fake_request  # type: ignore[method-assign]
        with pytest.raises(DgtNotFoundError):
            await client.get_ruling_by_number("V9999-99")


def test_spanish_date() -> None:
    assert spanish_date("02/01/2025") == "2 de enero de 2025"
    assert spanish_date("2026-04-28") == "28 de abril de 2026"
    assert spanish_date("24/06/2026") == "24 de junio de 2026"
    assert spanish_date(None) is None
    assert spanish_date("gibberish") is None


def test_dgt_human_citation_vinculante() -> None:
    assert dgt_human_citation("V0001-25", "02/01/2025") == (
        "Consulta Vinculante V0001-25, de 2 de enero de 2025, "
        "de la Dirección General de Tributos"
    )


def test_dgt_human_citation_general() -> None:
    citation = dgt_human_citation("0001-03", None)
    assert citation == "Consulta General 0001-03, de la Dirección General de Tributos"


def test_dgt_human_citation_none() -> None:
    assert dgt_human_citation(None, "02/01/2025") is None
