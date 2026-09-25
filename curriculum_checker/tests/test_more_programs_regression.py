"""Biyoloji, Temel Dinî Bilgiler ve Arnavutça (Yaşayan Diller ve Lehçeler) regression testleri.

Beklenen değerler PDF'lerin kendisinden elle doğrulanmıştır. Kaynak PDF'deki gerçek
tutarsızlıklar (FAIL/NEEDS_REVIEW) da beklenen sonuç olarak sabitlenmiştir.
"""
import hashlib
import re

import pytest

from models import Severity, Status
from pdf_extract import norm_label

from conftest import SAMPLES


def _analyze(name):
    p = SAMPLES / f"{name}.pdf"
    if not p.exists():
        pytest.skip(f"samples/{name}.pdf yok")
    from validators import analyze_pdf

    return analyze_pdf(str(p))


@pytest.fixture(scope="module")
def biy():
    return _analyze("biyoloji")


@pytest.fixture(scope="module")
def tdb():
    return _analyze("temeldinibilgiler")


@pytest.fixture(scope="module")
def arn():
    return _analyze("arnavutca")


def unit_by(res, grade, order):
    for u in res.units:
        g = int(re.match(r"\s*(\d+)", u.context.text).group(1)) if u.context else None
        if g == grade and u.order == order:
            return u
    raise AssertionError((grade, order))


def checks(res, name, unit_id=None):
    return [f for f in res.findings if f.check == name and (unit_id is None or f.unit_id == unit_id)]


COMMON_CLEAN = ("SECTION_LEAKAGE", "UNASSIGNED_SPANS", "DOUBLE_ASSIGNED_SPANS", "TEXT_NOT_IN_SOURCE", "LO_COUNT_MISMATCH", "UNIT_COUNT_MISMATCH", "LO_TOTAL_MISMATCH", "MISSING_UNIT", "UNKNOWN_LABEL", "ORPHAN_LABEL", "LO_CODE_IDENTITY")


# ---------------------------------------------------------------- Biyoloji


def test_biyoloji_units_and_counts(biy):
    assert biy.schema_.structure_pages == [13, 14] and biy.schema_.lo_prefix == "BİY"
    got = [(u.context.text, u.order, len(u.learning_outcomes)) for u in biy.units]
    assert got == [
        ("9. SINIF", 1, 8), ("9. SINIF", 2, 6), ("10. SINIF", 1, 10), ("10. SINIF", 2, 9),
        ("11. SINIF", 1, 12), ("11. SINIF", 2, 10), ("12. SINIF", 1, 10), ("12. SINIF", 2, 10),
    ]
    assert biy.expected_lo_total == biy.extracted_lo_total == 75
    for name in COMMON_CLEAN + ("HOURS_MISMATCH", "MISSING_SECTION"):
        assert not checks(biy, name), name


def test_biyoloji_colored_grade_heading_is_context(biy):
    # "10. SINIF" beyaz değil renkli başlık; özet tablosu başlığıyla ("10. SINIF BİYOLOJİ DERSİ ...") eşleştiği için bağlamdır
    assert {u.context.text for u in biy.units} == {"9. SINIF", "10. SINIF", "11. SINIF", "12. SINIF"}


def test_biyoloji_colored_punctuation_does_not_close_unit(biy):
    # s.47: "amaçlanmaktadır" sonrasındaki "." kırmızı; tema kapanmamalı, nokta içerikte kalmalı
    u = unit_by(biy, 11, 1)
    assert len(u.sections) == 24 and len(u.learning_outcomes) == 12
    desc = u.sections[0].content
    assert desc.text.endswith("amaçlanmaktadır.") and "P47_S10" in desc.source_spans


def test_biyoloji_source_anomalies(biy):
    # s.55: BİY.11.1.10'un uygulama bloğu "BİY.11.10" başlığıyla (segment eksik) yazılmış;
    # bloğu önceki bloğa karıştırmadan ayrı alır ve iki yönde raporlar
    [f] = checks(biy, "APPLICATION_MISSING")
    assert f.details["code_raw"] == "BİY.11.1.10." and f.unit_id == unit_by(biy, 11, 1).id
    [f] = checks(biy, "APPLICATION_UNKNOWN_CODE")
    assert f.details["code_raw"] == "BİY.11.10"
    u = unit_by(biy, 11, 1)
    nine = next(b for b in u.applications if b.header.text == "BİY.11.1.9")
    assert "iskelet kaslarının kasılma" not in nine.body.text
    got = {(f.unit_id, f.details["code_raw"]) for f in checks(biy, "USED_NOT_DECLARED")}
    assert got == {(unit_by(biy, 11, 2).id, "E3.8"), (unit_by(biy, 11, 2).id, "E3.9")}
    # uygulama başlıkları tutarlı biçimde noktasız: yalnızca gerçekten sapan yazım uyarı alır
    assert [f.details["code_raw"] for f in checks(biy, "CODE_FORMAT_ANOMALY")] == ["BİY. 9.1.5", "BİY.11.10"]
    assert biy.status == Status.FAIL


# ---------------------------------------------------------------- Temel Dinî Bilgiler


def test_tdb_units_counts_and_status(tdb):
    assert tdb.schema_.unit_keyword == "ÜNİTE" and tdb.schema_.lo_prefix == "TDB"
    assert [(u.title.text, len(u.learning_outcomes)) for u in tdb.units] == [
        ("1. ÜNİTE: KENDİMİ, KÂİNATI VE ALLAH’I TANIYORUM", 2),
        ("2. ÜNİTE: YARATILIŞIN GAYESİ: ALLAH’A İMAN", 2),
        ("3. ÜNİTE: İMANIN MEYVESİ: İBADETLER", 3),
        ("4.ÜNİTE: İSLAM’IN ÖZÜ: GÜZEL AHLAK", 3),
    ]
    # tek sınıflı program: bağlam başlığı yok; belge bölüm başlığı bağlam sayılmaz
    assert all(u.context is None for u in tdb.units)
    for name in COMMON_CLEAN + ("UNIT_NAME_MISMATCH", "EXPECTED_ROW_AMBIGUOUS"):
        assert not checks(tdb, name), name
    assert tdb.status == Status.WARNING


def test_tdb_order_in_separate_unlabeled_cell(tdb):
    # s.11: sıra numarası ("1.") başlıksız ayrı hücrede, ad yanındaki hücrede
    rows = [(r.order, r.lo_count) for t in tdb.expected_tables for r in t.rows if r.order is not None]
    assert rows == [(1, 2), (2, 2), (3, 3), (4, 3)]
    assert tdb.expected_lo_total == 10


# ---------------------------------------------------------------- Arnavutça


def test_arn_structure_and_letter_segment_codes(arn):
    s = arn.schema_
    assert s.structure_pages == [25, 26] and s.lo_prefix == "ARN" and s.lo_segment_types == ["n", "n", "a"]
    assert len(arn.units) == 16
    assert arn.expected_lo_total == arn.extracted_lo_total == 112
    for u in arn.units:
        assert [lo.code.segments[-1] for lo in u.learning_outcomes] == ["D", "O", "K", "Y", "DBS", "SÖS", "SES"], u.id
    for name in COMMON_CLEAN + ("LO_SKILL_ORDER", "MISSING_SECTION"):
        assert not checks(arn, name), name


def test_arn_nonstandard_unit_title(arn):
    u = unit_by(arn, 7, 3)
    assert u.title.text == "TEMA 3: SEYAHAT" and u.name == "SEYAHAT"
    [f] = checks(arn, "UNIT_TITLE_FORMAT")
    assert f.unit_id == u.id and f.severity == Severity.NEEDS_REVIEW


def test_arn_subtitle_and_compound_label(arn):
    u = unit_by(arn, 5, 1)
    assert u.subtitle.text == "Alt Temalar: Kendimi Tanıtıyorum, Harfleri Tanıyorum, Benim Ailem"
    paths = [s.path for s in u.sections]
    # yapı sayfasında "İlkeler/ Anahtar Kavramlar/", tema sayfasında iki ayrı başlık
    assert paths[paths.index("İÇERİK ÇERÇEVESİ") + 1 : paths.index("İÇERİK ÇERÇEVESİ") + 3] == ["İlkeler", "Anahtar Kavramlar"]


def test_arn_label_text_variant(arn):
    # s.68: "Öğrenme-Öğretme Uygulamalar" (sondaki "ı" yok) -> öğrenilmiş başlığa eşlenir, NEEDS_REVIEW
    u = unit_by(arn, 5, 4)
    [f] = checks(arn, "LABEL_TEXT_VARIANT")
    assert f.unit_id == u.id and f.details["text"] == "Öğrenme-Öğretme Uygulamalar"
    assert any(s.path.endswith("Öğrenme-Öğretme Uygulamalar") and s.kind.value == "applications" for s in u.sections)
    assert not checks(arn, "APPLICATIONS_LABEL_MISSING")


def test_arn_unmarked_single_component(arn):
    lo = unit_by(arn, 5, 1).learning_outcomes[4]
    assert lo.code.raw == "ARN.5.1.DBS."
    assert lo.title.text == "ʻʻBen ve Sen” temasında sosyal etkileşim durumlarında temel ifadelere\nuygun dil bilgisi seçebilme ve kullanabilme"
    assert [(c.marker, c.text.text) for c in lo.components] == [
        ("", "Temaya uygun dil bilgisi yapılarını seçerek doğal, otantik ve otomatik bir şe-\nkilde kullanır.")
    ]


def test_arn_vertically_centered_content(arn):
    # s.143: içerik başlığa göre ortalanmış (ilk satır başlıktan ~6pt yukarıda) -> ALAN BECERİLERİ'ne ait
    u = unit_by(arn, 7, 2)
    secs = {s.path: s for s in u.sections}
    assert secs["DERS SAATİ"].content.text == "18"
    assert secs["ALAN BECERİLERİ"].content.text.startswith("YDAB1. Dinleme / İzleme-Anlamlandırma")
    # s.206: "1. Zenginleştirme Etkinliği" FARKLILAŞTIRMA'ya değil Zenginleştirme'ye ait
    u = unit_by(arn, 8, 2)
    secs = {s.path: s for s in u.sections}
    assert secs["FARKLILAŞTIRMA"].content is None
    assert secs["FARKLILAŞTIRMA > Zenginleştirme"].content.text.startswith("1.  Zenginleştirme Etkinliği: Market Alışverişi Yapma")
    assert not checks(arn, "GROUP_INCONSISTENT")


def test_arn_margin_notes_excluded(arn):
    notes = [r for r in arn.excluded_regions if r.heading is None]
    assert len(notes) == 16
    for u in arn.units:
        for s in u.sections:
            assert not (s.content and "bütüncül yaklaşıma" in s.content.text), (u.id, s.path)


def test_arn_misspelled_application_header_not_merged(arn):
    # s.122: "ARN.6.4.0." (O yerine sıfır) önceki bloğa karışmaz; ayrı blok + açık bulgular
    u = unit_by(arn, 6, 4)
    assert [b.header.text for b in u.applications] == ["ARN.6.4.D", "ARN.6.4.0.", "ARN.6.4.K", "ARN.6.4.Y", "ARN.6.4.DBS", "ARN.6.4.SÖS", "ARN.6.4.SES"]
    assert "Okuma" not in u.applications[0].body.text.split("\n")[-1]
    assert [f.details["code_raw"] for f in checks(arn, "APPLICATION_UNKNOWN_CODE")] == ["ARN.6.4.0."]
    assert [f.details["code_raw"] for f in checks(arn, "APPLICATION_MISSING")] == ["ARN.6.4.O."]


def test_arn_used_code_findings(arn):
    malformed = {(f.unit_id, f.details["code_raw"]) for f in checks(arn, "USED_CODE_MALFORMED")}
    assert malformed == {(unit_by(arn, 5, 2).id, "KB2,4"), (unit_by(arn, 6, 2).id, "SDB")}
    incomplete = {f.details["code_raw"] for f in checks(arn, "USED_CODE_INCOMPLETE")}
    assert incomplete == {"E1", "E3", "SDB1", "SDB3"}
    assert all(f.severity == Severity.NEEDS_REVIEW for f in checks(arn, "USED_CODE_INCOMPLETE") + checks(arn, "USED_CODE_MALFORMED"))
    undeclared = {f.details["code_raw"] for f in checks(arn, "USED_NOT_DECLARED")}
    assert undeclared == {"SDB2.6", "KAB2.5", "SBD2.1"}


def test_arn_source_inconsistencies(arn):
    # tema sayfalarında "DERS SAATİ 18", özet tablosunda 16 (7. ve 8. sınıf 3. ve 4. temalar)
    got = {f.unit_id for f in checks(arn, "HOURS_MISMATCH")}
    assert got == {unit_by(arn, g, t).id for g in (7, 8) for t in (3, 4)}
    letters = {f.details["code_raw"]: f.details["letters"] for f in checks(arn, "COMPONENT_LETTER_SEQUENCE")}
    assert letters == {"ARN.5.1.K.": ["a", "b", "c", "ç", "ç", "d"], "ARN.7.3.D.": ["a", "b", "c", "ç", "ç"]}
    assert arn.status == Status.FAIL


# ---------------------------------------------------------------- süreç bağımsızlığı


def test_results_do_not_depend_on_processing_order():
    # PyMuPDF find_tables() global "küçük glif yüksekliği" ayarını değiştirir; sonuç önceki
    # PDF'lerden etkilenmemeli.
    from validators import analyze_pdf

    p = str(SAMPLES / "arnavutca.pdf")
    if not (SAMPLES / "arnavutca.pdf").exists():
        pytest.skip("samples/arnavutca.pdf yok")
    first = hashlib.md5(analyze_pdf(p).model_dump_json().encode()).hexdigest()
    analyze_pdf(str(SAMPLES / "müzik.pdf"))
    second = hashlib.md5(analyze_pdf(p).model_dump_json().encode()).hexdigest()
    assert first == second
