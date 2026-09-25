"""Bilişim Teknolojileri ve Yazılım (samples/bilisim.pdf) regression testleri.

Beklenen değerler PDF'in kendisinden (s.12 özet tablosu ve tema sayfaları) elle doğrulanmıştır.
"""
import re

import pytest

from models import SectionKind, Severity, Status
from pdf_extract import norm_label

from conftest import SAMPLES

PDF = SAMPLES / "bilisim.pdf"

EXPECTED_LO = {  # (sınıf, tema) -> özet tablosundaki öğrenme çıktısı sayısı
    (5, 1): 6, (5, 2): 7, (5, 3): 3, (5, 4): 2, (5, 5): 2, (5, 6): 4,
    (6, 1): 2, (6, 2): 10, (6, 3): 3, (6, 4): 4, (6, 5): 3, (6, 6): 3,
}

UNIT_PATHS = [
    "",
    "DERS SAATİ",
    "ALAN BECERİLERİ",
    "KAVRAMSAL BECERİLER",
    "EĞİLİMLER",
    "PROGRAMLAR ARASI BİLEŞENLER",
    "PROGRAMLAR ARASI BİLEŞENLER > Sosyal-Duygusal Öğrenme Becerileri",
    "PROGRAMLAR ARASI BİLEŞENLER > Değerler",
    "PROGRAMLAR ARASI BİLEŞENLER > Okuryazarlık Becerileri",
    "DİSİPLİNLER ARASI İLİŞKİLER",
    "BECERİLER ARASI İLİŞKİLER",
    "ÖĞRENME ÇIKTILARI VE SÜREÇ BİLEŞENLERİ",
    "İÇERİK ÇERÇEVESİ",
    "Anahtar Kavramlar",
    "ÖĞRENME KANITLARI (Ölçme ve Değerlendirme)",
    "ÖĞRENME-ÖĞRETME YAŞANTILARI",
    "ÖĞRENME-ÖĞRETME YAŞANTILARI > Temel Kabuller",
    "ÖĞRENME-ÖĞRETME YAŞANTILARI > Ön Değerlendirme Süreci",
    "ÖĞRENME-ÖĞRETME YAŞANTILARI > Köprü Kurma",
    "ÖĞRENME-ÖĞRETME YAŞANTILARI > Öğrenme-Öğretme Uygulamaları",
    "FARKLILAŞTIRMA",
    "FARKLILAŞTIRMA > Zenginleştirme",
    "FARKLILAŞTIRMA > Destekleme",
    "ÖĞRETMEN YANSITMALARI",
]


def _norm_path(p: str) -> list[str]:
    return [norm_label(x) for x in p.split(">")] if p else [""]


@pytest.fixture(scope="module")
def bil():
    if not PDF.exists():
        pytest.skip("samples/bilisim.pdf yok")
    from validators import analyze_pdf

    return analyze_pdf(str(PDF))


def unit_by(res, grade, theme):
    for u in res.units:
        if u.context and int(re.match(r"\s*(\d+)", u.context.text).group(1)) == grade and u.order == theme:
            return u
    raise AssertionError((grade, theme))


def checks(res, name, unit_id=None):
    return [f for f in res.findings if f.check == name and (unit_id is None or f.unit_id == unit_id)]


def section(u, path):
    [s] = [s for s in u.sections if _norm_path(s.path) == _norm_path(path)]
    return s


# ---------------------------------------------------------------- yapı ve sayılar


def test_structure_and_schema(bil):
    s = bil.schema_
    assert s.structure_pages == [13, 14]
    assert s.data_start_page == 15
    assert s.unit_keyword == "TEMA" and s.lo_prefix == "BTY" and s.lo_segments == 3
    assert len(s.labels) == 23
    for u in bil.units:
        assert not set(u.pages) & {13, 14}


def test_expected_table_order_from_name_cell(bil):
    # Tabloda ayrı sıra sütunu yok; sıra ad hücresindeki "N." ifadesinden okunur
    got = {
        (int(t.title.text.split(".")[0]), r.order): r.lo_count
        for t in bil.expected_tables
        for r in t.rows
        if r.order is not None
    }
    assert got == EXPECTED_LO
    assert [r.lo_count for t in bil.expected_tables for r in t.rows if r.is_total] == [24, 25]
    assert bil.expected_lo_total == 49


def test_units_and_lo_counts(bil):
    assert len(bil.units) == 12
    # "5. SINIF" başlığı yalnızca ilk temanın önünde; sonraki temalar da o sınıfa aittir
    assert [u.context.text for u in bil.units] == ["5. SINIF"] * 6 + ["6.SINIF"] * 6
    for (g, t), n in EXPECTED_LO.items():
        u = unit_by(bil, g, t)
        assert [lo.code.numbers for lo in u.learning_outcomes] == [[g, t, i] for i in range(1, n + 1)], (g, t)
    assert bil.extracted_lo_total == 49
    for name in ("LO_COUNT_MISMATCH", "LO_TOTAL_MISMATCH", "UNIT_COUNT_MISMATCH", "MISSING_UNIT", "HOURS_MISMATCH", "LO_CODE_IDENTITY"):
        assert not checks(bil, name), name


def test_dotless_i_headings_keep_raw_text(bil):
    # 6. sınıf sayfalarında başlıklar "BILIŞIM", "BILEŞENLERI" olarak kodlanmış: ham metin korunur, eşleşme yapılır
    u = unit_by(bil, 6, 1)
    assert u.title.text == "1. TEMA: BILIŞIM TEKNOLOJILERININ HAYATIMIZDAKI YERI"
    assert any(s.path == "ALAN BECERILERI" for s in u.sections)
    assert not checks(bil, "UNKNOWN_LABEL")


# ---------------------------------------------------------------- bölüm sınırları


def test_sections_in_pdf_order(bil):
    for u in bil.units:
        paths = [_norm_path(s.path) for s in u.sections]
        if u.id == unit_by(bil, 6, 2).id:
            continue
        assert paths == [_norm_path(p) for p in UNIT_PATHS], u.id
    for name in ("SECTION_LEAKAGE", "UNASSIGNED_SPANS", "DOUBLE_ASSIGNED_SPANS", "TEXT_NOT_IN_SOURCE", "SECTION_ORDER", "DUPLICATE_SECTION"):
        assert not checks(bil, name), name


def test_missing_applications_label_split(bil):
    # s.77: "Öğrenme-Öğretme Uygulamaları" başlığı PDF'de yok; kod blokları Köprü Kurma'dan ayrılır
    u = unit_by(bil, 6, 2)
    paths = [s.path for s in u.sections]
    i = paths.index("ÖĞRENME-ÖĞRETME YAŞANTILARI > Köprü Kurma")
    kopru, apps = u.sections[i], u.sections[i + 1]
    assert kopru.content.text.endswith("durumlara ör-\nnekler verilebilir.")
    assert "BTY.6.2.1." not in kopru.content.text
    assert apps.label is None and apps.kind == SectionKind.APPLICATIONS
    assert apps.content.text.startswith("BTY.6.2.1.")
    assert [b.code.key for b in u.applications] == [lo.code.key for lo in u.learning_outcomes]
    [f] = checks(bil, "APPLICATIONS_LABEL_MISSING")
    assert f.unit_id == u.id and f.severity == Severity.NEEDS_REVIEW
    [m] = checks(bil, "MISSING_SECTION")
    assert m.unit_id == u.id and m.details["labels"] == ["Öğrenme-Öğretme Uygulamaları"]
    assert not checks(bil, "UNATTACHED_APPLICATION_TEXT")


def test_lo_code_without_space(bil):
    # s.94: "BTY.6.4.2.Telif hakkı kavramını sorgulayabilme"
    u = unit_by(bil, 6, 4)
    lo = u.learning_outcomes[1]
    assert lo.code.raw == "BTY.6.4.2." and lo.title.text == "Telif hakkı kavramını sorgulayabilme"
    assert [c.letter for c in lo.components] == ["a", "b", "c", "ç", "d"]
    assert [c.letter for c in u.learning_outcomes[0].components] == ["a", "b", "c", "ç"]
    assert not checks(bil, "COMPONENT_LETTER_SEQUENCE")


# ---------------------------------------------------------------- kod tanımları


def test_nested_and_hyphenated_field_skills(bil):
    u = unit_by(bil, 5, 6)
    alan = u.declarations["ALAN BECERİLERİ"]
    assert [(d.code.normalized, d.parent) for d in alan] == [
        ("BTYAB2", None),
        ("BTYAB2.1", "BTYAB2"),
        ("BTYAB2.4", "BTYAB2"),
        ("BTYAB3", None),
        ("BTYAB3.2", "BTYAB3"),
        ("BTYAB3.3", "BTYAB3"),
    ]
    assert alan[5].code.raw == "BT-\nYAB3.3."  # satır sonunda bölünmüş kod ham haliyle
    assert alan[5].entry.text == "BT-\nYAB3.3. Yazılım Geliştirme Sürecini Yönetme"
    assert alan[1].entry.text == "BTYAB2.1. Algoritmik Düşünme"
    assert alan[0].entry.text.startswith("BTYAB2. Bilgi İşlemsel Düşünme (BTYAB2.1.")
    # alan becerileri kod kontrolüne girmez
    assert not [f for f in checks(bil, "DECLARED_NOT_USED") if "ALAN" in f.details["category"].upper()]


def test_nonstandard_declarations_recognized_with_warning(bil):
    u7 = unit_by(bil, 6, 1)
    eg = [d for p, ds in u7.declarations.items() if norm_label(p) == norm_label("EĞİLİMLER") for d in ds]
    assert [(d.code.raw, d.code.normalized, d.standard_format) for d in eg] == [
        ("E.1.1.", "E1.1", False),
        ("E3.3.", "E3.3", True),
        ("E3.8.", "E3.8", True),
    ]
    u8 = unit_by(bil, 6, 2)
    eg8 = [d for p, ds in u8.declarations.items() if norm_label(p) == norm_label("EĞİLİMLER") for d in ds]
    assert eg8[0].code.raw == "E1.1" and eg8[0].entry.text == "E1.1 Merak"
    raws = {(f.unit_id, f.details["code_raw"]) for f in checks(bil, "CODE_FORMAT_ANOMALY") if "entry" in f.details}
    assert {(u7.id, "E.1.1."), (u8.id, "E1.1"), (u8.id, "E3.8."), (unit_by(bil, 6, 6).id, "OB1.")} <= raws
    assert all(f.severity == Severity.WARNING for f in checks(bil, "CODE_FORMAT_ANOMALY"))
    assert not checks(bil, "DECLARATION_UNPARSED_CODE")


def test_real_used_not_declared(bil):
    # Tema girişlerinde (metin olarak gevşek aramayla da) bulunmayan, uygulamalarda kullanılan kodlar
    got = {(f.unit_id, f.details["code_raw"]) for f in checks(bil, "USED_NOT_DECLARED")}
    exp = {
        (unit_by(bil, 5, 3).id, "KB2.7"),
        (unit_by(bil, 5, 3).id, "KB2.18"),
        (unit_by(bil, 5, 3).id, "OB2"),
        (unit_by(bil, 5, 3).id, "E3.2"),
        (unit_by(bil, 5, 4).id, "D1.1"),
        (unit_by(bil, 6, 2).id, "KB2.7"),
        (unit_by(bil, 6, 4).id, "E3.3"),
        (unit_by(bil, 6, 4).id, "OB2"),
    }
    assert got == exp
    assert all(f.severity == Severity.FAIL for f in checks(bil, "USED_NOT_DECLARED"))


def test_name_mismatch_and_statuses(bil):
    # Tablo: "2. Dijital Ürün Tasarım ve Geliştirme" / başlık: "DİJİTAL ÜRÜN TASARIMI VE GELİŞTİRME"
    got = {f.unit_id for f in checks(bil, "UNIT_NAME_MISMATCH")}
    assert got == {unit_by(bil, 5, 2).id, unit_by(bil, 6, 2).id}
    assert all(f.severity == Severity.NEEDS_REVIEW for f in checks(bil, "UNIT_NAME_MISMATCH"))
    st = {r.unit_id: r.status for r in bil.unit_reports}
    for g, t in ((5, 3), (5, 4), (6, 2), (6, 4)):
        assert st[unit_by(bil, g, t).id] == Status.FAIL
    assert st[unit_by(bil, 5, 2).id] == Status.NEEDS_REVIEW
    assert bil.status == Status.FAIL


def test_dash_is_not_empty_section(bil):
    # "-" PDF'de yazılı içeriktir (boş değil); KAVRAMSAL BECERİLER'in altı gerçekten boş olan temalar ayrı
    u2 = unit_by(bil, 5, 2)
    assert section(u2, "KAVRAMSAL BECERİLER").content.text == "-"
    empty = {(f.unit_id, norm_label(f.details["section"])) for f in checks(bil, "EMPTY_SECTION")}
    assert empty == {(unit_by(bil, 5, 5).id, norm_label("KAVRAMSAL BECERİLER")), (unit_by(bil, 6, 2).id, norm_label("KAVRAMSAL BECERİLER"))}
