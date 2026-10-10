"""İşaretli PDF ve göz ardı edilebilen kontroller."""
import fitz
import pytest

from models import Status

from conftest import SAMPLES

ARN = SAMPLES / "arnavutca.pdf"
DIN = SAMPLES / "dınornek.pdf"


@pytest.fixture(scope="module")
def arn():
    if not ARN.exists():
        pytest.skip("samples/arnavutca.pdf yok")
    from pdf_extract import extract_spans
    from pdf_locate import Locator
    from validators import analyze_pdf

    res = analyze_pdf(str(ARN))
    return res, Locator(res, extract_spans(res.source))


def test_ignore_hours_recomputes_status():
    if not DIN.exists():
        pytest.skip("samples/dınornek.pdf yok")
    from validators import analyze_pdf, ignore_checks

    res = analyze_pdf(str(DIN))
    assert res.status == Status.FAIL and [f.unit_id for f in res.findings if f.check == "HOURS_MISMATCH"] == ["U04"]
    ign = ignore_checks(res, {"HOURS_MISMATCH"})
    assert not [f for f in ign.findings if f.check == "HOURS_MISMATCH"]
    assert ign.status != Status.FAIL
    assert next(r for r in ign.unit_reports if r.unit_id == "U04").status != Status.FAIL
    # Kaynak sonuç değişmez; çıkarılan değerler aynı kalır
    assert res.status == Status.FAIL and any(f.check == "HOURS_MISMATCH" for f in res.findings)
    assert [r.extracted_hours for r in ign.unit_reports] == [r.extracted_hours for r in res.unit_reports]


def test_lo_count_checks_cannot_be_ignored(arn):
    from validators import ignore_checks

    res, _ = arn
    assert ignore_checks(res, {"LO_COUNT_MISMATCH", "LO_TOTAL_MISMATCH", "UNIT_COUNT_MISMATCH"}) is res


def test_hours_finding_points_to_hours_section(arn):
    res, L = arn
    f = next(f for f in res.findings if f.check == "HOURS_MISMATCH")
    loc = L.finding_loc(f)
    assert loc.found
    marked = {L.span[i].text.strip() for i in L.span if L.span[i].page in loc.rects and tuple(L.span[i].bbox) in loc.rects[L.span[i].page]}
    assert "18" in marked  # temadaki ders saati değeri (özet tablosunda 16)


def test_annotated_pdf_used_not_declared(arn):
    from pdf_annotate import build_annotated_pdf

    res, L = arn
    fs = [f for f in res.findings if f.check == "USED_NOT_DECLARED"]
    sdb = next(f for f in fs if f.details["code_raw"] == "SDB2.6")
    data = build_annotated_pdf(res, fs, L)
    out, orig = fitz.open(stream=data), fitz.open(str(ARN))
    assert len(out) == len(orig)  # sayfa eklenmez

    usage_page = next(p for p in L.finding_loc(sdb).rects)
    up = out[usage_page - 1]
    assert up.rect.width > orig[usage_page - 1].rect.width  # açıklama şeridi
    # PDF'nin kendi metni değişmez
    assert up.get_text("text", clip=orig[usage_page - 1].rect) == orig[usage_page - 1].get_text("text")
    hl = [a for a in up.annots() if a.type[0] == fitz.PDF_ANNOT_HIGHLIGHT and a.info["subject"] == "Tanımlanmamış kod kullanılmış"]
    assert any("SDB2.6" in a.info["content"] for a in hl)

    # Kanıt: temanın Sosyal-Duygusal tanım bölümü mavi işaretli, tanımlı SDB kodları yazılı; kutular bağlantılı
    ev = [
        (i + 1, a)
        for i, pg in enumerate(out)
        for a in pg.annots()
        if a.info["subject"] == "Tanım bölümü (kanıt)" and "SDB2.6" in a.info["content"]
    ]
    assert len(ev) == 1
    ev_page, a = ev[0]
    assert "Sosyal-Duygusal" in a.info["content"] and "SDB2.1" in a.info["content"]
    assert any(l["kind"] == fitz.LINK_GOTO and l["page"] == ev_page - 1 for l in up.get_links())
    assert any(l["kind"] == fitz.LINK_GOTO and l["page"] == usage_page - 1 for l in out[ev_page - 1].get_links())

    # Önek tanımı hiç olmayan kod (KAB2.5): tema başlığına not, aday bölüm seçilmez
    kab = [a for pg in out for a in pg.annots() if a.info["subject"] == "Tanım bölümü (kanıt)" and "KAB2.5" in a.info["content"]]
    assert len(kab) == 1 and "hiçbir tanım bölümünde KAB" in kab[0].info["content"]

    toc = out.get_toc()
    assert toc[0][1] == f"Program Kontrol bulguları ({len(fs)})"
    assert sum(1 for t in toc if t[0] == 3) == len(fs)


def test_annotated_pdf_all_findings_listed(arn):
    from pdf_annotate import build_annotated_pdf

    res, L = arn
    data = build_annotated_pdf(res, res.findings, L)
    out = fitz.open(stream=data)
    toc = out.get_toc()
    assert sum(1 for t in toc if t[0] == 3) == len(res.findings)


def test_turkish_labels_cover_all_checks():
    """Arayüz/raporlarda İngilizce kontrol kodu ve U01 gibi kimlik görünmez; iç kod yalnızca "Kod" sütunundadır."""
    import glob

    from excel_export import findings_df, units_df
    from labels_tr import CHECK_TR, unit_labels
    from validators import analyze_pdf

    pdfs = sorted(glob.glob(str(SAMPLES / "*.pdf")))
    if not pdfs:
        pytest.skip("örnek PDF yok")
    for p in pdfs:
        res = analyze_pdf(p)
        assert {f.check for f in res.findings} <= set(CHECK_TR), p
        labels = list(unit_labels(res).values())
        assert len(labels) == len(set(labels)), p  # birim adları tekil
        fdf = findings_df(res)
        assert not fdf["Kontrol"].isin(CHECK_TR.keys()).any() and set(fdf["Önem"]) <= {"Hata", "İnceleme gerekli", "Uyarı", "Bilgi"}
        assert list(fdf["Kod"]) == [f.check for f in res.findings]
        assert not units_df(res)["Birim"].str.fullmatch(r"U\d+").any()
