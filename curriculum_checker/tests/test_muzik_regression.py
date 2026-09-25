"""Müzik Dersi Öğretim Programı (samples/müzik.pdf) regression testleri.

Beklenen değerler PDF'in kendisinden (s.8-9 özet tablosu ve tema sayfaları) elle doğrulanmıştır.
"""
import copy

import pytest

from models import ExpectedRow, SectionKind, Severity, Status
from pdf_extract import norm_label
from validators import check_codes, check_learning_outcomes, check_sections

EXPECTED_LO = {  # (sınıf, tema) -> özet tablosundaki öğrenme çıktısı sayısı
    (1, 1): 7, (1, 2): 6, (2, 1): 6, (2, 2): 6, (3, 1): 6, (3, 2): 6, (4, 1): 6, (4, 2): 6,
    (5, 1): 7, (5, 2): 8, (6, 1): 6, (6, 2): 7, (7, 1): 6, (7, 2): 10, (8, 1): 6, (8, 2): 9,
}

PDF_LABELS = [
    "DERS SAATİ",
    "ALAN BECERİLERİ",
    "KAVRAMSAL BECERİLER",
    "EĞİLİMLER",
    "PROGRAMLAR ARASI BİLEŞENLER",
    "Sosyal Duygusal Öğrenme Becerileri",
    "Değerler",
    "Okuryazarlık Becerileri",
    "DİSİPLİNLER ARASI İLİŞKİLER",
    "BECERİLER ARASI İLİŞKİLER",
    "ÖĞRENME ÇIKTILARI VE SÜREÇ BİLEŞENLERİ",
    "İÇERİK ÇERÇEVESİ",
    "Anahtar Kavramlar",
    "ÖĞRENME KANITLARI (Ölçme ve Değerlendirme)",
    "ÖĞRENME-ÖĞRETME YAŞANTILARI",
    "Temel Kabuller",
    "Ön Değerlendirme Süreci",
    "Köprü Kurma",
    "Öğrenme-Öğretme Uygulamaları",
    "FARKLILAŞTIRMA",
    "Zenginleştirme",
    "Destekleme",
    "ÖĞRETMEN YANSITMALARI",
]

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


def unit_by(res, grade, theme):
    for u in res.units:
        if u.context and u.context.text == f"{grade}. SINIF" and u.order == theme:
            return u
    raise AssertionError((grade, theme))


def section(u, path):
    [s] = [s for s in u.sections if s.path == path]
    return s


def checks(res, name, unit_id=None):
    return [f for f in res.findings if f.check == name and (unit_id is None or f.unit_id == unit_id)]


def all_unit_text(res):
    return "\n".join(s.content.text for u in res.units for s in u.sections if s.content)


# ---------------------------------------------------------------- program yapısı


def test_structure_page_detected_and_labels_learned_verbatim(muzik):
    s = muzik.schema_
    assert s.structure_pages == [11, 12, 13]
    assert s.structure_heading.text == "1.5. MÜZİK DERSİ ÖĞRETİM PROGRAMI’NIN YAPISI"
    assert s.data_start_page == 14
    assert s.unit_keyword == "TEMA"
    assert s.lo_prefix == "MÜZ" and s.lo_segments == 3
    assert [l.text for l in s.labels] == PDF_LABELS


def test_structure_page_is_not_a_unit(muzik):
    for u in muzik.units:
        assert not set(u.pages) & {11, 12, 13}
    text = all_unit_text(muzik)
    # yapı sayfasındaki açıklama metinleri gerçek birimlere girmemeli
    assert "Disiplin kodu" not in text
    assert "Temanın adını ifade eder." not in text


def test_expected_table(muzik):
    rows = [r for t in muzik.expected_tables for r in t.rows if r.order is not None]
    got = {(int(t.title.text.split(".")[0]), r.order): r.lo_count for t in muzik.expected_tables for r in t.rows if r.order is not None}
    assert got == EXPECTED_LO
    assert len(rows) == 16
    assert muzik.expected_lo_total == 108
    totals = [r.lo_count for t in muzik.expected_tables for r in t.rows if r.is_total]
    assert totals == [13, 12, 12, 12, 15, 13, 16, 15]


# ---------------------------------------------------------------- birimler ve sayılar


def test_units_found(muzik):
    assert len(muzik.units) == 16
    assert [(u.context.text, u.title.text) for u in muzik.units[:2]] == [
        ("1. SINIF", "1. TEMA: MÜZİK DİLİ"),
        ("1. SINIF", "2. TEMA: MÜZİK KÜLTÜRÜ"),
    ]
    assert muzik.units[-1].title.text == "2. TEMA: MÜZİK KÜLTÜRÜ" and muzik.units[-1].context.text == "8. SINIF"


def test_lo_counts_match_expected(muzik):
    for (g, t), n in EXPECTED_LO.items():
        u = unit_by(muzik, g, t)
        assert len(u.learning_outcomes) == n, (g, t)
        assert [lo.code.numbers for lo in u.learning_outcomes] == [[g, t, i] for i in range(1, n + 1)]
    assert muzik.extracted_lo_total == 108
    assert not checks(muzik, "LO_COUNT_MISMATCH")
    assert not checks(muzik, "LO_TOTAL_MISMATCH")
    assert not checks(muzik, "UNIT_COUNT_MISMATCH")
    assert not checks(muzik, "MISSING_UNIT")


def test_hours_match_table(muzik):
    for r in muzik.unit_reports:
        assert r.extracted_hours == r.expected_hours is not None
    assert not checks(muzik, "HOURS_MISMATCH")


# ---------------------------------------------------------------- bölüm sınırları


def test_every_unit_has_all_sections_in_pdf_order(muzik):
    for u in muzik.units:
        assert [s.path for s in u.sections] == UNIT_PATHS, u.id
    assert not checks(muzik, "MISSING_SECTION")
    assert not checks(muzik, "UNKNOWN_LABEL")
    assert not checks(muzik, "SECTION_ORDER")
    assert not checks(muzik, "DUPLICATE_SECTION")


def test_no_section_leakage_and_full_coverage(muzik):
    assert not checks(muzik, "SECTION_LEAKAGE")
    assert not checks(muzik, "UNASSIGNED_SPANS")
    assert not checks(muzik, "DOUBLE_ASSIGNED_SPANS")
    assert not checks(muzik, "TEXT_NOT_IN_SOURCE")
    assert not checks(muzik, "NO_SOURCE_SPANS")
    labels = {norm_label(l) for l in PDF_LABELS}
    for u in muzik.units:
        for s in u.sections:
            for row in s.content_rows:
                assert norm_label(row.text) not in labels, (u.id, s.path, row.text)


def test_unit1_boundaries(muzik):
    u = unit_by(muzik, 1, 1)
    assert section(u, "DERS SAATİ").content.text == "18"
    assert section(u, "İÇERİK ÇERÇEVESİ").content.text == (
        "İstiklâl Marşı’nın başlıca ögeleri\nDoğadan/çevreden/nesnelerden duyulan sesler\nMüziksel dinleme\n"
        "Farklı türdeki eserler\nBelirli gün ve haftalarla ilgili eserler\nOrtak repertuvar\nBedensel hareketler"
    )
    assert section(u, "Anahtar Kavramlar").content.text == "Ses kaynakları, tekerleme, ninni, sayışmaca"
    assert section(u, "ÖĞRETMEN YANSITMALARI").content.text == (
        "Programa yönelik görüş ve önerileriniz için karekodu akıllı cihazınıza\nokutunuz."
    )
    # Son öğrenme çıktısının son bileşeni İÇERİK ÇERÇEVESİ'ne taşmamalı
    last = u.learning_outcomes[-1]
    assert last.code.raw == "MÜZ.1.1.7."
    assert last.title.text == "Müzik eserlerine bedensel hareketlerle eşlik edebilme"
    assert [(c.marker, c.text.text) for c in last.components] == [
        ("a)", "Ritmik yapıya/eserin anlamına uygun hareketler belirler."),
        ("b)", "Ritmik yapıya/eserin anlamına uygun hareketler sergiler."),
    ]
    # Son uygulama bloğu FARKLILAŞTIRMA'ya taşmamalı, ondan önce de kesilmemeli
    app = u.applications[-1]
    assert app.header.text == "MÜZ.1.1.7."
    assert app.body.text.startswith("Parmak şıklatma, alkış yapma")
    assert app.body.text.endswith("kontrol listesi gibi araçlardan biriyle yapılabilir.")
    assert "Zenginleştirme" not in app.body.text and "FARKLILAŞTIRMA" not in app.body.text
    desc = u.sections[0]
    assert desc.label is None and desc.kind == SectionKind.UNIT_DESCRIPTION
    assert desc.content.text.startswith("Bu temada öğrencilerin İstiklâl Marşı’nın")
    assert desc.content.text.endswith("edebilmeleri amaçlanmaktadır.")


def test_multipage_unit_sections(muzik):
    # 8. sınıf 2. tema: "Anahtar Kavramlar" s.103 başında, İÇERİK ÇERÇEVESİ s.102 sonunda
    u = unit_by(muzik, 8, 2)
    icerik = section(u, "İÇERİK ÇERÇEVESİ").content
    assert icerik.pages[0] == 102
    assert section(u, "Anahtar Kavramlar").content is None
    assert section(u, "ÖĞRENME KANITLARI (Ölçme ve Değerlendirme)").content.text.startswith("Bu temadaki öğrenme çıktıları;")


def test_non_unit_pages_excluded(muzik):
    text = all_unit_text(muzik)
    assert "ESER ADI" not in text  # repertuvar listeleri
    assert "ORTAK REPERTUVAR" not in text
    assert "EK-1" not in text and "PERFORMANS GÖREVİ İÇİN DERECELİ PUANLAMA ANAHTARI" not in text
    heads = [r.heading.text for r in muzik.excluded_regions if r.heading]
    assert sum("ORTAK REPERTUVAR LİSTESİ" in h for h in heads) == 8
    for u in muzik.units:
        assert not set(u.pages) & {24, 35, 46, 57, 70, 82, 95, 107, 108, 109, 110, 111}


# ---------------------------------------------------------------- kodlar


def test_raw_code_variants_preserved(muzik):
    u9 = unit_by(muzik, 5, 1)
    assert [lo.code.raw for lo in u9.learning_outcomes][5] == "MÜZ. 5.1.6."
    headers = [b.header.text for b in u9.applications]
    assert headers == ["MÜZ.5.1.1.", "MÜZ.5.1.2.", "MÜZ 5.1.3.", "MÜZ.5.1.4.", "MÜZ.5.1.5.", "MÜZ. 5.1.6.", "MÜZ.5.1.7."]
    assert [b.code.normalized for b in u9.applications] == [f"MÜZ.5.1.{i}" for i in range(1, 8)]
    lo_where = ("öğrenme çıktıları", "öğrenme-öğretme uygulamaları")
    raws = sorted({f.details["code_raw"] for f in checks(muzik, "CODE_FORMAT_ANOMALY") if f.details["where"] in lo_where})
    assert raws == ["MÜZ 5.1.3.", "MÜZ 6.1.3.", "MÜZ 6.2.4.", "MÜZ 8.1.3.", "MÜZ 8.2.6.", "MÜZ. 5.1.6.", "MÜZ. 6.1.6.", "MÜZ. 7.1.6."]
    assert all(f.severity == Severity.WARNING for f in checks(muzik, "CODE_FORMAT_ANOMALY"))


def test_every_lo_linked_to_exactly_one_application(muzik):
    for u in muzik.units:
        assert [b.code.key for b in u.applications] == [lo.code.key for lo in u.learning_outcomes], u.id
    for name in ("APPLICATION_MISSING", "APPLICATION_DUPLICATE", "APPLICATION_UNKNOWN_CODE", "UNATTACHED_APPLICATION_TEXT"):
        assert not checks(muzik, name)


def test_declarations_raw_text(muzik):
    u = unit_by(muzik, 1, 1)
    alan = u.declarations["ALAN BECERİLERİ"]
    assert [(d.code.raw, d.entry.text) for d in alan] == [
        ("SAB9.", "SAB9. Müziksel Dinleme Becerisi"),
        ("SAB10.", "SAB10. Müziksel Söyleme Becerisi"),
        ("SAB13.", "SAB13. Müziksel Ha-\nreket Becerisi"),  # tire + satır kırılımı korunur
    ]
    assert alan[2].entry.compare_key == "SAB13. Müziksel Hareket Becerisi"
    assert alan[2].entry.pages == [14] and len(alan[2].entry.source_spans) == 2
    degerler = u.declarations["PROGRAMLAR ARASI BİLEŞENLER > Değerler"]
    assert [d.code.normalized for d in degerler] == ["D3", "D4", "D11", "D13", "D14", "D15", "D19"]


def test_code_cross_check_hierarchical(muzik):
    u = unit_by(muzik, 1, 1)
    rep = next(r for r in muzik.unit_reports if r.unit_id == u.id)
    deg = next(c for c in rep.code_checks if c.category.endswith("Değerler"))
    # D11.2, D14.3, D19.1 ... kullanılmış; üst kodlar D11, D14, D19 tanımlı -> MATCHED
    assert {"D11", "D14", "D19"} <= set(deg.matched)
    assert "D11.2" in deg.used
    assert rep.used_not_declared == []


def test_field_skills_out_of_cross_check(muzik):
    # Alan becerileri çıkarılır (Excel karşılaştırması için) ama kod kontrolüne girmez
    u = unit_by(muzik, 1, 1)
    assert [d.code.normalized for d in u.declarations["ALAN BECERİLERİ"]] == ["SAB9", "SAB10", "SAB13"]
    rep = next(r for r in muzik.unit_reports if r.unit_id == u.id)
    assert "ALAN BECERİLERİ" not in [c.category for c in rep.code_checks]
    assert not [f for f in checks(muzik, "DECLARED_NOT_USED") if f.details["category"] == "ALAN BECERİLERİ"]


def test_nonstandard_declared_code_is_recognized(muzik):
    # s.88: EĞİLİMLER'de "E.1.6. Seçicilik" (önekten sonra fazladan nokta); s.92'de (E1.6) kullanılıyor
    u = unit_by(muzik, 7, 2)
    eg = {d.code.raw: d for d in u.declarations["EĞİLİMLER"]}
    assert "E.1.6." in eg and eg["E.1.6."].code.normalized == "E1.6"
    assert eg["E.1.6."].entry.text == "E.1.6. Seçicilik"
    assert eg["E1.5."].entry.text == "E1.5. Kendine Güvenme (Öz Güven)"  # önceki girdiye karışmıyor
    [f] = [f for f in checks(muzik, "CODE_FORMAT_ANOMALY", u.id) if f.details["where"] == "EĞİLİMLER"]
    assert f.details["code_raw"] == "E.1.6." and f.severity == Severity.WARNING
    rep = next(r for r in muzik.unit_reports if r.unit_id == u.id)
    assert "E1.6" in next(c for c in rep.code_checks if c.category == "EĞİLİMLER").matched
    assert not checks(muzik, "USED_NOT_DECLARED")
    assert not checks(muzik, "DECLARATION_UNPARSED_CODE")


def test_used_not_declared_is_fail(muzik):
    u = copy.deepcopy(unit_by(muzik, 7, 2))
    u.declarations["EĞİLİMLER"] = [d for d in u.declarations["EĞİLİMLER"] if d.code.normalized != "E1.6"]
    _, not_declared, fs = check_codes(u, {"SAB"})
    assert not_declared == ["E1.6"]
    assert any(f.check == "USED_NOT_DECLARED" and f.severity == Severity.FAIL for f in fs)


def test_source_anomalies_reported(muzik):
    # s.59: MÜZ.5.1.7. bileşenleri a) b) c) d) — Türk alfabesinde c)'den sonra ç) gelir
    [f] = checks(muzik, "COMPONENT_LETTER_SEQUENCE")
    assert f.details["code_raw"] == "MÜZ.5.1.7." and f.details["letters"] == ["a", "b", "c", "d"]
    assert f.severity == Severity.NEEDS_REVIEW
    empty = sorted((f.unit_id, f.details["section"]) for f in checks(muzik, "EMPTY_SECTION"))
    u15 = unit_by(muzik, 8, 1).id
    assert (u15, "KAVRAMSAL BECERİLER") in empty
    assert all(f.severity == Severity.WARNING for f in checks(muzik, "EMPTY_SECTION"))


def test_unit_statuses(muzik):
    st = {r.unit_id: r.status for r in muzik.unit_reports}
    assert st[unit_by(muzik, 5, 1).id] == Status.NEEDS_REVIEW  # MÜZ.5.1.7. a) b) c) d)
    others = {s for uid, s in st.items() if uid != unit_by(muzik, 5, 1).id}
    assert others <= {Status.PASS, Status.WARNING}  # yalnızca kullanılmayan kod / biçim / boş bölüm uyarıları
    assert muzik.status == Status.NEEDS_REVIEW


def test_every_text_linked_to_source_spans(muzik):
    from validators import _iter_fields

    for u in muzik.units:
        for f in _iter_fields(u):
            assert f.source_spans and f.pages, (u.id, f.text[:40])


# ---------------------------------------------------------------- PASS verilmemesi gereken durumlar


def test_count_mismatch_is_fail(muzik):
    u = unit_by(muzik, 1, 1)
    row = ExpectedRow(table_index=0, order=1, name=None, lo_count_raw="8", lo_count=8, hours=18)
    fs = check_learning_outcomes(u, row, muzik.schema_)
    assert any(f.check == "LO_COUNT_MISMATCH" and f.severity == Severity.FAIL for f in fs)
    missing = copy.deepcopy(u)
    missing.learning_outcomes.pop(3)
    fs = check_learning_outcomes(missing, ExpectedRow(table_index=0, order=1, name=None, lo_count_raw="7", lo_count=7, hours=18), muzik.schema_)
    assert {f.check for f in fs if f.severity == Severity.FAIL} >= {"LO_COUNT_MISMATCH", "LO_CODE_IDENTITY"}


def test_leakage_is_detected(muzik):
    u = copy.deepcopy(unit_by(muzik, 1, 1))
    lo_sec = next(s for s in u.sections if s.kind == SectionKind.LEARNING_OUTCOMES)
    icerik = section(u, "İÇERİK ÇERÇEVESİ")
    lo_sec.content_rows.append(icerik.label)  # başlık başka bölümün içine taşmış gibi
    fs = check_sections(u, muzik.schema_)
    assert any(f.check == "SECTION_LEAKAGE" and f.severity == Severity.FAIL for f in fs)
