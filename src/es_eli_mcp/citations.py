"""Spanish citation helpers - BOE consolidated legislation + Tribunal Constitucional rulings.

BOE metadata is already flat-ish. ELI is exposed as a full URL in ``url_eli``, and the
``titulo`` field is the canonical Spanish citation (e.g. "Ley Organica 3/2018, de 5 de
diciembre, de Proteccion de Datos Personales...").

Citation contract (BOE):
- ``eli_uri``: ``url_eli`` (e.g. ``https://www.boe.es/eli/es/lo/2018/12/05/3``).
- ``human_readable_citation``: ``titulo`` (trailing period trimmed).
- ``source_url``: ``url_html_consolidada`` (the openable consolidated-text page) or ``url_eli``.

Citation contract (Tribunal Constitucional): TC rulings carry no ELI (ELI covers Spanish
legislation, not TC case law) - ``ecli`` (e.g. ``ECLI:ES:TC:2016:117``) is the identifier,
and ``human_readable_citation`` follows the Spanish doctrinal convention
"STC 117/2016, de 20 de junio" (see ``tc_human_citation``).
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Tribunal Constitucional (hj.tribunalconstitucional.es) citation helpers
# ---------------------------------------------------------------------------
#
# Spanish citation convention: "STC 31/2010, de 28 de junio" for a Sentencia,
# "ATC 15/2020, de 3 de febrero" for an Auto. The page title already carries
# "SENTENCIA 31/2010, de 28 de junio"; we just map the type word to its
# abbreviation (STC/ATC/DTC) to match how Spanish courts/doctrine cite it.

_TIPO_ABBREV = {
    "SENTENCIA": "STC",
    "AUTO": "ATC",
    "DECLARACION": "DTC",
    "DECLARACIÓN": "DTC",
}

_TITLE_HEAD_RE = re.compile(r"^(SENTENCIA|AUTO|DECLARACI[OÓ]N)\s+(.*)$", re.IGNORECASE)


def tc_human_citation(title: str | None) -> str | None:
    """Convert a Sistema HJ page title ("SENTENCIA 31/2010, de 28 de junio") into the
    standard Spanish doctrinal citation ("STC 31/2010, de 28 de junio")."""
    if not title:
        return None
    m = _TITLE_HEAD_RE.match(title.strip())
    if not m:
        return title.strip()
    tipo_word, rest = m.group(1).upper(), m.group(2).strip()
    abbrev = _TIPO_ABBREV.get(tipo_word, tipo_word)
    return f"{abbrev} {rest}"


def tc_tipo_from_title(title: str | None) -> str | None:
    """Extract the resolution type word ("SENTENCIA" | "AUTO" | "DECLARACION") from a
    Sistema HJ page title, e.g. "SENTENCIA 31/2010, de 28 de junio" -> "SENTENCIA"."""
    if not title:
        return None
    m = _TITLE_HEAD_RE.match(title.strip())
    return m.group(1).upper() if m else None


# ---------------------------------------------------------------------------
# DGT / TEAC / AEPD citation helpers (feature-003)
# ---------------------------------------------------------------------------

_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

_DDMMYYYY_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def spanish_date(value: str | None) -> str | None:
    """Render ``dd/mm/aaaa`` or ISO ``aaaa-mm-dd`` as "d de <mes> de aaaa"."""
    if not value:
        return None
    m = _DDMMYYYY_RE.match(value.strip())
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
    else:
        m = _ISO_DATE_RE.match(value.strip())
        if not m:
            return None
        year, month, day = m.group(1), int(m.group(2)), int(m.group(3))
    if not 1 <= month <= 12:
        return None
    return f"{day} de {_MESES[month - 1]} de {year}"


def dgt_human_citation(num_consulta: str | None, fecha_salida: str | None) -> str | None:
    """Spanish doctrinal convention for DGT rulings: "Consulta Vinculante V0001-25, de
    2 de enero de 2025, de la Direccion General de Tributos" (V-numbers are vinculantes,
    the rest generales)."""
    if not num_consulta:
        return None
    kind = "Consulta Vinculante" if num_consulta.upper().startswith("V") else "Consulta General"
    parts = [f"{kind} {num_consulta}"]
    date_es = spanish_date(fecha_salida)
    if date_es:
        parts.append(f"de {date_es}")
    parts.append("de la Dirección General de Tributos")
    return ", ".join(parts)


def teac_human_citation(
    rg: str | None, fecha_resolucion: str | None, unidad: str | None
) -> str | None:
    """Spanish convention for TEAC doctrine: "Resolución del TEAC de 24 de junio de
    2026, RG 00/07082/2025"."""
    if not rg and not fecha_resolucion:
        return None
    tribunal = unidad or "TEAC"
    date_es = spanish_date(fecha_resolucion)
    out = f"Resolución del {tribunal}"
    if date_es:
        out += f" de {date_es}"
    if rg:
        out += f", RG {rg}"
    return out


def aepd_human_citation(expediente: str | None, fecha_firma: str | None) -> str | None:
    """Convention for AEPD resolutions: "Resolución de la AEPD en el procedimiento
    PS-00615-2025, de <fecha de firma>"."""
    if not expediente:
        return None
    out = f"Resolución de la AEPD en el procedimiento {expediente}"
    date_es = spanish_date(fecha_firma)
    if date_es:
        out += f", de {date_es}"
    return out


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
