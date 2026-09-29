"""PDF'de göster: konumlar deterministik; kodlar yalnızca birebir yazımıyla, verilen kaynak alan içinde işaretlenir."""
import pytest

import grid_compare as gc
from pdf_locate import Locator, code_check_refs, code_pattern, page_list, page_words

from conftest import SAMPLES

PDF = SAMPLES / "arnavutca.pdf"
XL = SAMPLES / "system-example.xlsx"


def test_code_pattern_is_exact():
    p = code_pattern("D1")
    assert p.match("D1") and p.match("(D1,") and p.match("D1.")
    assert not p.match("D10") and not p.match("D1.1") and not p.match("D1.1).")
    assert code_pattern("E1.1").match("E1.1.Merak")  # bitişik standart dışı tanım yazımı
    assert not code_pattern("ARN.5.1.D").match("ARN.5.1.DBS")
    assert page_list("27-29") == [27, 28, 29] and page_list("31, 32") == [31, 32]


@pytest.fixture(scope="module")
def loc():
    if not (PDF.exists() and XL.exists()):
        pytest.skip("örnek dosyalar yok")
    from excel_import import read_system_excel
    from pdf_extract import extract_spans
    from validators import analyze_pdf

    res = analyze_pdf(str(PDF))
    return res, Locator(res, extract_spans(res.source)), read_system_excel(str(XL))


def _marked_words(L, loc):
    return [w[4] for p, rs in loc.rects.items() for w in page_words(L.path, p) for r in rs if (w[0], w[1], w[2], w[3]) == r]


def test_declared_and_used_codes(loc):
    res, L, _ = loc
    u = res.units[0]
    d = L.declared_code_loc(u, "D3", "PROGRAMLAR ARASI BİLEŞENLER > Değerler")
    assert d.found and set(d.rects) == {27} and _marked_words(L, d) == ["D3."]
    used = L.used_code_loc(u, "E1.1")
    assert used.found and all(code_pattern("E1.1").match(w) for w in _marked_words(L, used))
    # yalnızca bu birimin sayfalarında
    assert set(used.rects) <= set(u.pages)


def test_code_check_rows_and_findings_have_locations(loc):
    res, L, _ = loc
    refs = code_check_refs(res)
    assert len(refs) == sum(len(r.code_checks) for r in res.unit_reports) + sum(
        1 for r in res.unit_reports if set(r.used_not_declared) - {x for c in r.code_checks for x in c.used_not_declared}
    )
    unit_id, cat = refs[0]
    items = L.code_check_cell(unit_id, cat, "Tanımlanan", "E1.1, E1.4")
    assert [c for c, _ in items] == ["E1.1", "E1.4"] and all(x.found for _, x in items)
    assert all(L.finding_loc(f).found for f in res.findings if f.details.get("spans") or f.details.get("label_spans"))


def test_merged_theme_cells_show_each_error_once(loc):
    """Dikey görünüm: çıktılar + bileşenler tek hücrede, kod sütunu temada tek liste; OB5 ad farkı bir kez."""
    res, L, xl = loc
    import grid_tab

    grid = gc.build_grid(res, xl)
    m = gc.merged_theme_cells(grid)[0]
    lo = m[gc.MERGED_LO_HEADER]
    lids = {r.lo_id for r in grid.rows if r.theme_id == 0 and r.lo_id is not None}
    assert all(grid.lo_cells[l]["Öğrenme Çıktısı"].pdf.strip() in lo.pdf for l in lids)
    ob = m["Okuryazarlık Becerileri"]
    assert ob.status == gc.FARKLI and ob.sys.count("OB5") == 1 and ob.note.count("OB5") == 1
    per_lo = [grid.lo_cells[l]["Okuryazarlık Becerileri"] for l in lids]
    assert sum(c.status == gc.FARKLI for c in per_lo) > 1  # yan yana satırlarda tekrar ediyordu
    # kaynak hücreler değişmez; birleşik hücrenin PDF konumu parçalarından
    assert grid_tab.cell_loc(L, grid, gc.cell_key("M0", "Okuryazarlık Becerileri")).found


def test_grid_code_column_marks_only_block_codes(loc):
    res, L, xl = loc
    import grid_tab

    grid = gc.build_grid(res, xl)
    key = next(gc.cell_key(f"L{l}", h) for l, cs in grid.lo_cells.items() for h, c in cs.items() if h.startswith("Erdem") and c.pdf_codes)
    c = gc.cell_by_key(grid, key)
    got = grid_tab.cell_loc(L, grid, key)
    assert got.found
    for w in _marked_words(L, got):
        assert any(code_pattern(x).match(w) for x in c.pdf_codes)
