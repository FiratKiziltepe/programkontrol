"""PDF'den bağımsız yardımcı fonksiyon testleri."""
import pytest

from models import Code
from pdf_extract import compare_key, lo_code_regex, norm_label, parse_code
from unit_extract import _declaration_entries, extract_used_codes
from validators import _covers


@pytest.mark.parametrize(
    "raw, normalized",
    [
        ("MÜZ.5.1.6.", "MÜZ.5.1.6"),
        ("MÜZ. 5.1.6.", "MÜZ.5.1.6"),
        ("MÜZ 5.1.3.", "MÜZ.5.1.3"),
        ("MÜZ.1.2.1", "MÜZ.1.2.1"),
        ("D11.2", "D11.2"),
        ("SAB9.", "SAB9"),
        ("KB2.13.", "KB2.13"),
    ],
)
def test_parse_code_keeps_raw_and_normalizes(raw, normalized):
    c = parse_code(raw)
    assert c.raw == raw
    assert c.normalized == normalized


def test_code_variants_share_key():
    keys = {parse_code(r).key for r in ("MÜZ.5.1.3.", "MÜZ. 5.1.3.", "MÜZ 5.1.3.", "MÜZ.5.1.3")}
    assert keys == {("MÜZ", ("5", "1", "3"))}


def test_lo_code_regex_variants():
    rx = lo_code_regex("MÜZ", ["n", "n", "n"])
    for t in ("MÜZ.5.1.6. Müzik yazısını çözümleyebilme", "MÜZ. 5.1.6. ", "MÜZ 5.1.3.", "MÜZ.7.2.10."):
        assert rx.match(t), t
    for t in ("MÜZİK DERSİ", "MÜZ.5.1 eksik", "Bu MÜZ.5.1.3. satır başında değil"):
        assert not rx.match(t), t


def test_compare_key_does_not_touch_raw():
    raw = "Müziksel Ha-\nreket Becerisi"
    assert compare_key(raw) == "Müziksel Hareket Becerisi"
    assert raw == "Müziksel Ha-\nreket Becerisi"
    assert compare_key("öğrenme-\nöğretme") == compare_key("öğrenme-öğretme")
    assert compare_key("a)    İstiklâl") == "a) İstiklâl"


def test_norm_label_matches_pdf_variants():
    assert norm_label("Sosyal Duygusal Öğrenme Becerileri") == norm_label("Sosyal-Duygusal Öğrenme Becerileri")
    assert norm_label("DERS SAATİ") == norm_label("Ders Saati")
    assert norm_label("ÖĞRENME KANITLARI (Ölçme ve Değerlendirme)") == norm_label("ÖĞRENME\nKANITLARI\n(Ölçme ve\nDeğerlendirme)")
    assert norm_label("Değerler") != norm_label("Değerlendirme")


def test_hierarchical_cover():
    assert _covers(parse_code("D11"), parse_code("D11.2"))
    assert _covers(parse_code("E1.1"), parse_code("E1.1"))
    assert not _covers(parse_code("D11.2"), parse_code("D11"))
    assert not _covers(parse_code("D1"), parse_code("D11"))
    assert not _covers(parse_code("E1.1"), parse_code("E1.6"))
    assert not _covers(parse_code("SB1"), parse_code("SAB1"))


def test_declaration_entries():
    t = "E1.1. Merak, E1.4. Kendine İnanma (Öz Yeterlilik), E1.5. Kendine Güvenme (Öz Güven), \nE3.2. Odaklanma"
    e = _declaration_entries(t)
    assert [x[2] for x in e] == ["E1.1.", "E1.4.", "E1.5.", "E3.2."]
    assert _declaration_entries("Türkçe, Hayat Bilgisi, Beden Eğitimi") == []
    assert _declaration_entries("18") == []


def test_extract_used_codes():
    t = "sorular sorulur (E1.1). Fikir birliğine varılır (D11.2, D14.3,\nD19.1). MÜZ.1.1.2 ile A4 kağıt kullanılır."
    codes = [c.normalized for c in extract_used_codes(t, {"D", "E"}, "MÜZ")]
    assert codes == ["E1.1", "D11.2", "D14.3", "D19.1"]
    # parantez içindeki bilinmeyen önek de alınır (tanımsız kullanım yakalanabilsin)
    assert [c.raw for c in extract_used_codes("(XY3.1)", set(), "MÜZ")] == ["XY3.1"]


def test_letter_segment_lo_codes():
    # Arnavutça: son segment alan becerisi kısaltması (ARN.5.1.D., ARN.5.3. SÖS)
    rx = lo_code_regex("ARN", ["n", "n", "a"])
    for t in ("ARN.5.1.D.", "ARN.5.1.DBS. metin", "ARN.5.3. SÖS", "ARN.5.1.SES"):
        assert rx.match(t), t
    assert not rx.match("ARN.5.1.1.")
    c = parse_code("ARN.5.3. SÖS")
    assert c.raw == "ARN.5.3. SÖS" and c.normalized == "ARN.5.3.SÖS" and c.segments == ["5", "3", "SÖS"]
    assert parse_code("ARN.5.3.SÖS").key == c.key
