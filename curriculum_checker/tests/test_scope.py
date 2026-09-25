"""Karşılaştırma kapsamı (sınıf sınıf indirilen sistem Excel'leri) ve çoklu Excel birleştirme testleri.
Örnek sistem Excel'i Arnavutça 5. sınıfın 4 temasını içerir; PDF 5-8. sınıfların 16 temasını içerir."""
import copy

import pytest

import grid_compare as gc
import review_report as rr
from compare import EXCEL_VAR, INCELEME, KAPSAM_DISI, PDF_VAR, compare
from excel_import import merge_system_excels
from scope import default_scope, matched_unit_ids, unit_groups

from conftest import SAMPLES


@pytest.fixture(scope="module")
def base():
    pdf, xlp = SAMPLES / "arnavutca.pdf", SAMPLES / "system-example.xlsx"
    if not (pdf.exists() and xlp.exists()):
        pytest.skip("örnek dosyalar yok")
    from excel_import import read_system_excel
    from validators import analyze_pdf

    return analyze_pdf(str(pdf)), read_system_excel(str(xlp))


def test_groups_and_default_scope(base):
    res, xl = base
    groups = unit_groups(res)
    assert [(g.name, len(g.unit_ids), g.first_page, g.last_page) for g in groups] == [
        ("5. SINIF (A1.1)", 4, 27, 75),
        ("6. SINIF (A1.1)", 4, 76, 129),
        ("7. SINIF (A1.2)", 4, 130, 183),
        ("8. SINIF (A1.2)", 4, 184, 232),
    ]
    assert matched_unit_ids(res, xl) == {"U01", "U02", "U03", "U04"}
    assert default_scope(res, xl) == {"U01", "U02", "U03", "U04"}


def test_no_scope_is_unchanged_behaviour(base):
    res, xl = base
    df = compare(res, xl)
    assert KAPSAM_DISI not in set(df["Durum"])
    assert len(df[(df["Durum"] == PDF_VAR) & (df["Alan / sütun"] == "Tema")]) == 12
    g = gc.build_grid(res, xl)
    assert not g.out_of_scope and gc.grid_counts(g)[gc.SADECE_PDF] == 847


def test_scope_excludes_other_grades_from_differences(base):
    res, xl = base
    sc = default_scope(res, xl)
    df = compare(res, xl, sc)
    assert len(df[df["Durum"] == KAPSAM_DISI]) == 12 and PDF_VAR not in set(df["Durum"])
    # kapsam içindeki karşılaştırma aynıdır
    full = compare(res, xl)
    inside = lambda d: d[d["Tema (PDF)"].str.startswith("5. SINIF")].reset_index(drop=True)
    assert inside(df).equals(inside(full))
    g = gc.build_grid(res, xl, sc)
    counts = gc.grid_counts(g)
    assert counts[gc.SADECE_PDF] == 0 and counts[gc.FARKLI] == 21 and len(g.out_of_scope) == 12
    assert {r.theme_label.split(" | ")[0] for r in g.rows} == {"5. SINIF (A1.1)"}
    md = rr.python_report(g, "a.pdf", "b.xlsx")
    assert "kapsamı dışında bırakılan PDF temaları (fark sayılmadı): **12**" in md
    assert "Tema sistem Excel'inde yok" not in md


def test_user_can_narrow_or_widen_scope(base):
    res, xl = base
    # 5. sınıftan yalnızca 1. tema: Excel'deki diğer 3 tema kapsam dışı (Excel'de var ama karşılaştırılmaz)
    df = compare(res, xl, {"U01"})
    assert len(df[df["Durum"] == KAPSAM_DISI]) == 15
    g = gc.build_grid(res, xl, {"U01"})
    assert sum(1 for o in g.out_of_scope if o["excelde"]) == 3
    # kapsama Excel'de olmayan bir tema eklenirse gerçek fark olarak kalır (gizlenmez)
    df = compare(res, xl, {"U01", "U02", "U03", "U04", "U05"})
    assert len(df[(df["Durum"] == PDF_VAR) & (df["Alan / sütun"] == "Tema")]) == 1


def test_multiple_excels_are_merged(base):
    res, xl = base
    merged = merge_system_excels([("5a.xlsx", copy.deepcopy(xl)), ("5b.xlsx", copy.deepcopy(xl))])
    assert len(merged.themes) == 8 and merged.themes[4].cell.address == "5b.xlsx!A2"
    assert xl.themes[0].cell.address == "A2"  # kaynak nesne değişmez (kopya birleştirildi)
    # aynı tema iki dosyada: inceleme gerekli
    df = compare(res, merged, default_scope(res, merged))
    assert len(df[(df["Durum"] == INCELEME) & (df["Açıklama"] == "Aynı PDF birimine birden fazla Excel teması eşleşti")]) == 4
    assert merge_system_excels([("tek.xlsx", xl)]) is xl


def test_no_match_keeps_everything_in_scope(base):
    res, xl = base
    empty = copy.deepcopy(xl)
    empty.themes = []
    assert default_scope(res, empty) == {u.id for u in res.units}
    df = compare(res, empty, default_scope(res, empty))
    assert KAPSAM_DISI not in set(df["Durum"]) and EXCEL_VAR not in set(df["Durum"])
