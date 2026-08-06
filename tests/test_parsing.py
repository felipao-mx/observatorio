"""Parser tests. No network, no cassettes -- these are pure functions.

Most of the real complexity lives here rather than in the HTTP layer, so these
are the tests that actually protect against regressions.
"""

from __future__ import annotations

import pytest

from observatorio.client import (
    IncompleteDataError,
    StatusClient,
    _ajax_fragment,
    _attr,
    _cell_text,
    _parse_rows,
)


def _row(
    icon: str,
    estado: str = "Servicio Regular",
    estaciones: str = "Ninguna",
    extra: str = "",
    data_ri: int = 0,
) -> str:
    return (
        f'<tr data-ri="{data_ri}" class="ui-widget-content">'
        f'<td><img src="/jakarta.faces.resource/img/iconos/{icon}.xhtml?v=eb689f0"/></td>'
        f'<td colspan="2">{estado}</td>'
        f'<td colspan="2">{estaciones}</td>'
        f'<td colspan="2">{extra}</td>'
        f"</tr>"
    )


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        pass


class _HttpClient:
    def __init__(self, text: str) -> None:
        self.text = text

    async def get(self, url: str) -> _Response:
        return _Response(self.text)


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


def test_short_rows_have_empty_cell_text():
    assert _cell_text([], 0) == ""


def test_missing_attribute_tag_is_empty():
    assert _attr(None, "src") == ""


def test_list_attributes_are_narrowed_to_strings():
    class Tag:
        def __init__(self, value: list[str]) -> None:
            self.value = value

        def get(self, name: str) -> list[str]:
            return self.value

    assert _attr(Tag(["first", "second"]), "class") == "first"
    assert _attr(Tag([]), "class") == ""


def test_short_table_rows_are_skipped():
    markup = '<tr data-ri="0"><td>line</td><td>status</td></tr>'
    assert _parse_rows(markup, "stc") == []


def test_unknown_icon_keeps_line_empty():
    row = _parse_rows(_row("misterio/desconocido.svg"), "stc")[0]
    assert row["linea"] is None


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


@pytest.mark.asyncio
async def test_missing_ajax_fragment_raises_incomplete_data(monkeypatch):
    rows = "".join(_row("lineas/stc1.svg", data_ri=i) for i in range(10))
    page = (
        "<html><body>"
        '<input name="jakarta.faces.ViewState" value="view-state">'
        "<script>PrimeFaces.cw('DataTable','widget',{paginator:{rows:10,rowCount:12,page:0}});"
        "</script>"
        f"<table>{rows}</table>"
        "</body></html>"
    )
    client = StatusClient()
    monkeypatch.setattr(client, "_client_for", lambda system: _HttpClient(page))

    async def paginate(system: str, url: str, viewstate: str, first: int) -> str:
        return "<not xml"

    monkeypatch.setattr(client, "_paginate", paginate)

    with pytest.raises(IncompleteDataError, match="got 10 rows but the server declared 12"):
        await client.fetch("stc")
