"""Fizik, Kimya, Fen Bilimleri, Hayat Bilgisi, Afet Bilinci regression testleri.

Her programın FAIL/NEEDS_REVIEW bulgu kümesi PDF'de tek tek doğrulanmış kaynak
durumlarıdır; beklenen sonuç olarak sabitlenmiştir.
"""
import pytest

from models import Severity, TableRole
from pdf_extract import context_in_title, dehyphen_view

from conftest import SAMPLES

_cache: dict = {}


def res(name):
    if name not in _cache:
        p = SAMPLES / f"{name}.pdf"
        if not p.exists():
            pytest.skip(f"samples/{name}.pdf yok")
        from validators import analyze_pdf

        _cache[name] = analyze_pdf(str(p))
    return _cache[name]


def blocking(r):
    """(bulgu, (bağlam, birim sırası), ayrıntı) kümesi — WARNING hariç."""
    ids = {u.id: (u.context.text if u.context else None, u.order) for u in r.units}
    return {
        (f.check, ids.get(f.unit_id), f.details.get("code_raw") or f.details.get("text") or str(f.details.get("labels")))
        for f in r.findings
        if f.severity != Severity.WARNING
    }


# (program, anahtar kelime, birim sayısı, ÖÇ toplamı, bağlamlar)
PROGRAMS = [
    ("fizik", "ÜNİTE", 15, 106, ["9. SINIF", "10. SINIF", "11. SINIF", "12. SINIF"]),
    ("kimya", "TEMA", 12, 93, ["9. SINIF TEMALARI", "10. SINIF TEMALARI", "11. SINIF TEMALARI", "12. SINIF TEMALARI"]),
    ("fen", "ÜNİTE", 44, 180, ["3. SINIF", "4. SINIF", "5. SINIF", "6. SINIF", "7. SINIF", "8. SINIF"]),
    ("hayalbilgisi", "ÖĞRENME ALANI", 18, 66, ["1. SINIF", "2. SINIF", "3. SINIF"]),
    ("afet", "ÜNİTE", 8, 22, ["I. DÜZEY", "II. DÜZEY"]),
]


@pytest.mark.parametrize("name,kw,n_units,n_lo,contexts", PROGRAMS)
def test_units_contexts_and_counts(name, kw, n_units, n_lo, contexts):
    r = res(name)
    assert r.schema_.unit_keyword == kw
    assert len(r.units) == r.expected_unit_count == n_units
    assert r.expected_lo_total == r.extracted_lo_total == n_lo
    seen = []
    for u in r.units:
        if u.context.text not in seen:
            seen.append(u.context.text)
    assert seen == contexts
    for c in ("SECTION_LEAKAGE", "UNASSIGNED_SPANS", "DOUBLE_ASSIGNED_SPANS", "TEXT_NOT_IN_SOURCE", "ORPHAN_LABEL", "MISSING_UNIT", "EXPECTED_TABLE_AMBIGUOUS"):
        assert not [f for f in r.findings if f.check == c], (name, c)


def test_fizik_findings():
    # s.26: "İlkeler" ve "Deneyler" yapı sayfasında yok (ayrı bölüm + NEEDS_REVIEW); "Deneyler"
    # "Değerler"e eşlenmez. s.86-87: 12. sınıf 2. ünitede "ÖĞRENME-ÖĞRETME YAŞANTILARI" basılmamış.
    assert blocking(res("fizik")) == {
        ("UNKNOWN_LABEL", ("9. SINIF", 3), "İlkeler"),
        ("UNKNOWN_LABEL", ("9. SINIF", 3), "Deneyler"),
        ("MISSING_SECTION", ("12. SINIF", 2), "['ÖĞRENME-ÖĞRETME YAŞANTILARI']"),
    }
    u = res("fizik").units[2]
    labels = [s.label.text for s in u.sections if s.label is not None]
    i = labels.index("İlkeler")
    assert labels[i : i + 3] == ["İlkeler", "Anahtar Kavramlar", "Deneyler"]
    assert [s.content.text for s in u.sections if s.label is not None and s.label.text in ("İlkeler", "Deneyler")] == ["Bernoulli İlkesi", "Torricelli deneyi"]


def test_kimya_findings():
    # Başlık rengi yapı sayfasında #0098B9, tema sayfalarında #01B49C; s.101 "(KB2.\n14, …)" tanımlı KB2.14.
    # "(E )" elektrokimya sembolü tek başına önek gibi görünür: NEEDS_REVIEW.
    r = res("kimya")
    assert blocking(r) == {("USED_CODE_MALFORMED", ("12. SINIF TEMALARI", 1), "E")}
    assert 0x98B9 not in r.schema_.label_colors


def test_fen_findings():
    r = res("fen")
    assert blocking(r) == {
        ("GROUP_HAS_CONTENT", ("3. SINIF", 4), "None"),  # s.31 içerik FARKLILAŞTIRMA satırından başlıyor
        ("LABEL_TEXT_VARIANT", ("3. SINIF", 5), "Öğrenme-Öğretme  Uygulamalar"),
        ("MISSING_SECTION", ("5. SINIF", 3), "['ALAN BECERİLERİ']"),  # s.88 yerinde "ÖĞRENCİ PROFİLİ"
        ("MISSING_SECTION", ("8. SINIF", 6), "['Genellemeler/ İlkeler/ Anahtar Kavramlar/ Semboller vb.']"),
        ("UNKNOWN_LABEL", ("3. SINIF", 4), "ÖĞRENCİ PROFİLİ "),
        ("UNKNOWN_LABEL", ("4. SINIF", 4), "ÖĞRENCİ PROFİLİ"),
        ("UNKNOWN_LABEL", ("4. SINIF", 8), "ÖĞRENCİ PROFİLİ"),
        ("UNKNOWN_LABEL", ("5. SINIF", 3), "ÖĞRENCİ  PROFİLİ"),
        ("UNKNOWN_LABEL", ("7. SINIF", 6), "ÖĞRENCİ PROFİLİ"),
        ("UNKNOWN_LABEL", ("8. SINIF", 6), "Yasalar/Anahtar  Kavramlar"),
        ("USED_CODE_MALFORMED", ("6. SINIF", 2), "D20,2"),
        ("USED_NOT_DECLARED", ("7. SINIF", 7), "D1.4"),
    }
    # s.127: bileşendeki tek kelime "Işığın" #000000 (gövde #221F1F) basılmış; bileşen metnine aittir
    lo = next(lo for u in r.units for lo in u.learning_outcomes if lo.code.normalized == "FB.6.4.1")
    assert lo.components[1].marker == "b)" and lo.components[1].text.text.startswith("Işığın farklı yüzeylerdeki")
    # s.98: bileşik başlığın parçaları ("Genellemeler/Anahtar Kavramlar") o başlığın yerindedir
    compound = {s.label.text: s.label_norm for u in r.units for s in u.sections if s.label is not None and "/" in s.label.text}
    assert compound == {
        "Genellemeler/Anahtar\nKavramlar": "genellemelerilkeleranahtarkavramlarsembollervb",
        "İlkeler/Anahtar\nKavramlar": "genellemelerilkeleranahtarkavramlarsembollervb",
        "Yasalar/Anahtar\nKavramlar": "yasalaranahtarkavramlar",  # "Yasalar" yapı sayfasında yok: UNKNOWN_LABEL
    }


def test_hayalbilgisi_findings():
    # s.72: "SDB2B.3" yazım hatası -> SDB2.3 tanımsız. Süreç bileşeni olmayan ÖÇ bulgu değildir.
    r = res("hayalbilgisi")
    assert blocking(r) == {
        ("DECLARATION_UNPARSED_CODE", ("3. SINIF", 4), "SDB2"),
        ("USED_NOT_DECLARED", ("3. SINIF", 4), "SDB2.3"),
    }
    assert sum(1 for u in r.units for lo in u.learning_outcomes if not lo.components) == 31


def test_afet_tables_and_limited_lists():
    r = res("afet")
    roles = [(t.page, t.role, t.title.text.split("\n")[0][:25]) for t in r.expected_tables]
    assert roles == [
        (10, TableRole.SUMMARY, "AFET BİLİNCİ I. DÜZEY"),
        (10, TableRole.ALTERNATIVE, "AFET BİLİNCİ I. DÜZEY"),
        (11, TableRole.SUMMARY, "AFET BİLİNCİ II. DÜZEY"),
        (11, TableRole.ALTERNATIVE, "AFET BİLİNCİ II. DÜZEY"),
        (12, TableRole.LO_LIST, "AFET BİLİNCİ I. DÜZEY DER"),
        (12, TableRole.LO_LIST, "AFET BİLİNCİ II. DÜZEY DE"),
    ]
    lst = r.expected_tables[4]
    assert [[c.text for c in col.codes] for col in lst.lo_columns] == [["AB.1.1.1", "AB.1.1.2", "AB.1.1.3"], ["AB.1.2.1"], ["AB.1.3.1"], ["AB.1.4.2"]]
    assert blocking(r) == {("USED_CODE_MALFORMED", ("II. DÜZEY", 4), "OB2,0")}


def test_afet_limited_checks_detect_mismatch():
    from validators import check_limited_tables

    r = res("afet").model_copy(deep=True)
    assert check_limited_tables(r.units, r.expected_tables) == []
    r.expected_tables[4].lo_columns[1].codes[0].text = "AB.1.2.9"
    r.expected_tables[1].rows[0].lo_count = 2
    got = {(f.check, f.unit_id) for f in check_limited_tables(r.units, r.expected_tables)}
    assert got == {("LIMITED_LO_COUNT_MISMATCH", "U01"), ("LIMITED_LO_NOT_FOUND", "U02")}


def test_context_and_code_primitives():
    assert context_in_title("9. SINIF", "FİZİK DERSİ 9. SINIF")
    assert context_in_title("9. SINIF TEMALARI", "9. SINIF KİMYA DERSİ")
    assert not context_in_title("1. SINIF", "FİZİK DERSİ 11. SINIF")
    assert not context_in_title("I. DÜZEY", "AFET BİLİNCİ II. DÜZEY")
    assert dehyphen_view("(KB2.\n14, OB2)")[0] == "(KB2.14, OB2)"
    assert dehyphen_view("sayfa 3.\n4 satır")[0] == "sayfa 3.\n4 satır"


# ---------------------------------------------------------------- Matematik ve yapı sayfası olmadan çıkarım


def test_matematik_structure_heading_far_from_diagram():
    # s.12 "…PROGRAMI'NIN YAPISI" başlığı, şema s.17-18'de; ÖÇ kodunun 2. segmenti içerik alanı (tema sırası
    # değil) ve numaralar alan içinde temalar boyunca devam eder (MAT.1.1.8 2. temada). Tablo işleniş sırasına
    # göre dizili; satırlar adla eşleşir. s.43: Öğrenme Kanıtları metni grup başlığının altına taşmış.
    r = res("matematik")
    assert r.schema_.structure_pages == [17, 18] and r.schema_.unit_keyword == "TEMA"
    assert len(r.units) == r.expected_unit_count == 26
    assert r.expected_lo_total == r.extracted_lo_total == 111
    assert blocking(r) == {("GROUP_HAS_CONTENT", ("1. SINIF", 6), "None")}
    u = r.units[25]
    assert u.title.text == "7. TEMA: OLAYLARIN OLASILIĞI VE\nVERİYE DAYALI ARAŞTIRMA" and u.subtitle is None


def _without_structure(name):
    """Yapı sayfaları PDF'de hiç yokmuş gibi analiz (yapı tema sayfalarından öğrenilir)."""
    import pdf_extract
    import validators

    base = res(name)
    orig = pdf_extract.extract_spans

    def patched(path):
        d = orig(path)
        d.spans = [s for s in d.spans if s.page not in base.schema_.structure_pages]
        return d

    validators.extract_spans = patched
    try:
        return base, validators.analyze_pdf(str(SAMPLES / f"{name}.pdf"))
    finally:
        validators.extract_spans = orig


@pytest.mark.parametrize("name", ["zazaca", "kimya", "matematik", "hayalbilgisi"])
def test_extraction_without_structure_page(name):
    base, r = _without_structure(name)
    assert r.schema_.structure_pages == []
    assert [f.check for f in r.findings if f.check == "STRUCTURE_PAGE_NOT_FOUND"] == ["STRUCTURE_PAGE_NOT_FOUND"]
    assert [u.title.text for u in r.units] == [u.title.text for u in base.units]
    assert [[lo.code.raw for lo in u.learning_outcomes] for u in r.units] == [[lo.code.raw for lo in u.learning_outcomes] for u in base.units]
    assert [[s.label.text if s.label else None for s in u.sections] for u in r.units] == [
        [s.label.text if s.label else None for s in u.sections] for u in base.units
    ]


def test_structure_found_without_heading_hint(monkeypatch):
    # "YAPISI" başlığı olmasa da yapı sayfası küçültülmüş başlıklarından tanınır
    import schema_detect
    from validators import analyze_pdf

    monkeypatch.setattr(schema_detect, "STRUCTURE_HINTS", ())
    r = analyze_pdf(str(SAMPLES / "kimya.pdf"))
    assert r.schema_.structure_pages == [11, 12] and len(r.units) == 12 and r.extracted_lo_total == 93


def test_used_not_declared_listed_under_its_category():
    # Fen U37: D1.4 uygulamada kullanılmış ama Değerler'de tanımlı değil -> Değerler satırında görünür
    from excel_export import code_checks_df

    df = code_checks_df(res("fen"))
    row = df[df["Kullanılmış ama tanımlı değil"] != ""]
    assert list(zip(row["Birim"], row["Kategori"], row["Kullanılmış ama tanımlı değil"])) == [
        ("U37", "PROGRAMLAR ARASI BİLEŞENLER > Değerler", "D1.4")
    ]


def test_excel_never_fails_on_control_characters():
    # PyMuPDF'in yeni sürümleri görünmez glifler için "\x07" üretebilir; Excel'e yazılamaz
    import openpyxl, io
    from excel_export import _append, _xl_safe
    from pdf_extract import _visible

    removed = {}
    assert _visible("\x07Öğrenciler\tçalışır", 11, removed) == "Öğrenciler\tçalışır" and removed == {11: 1}
    wb = openpyxl.Workbook()
    _append(wb.active, ["a\x07b", 3, None])
    assert wb.active["A1"].value == "a�b" and _xl_safe(5) == 5
    wb.save(io.BytesIO())
