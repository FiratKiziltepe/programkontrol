"""Gemini yerleşim doğrulaması: karşılaştırma mantığı (API çağrısı yapılmaz, sahte yanıt kullanılır)."""
import pytest

import gemini_verify as gv

from conftest import SAMPLES


@pytest.fixture(scope="module")
def res():
    p = SAMPLES / "kimya.pdf"
    if not p.exists():
        pytest.skip("samples/kimya.pdf yok")
    from validators import analyze_pdf

    return analyze_pdf(str(p))


def _echo(res, pages):
    """Bizim çıkarımı birebir yansıtan sahte Gemini yanıtı (sayfa -> JSON)."""
    items = gv.extracted_page_items(res, pages)
    return {p: {k: [t for _, t in v] for k, v in kinds.items()} for p, kinds in items.items()}


def test_matching_layout_gives_no_findings(res):
    uid = res.units[0].id
    pages = gv.unit_pages(res, [uid])
    fake = _echo(res, pages)
    calls = iter(sorted(pages))
    rep = gv.verify(res, "model", [uid], asker=lambda png: fake[next(calls)])
    assert rep.pages == sorted(pages)
    assert rep.findings == []
    assert {c.status for c in rep.checks} == {"UYUMLU"}


def test_disagreements_become_needs_review_and_gemini_text_stays_out(res):
    uid = res.units[0].id
    pages = sorted(gv.unit_pages(res, [uid]))
    fake = _echo(res, pages)
    first = pages[0]
    lo_page = next(p for p in pages if fake[p]["learning_outcome_codes"])
    missing = fake[lo_page]["learning_outcome_codes"].pop(0)  # Gemini bir ÖÇ kodunu görmemiş
    fake[first]["section_headings"].append("GEMİNİ'NİN GÖRDÜĞÜ BAŞLIK")  # Gemini fazladan başlık görmüş
    calls = iter(pages)
    rep = gv.verify(res, "model", [uid], asker=lambda png: fake[next(calls)])
    got = {(f.check, f.details.get("extracted") or f.details.get("gemini_reported")) for f in rep.findings}
    assert got == {("GEMINI_NOT_CONFIRMED", missing), ("GEMINI_NOT_EXTRACTED", "GEMİNİ'NİN GÖRDÜĞÜ BAŞLIK")}
    assert all(f.severity.value == "NEEDS_REVIEW" for f in rep.findings)
    # Gemini'nin metni çıkarıma girmez
    assert all("GEMİNİ" not in (s.label.text if s.label else "") for u in res.units for s in u.sections)


def test_small_reading_differences_in_headings_tolerated_codes_exact():
    ours = {"section_headings": [("U01", "ÖĞRENME-ÖĞRETME UYGULAMALARI")], "learning_outcome_codes": [("U01", "KİM.9.1.1.")]}
    theirs = {"section_headings": ["OGRENME-ÖĞRETME UYGULAMALARI"], "learning_outcome_codes": ["KİM.9.1.2."], "unit_titles": [], "application_codes": []}
    checks, findings = gv.compare_page(5, ours, theirs, "U01")
    assert [c.status for c in checks if c.kind == "section_headings"] == ["UYUMLU"]
    assert {f.check for f in findings} == {"GEMINI_NOT_CONFIRMED", "GEMINI_NOT_EXTRACTED"}


def test_api_error_is_info_not_crash(res):
    uid = res.units[0].id

    def boom(png):
        raise RuntimeError("kota aşıldı")

    rep = gv.verify(res, "model", [uid], asker=boom)
    assert rep.findings and {f.check for f in rep.findings} == {"GEMINI_ERROR"}
    assert {f.severity.value for f in rep.findings} == {"INFO"}


def test_browser_responses_are_validated(res):
    # Tarayıcıdan dönen yanıt: JSON metni, hata veya bozuk içerik; yalnızca dört liste alınır
    uid = res.units[0].id
    pages = sorted(gv.unit_pages(res, [uid]))
    fake = _echo(res, pages)
    import json

    responses = {p: {"ok": json.dumps({**fake[p], "ekstra": ["yok sayılır"]})} for p in pages}
    responses[pages[-1]] = {"error": "HTTP 429: kota"}
    rep = gv.build_report(res, gv.DEFAULT_MODEL, [uid], responses)
    assert {f.check for f in rep.findings} == {"GEMINI_ERROR"}
    assert [c.gemini for c in rep.checks if c.status == "HATA"] == ["HTTP 429: kota"]
    assert all(set(v) == set(gv.KINDS) for v in rep.raw.values())
    imgs = gv.page_images(res.source, pages[:1])
    assert imgs[0]["page"] == pages[0] and len(imgs[0]["image"]) > 1000
