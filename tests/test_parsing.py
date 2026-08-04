"""Parser tests. No network, no cassettes -- these are pure functions.

Most of the real complexity lives here rather than in the HTTP layer, so these
are the tests that actually protect against regressions.
"""

from __future__ import annotations

from observatorio.client import _ajax_fragment, _parse_rows


def _row(
    icon: str, estado: str = "Servicio Regular", estaciones: str = "Ninguna", extra: str = ""
) -> str:
    return (
        f'<tr data-ri="0" class="ui-widget-content">'
        f'<td><img src="/jakarta.faces.resource/img/iconos/{icon}.xhtml?v=eb689f0"/></td>'
        f'<td colspan="2">{estado}</td>'
        f'<td colspan="2">{estaciones}</td>'
        f'<td colspan="2">{extra}</td>'
        f"</tr>"
    )


def test_orphan_tr_fragments_survive_parsing():
    """The pagination response has no enclosing <table>.

    This is why the BeautifulSoup backend is pinned to html.parser: lxml and
    html5lib apply table-context fixup and discard orphan rows, which would
    silently drop every paginated line.
    """
    rows = _parse_rows(_row("lineas/stca.svg"), "stc")
    assert len(rows) == 1


def test_letter_lines_are_parsed():
    """Metro's Líneas A and B are letters, not digits, and live on page 2."""
    assert _parse_rows(_row("lineas/stca.svg"), "stc")[0]["linea"] == "A"
    assert _parse_rows(_row("lineas/stcb.svg"), "stc")[0]["linea"] == "B"


def test_numeric_and_multidigit_lines():
    assert _parse_rows(_row("lineas/stc1.svg"), "stc")[0]["linea"] == "1"
    assert _parse_rows(_row("lineas/stc12.svg"), "stc")[0]["linea"] == "12"
    assert _parse_rows(_row("lineas/MB3.png"), "mb")[0]["linea"] == "3"
    assert _parse_rows(_row("lineas/CB2.png"), "cb")[0]["linea"] == "2"


def test_unnumbered_row_falls_back_to_system_icon():
    """STE rows with no line icon are the unnumbered services."""
    row = _parse_rows(_row("transportes/ste.png"), "ste")[0]
    assert row["linea"] == "Tren Ligero"


def test_normal_flag_tracks_servicio_regular():
    assert _parse_rows(_row("lineas/stc1.svg"), "stc")[0]["normal"] is True
    incident = _row(
        "lineas/stc1.svg", estado="Avance lento por lluvia", estaciones="Línea Completa"
    )
    parsed = _parse_rows(incident, "stc")[0]
    assert parsed["normal"] is False
    assert parsed["estado"] == "Avance lento por lluvia"
    assert parsed["estaciones_afectadas"] == "Línea Completa"


def test_text_cells_are_collapsed():
    row = _row("lineas/stc1.svg", estado="  Retraso   en\n el servicio  ")
    assert _parse_rows(row, "stc")[0]["estado"] == "Retraso en el servicio"


def test_ajax_fragment_extracts_table_update():
    xml = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<partial-response><changes>"
        '<update id="messages"><![CDATA[<div/>]]></update>'
        '<update id="frmEstadoServicio:tblEstadoServicio"><![CDATA[<tr data-ri="0"/>]]></update>'
        "</changes></partial-response>"
    )
    assert _ajax_fragment(xml) == '<tr data-ri="0"/>'


def test_ajax_fragment_returns_none_on_viewroot_rerender():
    """An expired ViewState makes JSF re-render the whole page instead."""
    xml = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<partial-response><changes>"
        '<update id="jakarta.faces.ViewRoot"><![CDATA[<html/>]]></update>'
        "</changes></partial-response>"
    )
    assert _ajax_fragment(xml) is None


def test_ajax_fragment_survives_malformed_xml():
    assert _ajax_fragment("not xml at all") is None
