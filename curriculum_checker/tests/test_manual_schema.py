"""Parçalı birim başlıkları ve elle verilen program yapısı (SchemaOverrides) testleri."""
import pytest

from manual_schema import _parse_pages
from models import SchemaOverrides, Severity
from schema_detect import SchemaError, keyword_of_example, lo_code_from_example

from conftest import SAMPLES

DIN = SAMPLES / "dınornek.pdf"
_cache: dict = {}


def res(name, ov=None):
    key = (name, ov.model_dump_json() if ov else "")
    if key not in _cache:
        p = SAMPLES / f"{name}.pdf"
        if not p.exists():
            pytest.skip(f"samples/{name}.pdf yok")
        from validators import analyze_pdf

        _cache[key] = analyze_pdf(str(p), ov)
    return _cache[key]


def shape(r):
    return (
        [u.title.text for u in r.units],
        [[lo.code.raw for lo in u.learning_outcomes] for u in r.units],
        [[s.label.text if s.label else None for s in u.sections] for u in r.units],
    )


def test_title_split_into_spans_is_recognized():
    # Din Hizmetleri s.14: "1. ÜNİTE: " (Medium) + "DİN HİZMETLERİ VE İLETİŞİM" (Bold) ayrı parçalar;
    # yapı sayfasında (s.12-13) örnek kod "HMU.11.1.1." başlık renginde iki başlık satırının arasında.
    r = res("dınornek")
    assert r.schema_.unit_keyword == "ÜNİTE" and r.schema_.structure_pages == [12, 13] and r.schema_.lo_prefix == "HMU"
    assert [u.title.text for u in r.units] == [
        "1. ÜNİTE: DİN HİZMETLERİ VE İLETİŞİM",
        "2. ÜNİTE: DİNÎ HİTABET UYGULAMALARI",
        "3. ÜNİTE: TESBİHAT VE DUALAR",
        "4. ÜNİTE: DİNÎ MERASİMLER",
    ]
    assert r.expected_lo_total == r.extracted_lo_total == 9
    assert "ÖĞRENME ÇIKTILARI VE SÜREÇ BİLEŞENLERİ" in [l.text for l in r.schema_.labels]
    # s.27 ders saati 20, özet tablosunda 18: kaynak PDF tutarsızlığı
    assert {(f.check, f.unit_id) for f in r.findings if f.severity in (Severity.FAIL, Severity.NEEDS_REVIEW)} == {("HOURS_MISMATCH", "U04")}


@pytest.mark.parametrize("name", ["dınornek", "kimya", "hayalbilgisi", "arnavutca"])
def test_example_based_detection_matches_auto(name):
    auto = res(name)
    ov = SchemaOverrides(
        unit_title_example=auto.units[0].title.text.replace("\n", " "),
        lo_code_example=auto.units[0].learning_outcomes[0].code.raw,
    )
    manual = res(name, ov)
    assert shape(manual) == shape(auto)
    assert [f.check for f in manual.findings if f.check == "MANUAL_SCHEMA"] == ["MANUAL_SCHEMA"]


def test_structure_and_start_page_overrides():
    auto = res("dınornek")
    r = res("dınornek", SchemaOverrides(structure_pages=[12, 13], data_start_page=14))
    assert shape(r) == shape(auto) and r.schema_.data_start_page == 14


def test_wrong_examples_give_clear_errors():
    with pytest.raises(SchemaError, match="bulunamadı"):
        res("dınornek", SchemaOverrides(unit_title_example="1. ÜNİTE: BÖYLE BİR BAŞLIK YOK"))
    with pytest.raises(SchemaError, match="biçiminde"):
        keyword_of_example("DİN HİZMETLERİ")
    with pytest.raises(SchemaError, match="biçiminde"):
        lo_code_from_example("HMU")


def test_example_parsers():
    assert keyword_of_example("1. ÜNİTE: DİN HİZMETLERİ VE İLETİŞİM") == "ÜNİTE"
    assert keyword_of_example("3. ÖĞRENME ALANI: AİLEM VE TOPLUM") == "ÖĞRENME ALANI"
    assert keyword_of_example("TEMA 3: SEYAHAT") == "TEMA"
    assert lo_code_from_example("HMU.11.1.1.") == ("HMU", ["n", "n", "n"])
    assert lo_code_from_example("ARN.5.1.D.") == ("ARN", ["n", "n", "a"])
    assert _parse_pages("12-13, 15") == [12, 13, 15] and _parse_pages("12-x") is None and _parse_pages("") is None
