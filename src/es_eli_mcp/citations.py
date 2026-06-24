"""Spanish BOE citation helpers.

BOE metadata is already flat-ish. ELI is exposed as a full URL in ``url_eli``, and the
``titulo`` field is the canonical Spanish citation (e.g. "Ley Organica 3/2018, de 5 de
diciembre, de Proteccion de Datos Personales...").

Citation contract:
- ``eli_uri``: ``url_eli`` (e.g. ``https://www.boe.es/eli/es/lo/2018/12/05/3``).
- ``human_readable_citation``: ``titulo`` (trailing period trimmed).
- ``source_url``: ``url_html_consolidada`` (the openable consolidated-text page) or ``url_eli``.
"""

from __future__ import annotations

from typing import Any


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _nested_text(value: Any) -> str | None:
    """A few BOE fields are {codigo, texto}; return the texto."""
    if isinstance(value, dict):
        return _text(value.get("texto"))
    return _text(value)


def enrich_metadata(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten a BOE metadatos record into a contract-bearing dict."""
    titulo = _text(item.get("titulo"))
    citation = titulo.rstrip(".") if titulo else None
    eli = _text(item.get("url_eli"))
    source = _text(item.get("url_html_consolidada")) or eli
    out: dict[str, Any] = {
        "id": _text(item.get("identificador")),
        "titulo": titulo,
        "rango": _nested_text(item.get("rango")),
        "departamento": _nested_text(item.get("departamento")),
        "numero_oficial": _text(item.get("numero_oficial")),
        "fecha_publicacion": _text(item.get("fecha_publicacion")),
        "fecha_disposicion": _text(item.get("fecha_disposicion")),
        "estado_consolidacion": _nested_text(item.get("estado_consolidacion")),
    }
    if eli:
        out["eli_uri"] = eli
    if citation:
        out["human_readable_citation"] = citation
    if source:
        out["source_url"] = source
    return out


def extract_gazette_items(sumario: Any) -> list[dict[str, str]]:
    """Walk a BOE sumario tree and collect document items {id, titulo}.

    The sumario nests diario -> seccion -> departamento -> epigrafe -> item; each ``item``
    carries an ``identificador`` and a ``titulo``.
    """
    found: list[dict[str, str]] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            ident = node.get("identificador")
            titulo = node.get("titulo")
            if isinstance(ident, str) and ident and ident not in seen:
                seen.add(ident)
                entry = {"id": ident}
                if isinstance(titulo, str) and titulo.strip():
                    entry["titulo"] = titulo.strip()
                found.append(entry)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(sumario)
    return found
