"""Offline tests for the Tribunal Constitucional HTML parser - no network calls.

Uses saved fixtures (real pages fetched during discovery, 2026-07-07) and monkeypatches
``TcClient._request`` to serve them, so parsing logic is exercised without hitting
hj.tribunalconstitucional.es.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from es_eli_mcp.cache import HttpCache
from es_eli_mcp.citations import tc_human_citation, tc_tipo_from_title
from es_eli_mcp.tc_client import TcClient, TcNotFoundError

FIXTURES = Path(__file__).parent / "fixtures"


def _fake_response(html: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=html, request=httpx.Request("GET", "https://example.test"))


@pytest.mark.asyncio
async def test_parses_real_resolution_page(tmp_path: Path) -> None:
    html = (FIXTURES / "tc_resolution_25015.html").read_text(encoding="utf-8")

    async with TcClient(cache=HttpCache(cache_dir=tmp_path)) as client:
        async def fake_request(method: str, url: str, **kwargs: object) -> httpx.Response:
            return _fake_response(html)

        client._request = fake_request  # type: ignore[method-assign]
        res = await client.get_resolution("25015")

    assert res.title == "SENTENCIA 117/2016, de 20 de junio"
    assert res.ecli == "ECLI:ES:TC:2016:117"
    assert res.sala == "Sala Segunda"
    assert res.encabezamiento is not None and "amparo" in res.encabezamiento
    assert res.fallo is not None and "presunción de inocencia" in res.fallo
    assert res.source_url.endswith("/es/Resolucion/Show/25015")


@pytest.mark.asyncio
async def test_not_found_redirect_raises(tmp_path: Path) -> None:
    html = (FIXTURES / "tc_notfound.html").read_text(encoding="utf-8")

    async with TcClient(cache=HttpCache(cache_dir=tmp_path)) as client:
        async def fake_request(method: str, url: str, **kwargs: object) -> httpx.Response:
            return _fake_response(html)

        client._request = fake_request  # type: ignore[method-assign]
        with pytest.raises(TcNotFoundError):
            await client.get_resolution("999999")


def test_tc_human_citation_sentencia() -> None:
    assert tc_human_citation("SENTENCIA 31/2010, de 28 de junio") == "STC 31/2010, de 28 de junio"


def test_tc_human_citation_auto() -> None:
    assert tc_human_citation("AUTO 15/2020, de 3 de febrero") == "ATC 15/2020, de 3 de febrero"


def test_tc_human_citation_none() -> None:
    assert tc_human_citation(None) is None


def test_tc_human_citation_unrecognized_passthrough() -> None:
    assert tc_human_citation("Something else") == "Something else"


def test_tc_tipo_from_title() -> None:
    assert tc_tipo_from_title("SENTENCIA 31/2010, de 28 de junio") == "SENTENCIA"
    assert tc_tipo_from_title("AUTO 15/2020, de 3 de febrero") == "AUTO"
    assert tc_tipo_from_title(None) is None
    assert tc_tipo_from_title("gibberish") is None
