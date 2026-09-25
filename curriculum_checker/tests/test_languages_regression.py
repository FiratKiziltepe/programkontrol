"""Yaşayan Diller ve Lehçeler: Abazaca, Adigece, Zazaca, Lazca, Kurmanca regression testleri.

Her programın FAIL/NEEDS_REVIEW bulgu kümesi PDF'de tek tek doğrulanmış kaynak
tutarsızlıklarıdır; beklenen sonuç olarak sabitlenmiştir.
"""
import re

import pytest

from models import Severity, Status

from conftest import SAMPLES

LANGS = ("abazaca", "adigece", "zazaca", "lazca", "kurmanca")
_cache: dict = {}


def res(name):
    if name not in _cache:
        p = SAMPLES / f"{name}.pdf"
        if not p.exists():
            pytest.skip(f"samples/{name}.pdf yok")
        from validators import analyze_pdf

        _cache[name] = analyze_pdf(str(p))
    return _cache[name]


def gt(r, u):
    return (int(re.match(r"\s*(\d+)", u.context.text).group(1)), u.order)


def unit_by(r, grade, order):
    return next(u for u in r.units if gt(r, u) == (grade, order))


def blocking(r):
    """(bulgu, (sınıf, tema), ayrıntı) kümesi — WARNING hariç."""
    ids = {u.id: gt(r, u) for u in r.units}
    return {
        (f.check, ids.get(f.unit_id), f.details.get("code_raw") or f.details.get("text") or str(f.details.get("labels")))
        for f in r.findings
        if f.severity != Severity.WARNING
    }


CLEAN = ("SECTION_LEAKAGE", "UNASSIGNED_SPANS", "DOUBLE_ASSIGNED_SPANS", "TEXT_NOT_IN_SOURCE", "UNKNOWN_LABEL", "ORPHAN_LABEL", "MISSING_UNIT", "UNIT_COUNT_MISMATCH", "GROUP_HAS_CONTENT")


@pytest.mark.parametrize("name", LANGS)
def test_structure_units_and_contexts(name):
    r = res(name)
    assert r.schema_.lo_segment_types == ["n", "n", "a"]
    assert len(r.units) == 16 and r.expected_lo_total == 112
    assert [u.context.text for u in r.units[::4]] == ["5. SINIF (A1.1)", "6. SINIF (A1.1)", "7. SINIF (A1.2)", "8. SINIF (A1.2)"]
    for c in CLEAN:
        assert not [f for f in r.findings if f.check == c], (name, c)


def test_abazaca_findings():
    r = res("abazaca")
    # s.83: yarım kalmış ikinci "ABZ.6.2.D." başlığı (bileşensiz ÖÇ tek başına bulgu değildir); K bileşenleri "a) a) b) ç) c) d)"; s.158 "E,2.4"
    assert blocking(r) == {
        ("LO_COUNT_MISMATCH", (6, 2), "None"),
        ("DUPLICATE_LO_CODE", (6, 2), "None"),
        ("COMPONENT_LETTER_SEQUENCE", (6, 2), "ABZ.6.2.K."),
        ("APPLICATION_ORDER", (6, 2), "None"),
        ("LO_SKILL_ORDER", (6, 2), "None"),
        ("USED_CODE_MALFORMED", (7, 4), "E,2.4"),
        ("LO_TOTAL_MISMATCH", None, "None"),
    }
    # s.178: tek süreç bileşeni italik değil düz "Light" basılmış; yine de başlıktan ayrılır
    lo = next(lo for lo in unit_by(r, 8, 2).learning_outcomes if lo.code.segments[-1] == "DBS")
    assert lo.title.text.endswith("seçebilme - kullanabilme")
    assert [c.text.text for c in lo.components] == ["Temaya uygun dil bilgisi yapılarını seçerek doğal, otantik ve otomatik bir\nşekilde kullanır."]


def test_adigece_findings():
    r = res("adigece")
    # s.66 "ADG.5.4." (kısaltma eksik); 3 temada ÖĞRENME-ÖĞRETME YAŞANTILARI başlığı hiç basılmamış
    assert blocking(r) == {
        ("APPLICATION_MISSING", (5, 4), "ADG.5.4.D."),
        ("APPLICATION_UNKNOWN_CODE", (5, 4), "ADG.5.4."),
        ("MISSING_SECTION", (7, 3), "['ÖĞRENME-ÖĞRETME YAŞANTILARI']"),
        ("MISSING_SECTION", (8, 2), "['ÖĞRENME-ÖĞRETME YAŞANTILARI']"),
        ("MISSING_SECTION", (8, 4), "['ÖĞRENME-ÖĞRETME YAŞANTILARI']"),
    }
    # s.47: FARKLILAŞTIRMA bu temada Medium (diğerlerinde Bold) -> çoğunluk yapısı, WARNING
    u = unit_by(r, 5, 2)
    assert "FARKLILAŞTIRMA > Zenginleştirme" in [s.path for s in u.sections]
    assert [f.unit_id for f in r.findings if f.check == "GROUP_STYLE_VARIANT"] == [u.id]
    # başlığı eksik temada alt başlıklara PDF'de olmayan üst başlık yolu eklenmez
    assert "Temel Kabuller" in [s.path for s in unit_by(r, 7, 3).sections]


def test_zazaca_findings():
    r = res("zazaca")
    # gövde metni #221F1F ve #231F20 tonlarıyla karışık basılmış: ikisi de gövde
    assert {0x221F1F, 0x231F20} <= set(r.schema_.body_colors)
    assert len(r.schema_.labels) == 23
    assert not {l.color for l in r.schema_.labels} & set(r.schema_.body_colors)
    # s.69: "6. SINIF (" #FFFFFF, "A1.1" #FEFEFE, ")" #FFFFFF -> tek bağlam
    assert unit_by(r, 6, 1).context.text == "6. SINIF (A1.1)"
    # s.26 "ZAZ.5.1.0." (O yerine sıfır) ayrı çıktı; önceki çıktıya karışmaz
    u = unit_by(r, 5, 1)
    assert [lo.code.raw for lo in u.learning_outcomes][:2] == ["ZAZ.5.1.D.", "ZAZ.5.1.0."]
    assert [c.letter for c in u.learning_outcomes[0].components] == ["a", "b", "c", "ç"]
    assert blocking(r) == {
        ("LO_CODE_IDENTITY", (5, 1), "ZAZ.5.1.0."),
        ("APPLICATION_MISSING", (5, 1), "ZAZ.5.1.0."),
        ("APPLICATION_UNKNOWN_CODE", (5, 1), "ZAZ.5.1.O"),
        ("LO_SKILL_ORDER", (5, 1), "None"),
        ("LABEL_TEXT_VARIANT", (7, 1), "Öğrenme-Öğreme  Uygulamaları"),
        ("LABEL_TEXT_VARIANT", (7, 3), "Öğrene-Öğretme  Uygulamaları"),
        ("USED_CODE_MALFORMED", (6, 2), "D16,1"),
    }


def test_lazca_findings():
    r = res("lazca")
    assert blocking(r) == {
        ("APPLICATION_MISSING", (6, 2), "LAZ.6.2.DBS."),
        ("APPLICATION_UNKNOWN_CODE", (6, 2), "LAZ.6.2."),
        ("LABEL_TEXT_VARIANT", (8, 1), "ÖĞRENME-ÖĞRETME  YAŞANTILAR"),
    }
    # s.106 "LAZ.6.2." başlığı altındaki DBS uygulaması Y bloğuna karışmaz
    u = unit_by(r, 6, 2)
    heads = [b.header.text for b in u.applications]
    assert heads.index("LAZ.6.2.") == heads.index("LAZ.6.2.Y.") + 1


def test_kurmanca_findings():
    r = res("kurmanca")
    # yapı sayfasında "ÖĞRENME-ÖĞRETME YAŞANTILARI" (Bold) + "Temel Kabuller" (Medium) ayrı başlık
    assert "Temel Kabuller" in [l.text for l in r.schema_.labels]
    missing = {(7, 2), (7, 3), (7, 4), (8, 1), (8, 2), (8, 3), (8, 4)}
    assert blocking(r) == (
        {("MISSING_SECTION", k, "['ÖĞRENME-ÖĞRETME YAŞANTILARI']") for k in missing}
        | {
            ("COMPONENT_LETTER_SEQUENCE", (6, 1), "KUR.6.1.D."),
            ("DECLARATION_NAME_MISSING", (7, 1), "KB2.14"),
            ("DECLARATION_NAME_MISSING", (8, 1), "KB2.14"),
            ("USED_CODE_INCOMPLETE", (7, 2), "SDB2"),
            ("USED_CODE_INCOMPLETE", (8, 2), "SDB2"),
        }
    )
    # "KB2.13. Yapılandırma, KB2.14, KB2.15. ...": adı olmayan kod yine de tanımlı; kullanımı FAIL değil
    assert not [f for f in r.findings if f.check == "USED_NOT_DECLARED"]
    assert r.status == Status.NEEDS_REVIEW
