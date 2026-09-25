"""Gemini ile yerleşim (layout) doğrulaması — isteğe bağlı.

Kurallar (CLAUDE.md):
- Gemini yalnızca layout doğrulaması için kullanılır: tema sayfalarının görüntüsünde hangi birim
  başlıklarının, bölüm başlıklarının ve öğrenme çıktısı / uygulama bloğu kodlarının göründüğünü listeler.
- Gemini'nin döndürdüğü metin hiçbir zaman çıkarıma, Excel'in veri sayfalarına veya karşılaştırmaya
  girmez. Yalnızca bizim PDF'den çıkardığımız yapıyla karşılaştırılır; uyuşmazlık NEEDS_REVIEW bulgusu
  olur ve bulguda "Gemini'nin gördüğü" diye açıkça etiketlenir.
- Gemini çağrısı TARAYICIDA yapılır (gemini_component.py): kullanıcının API anahtarı yalnızca tarayıcı
  oturumunda kalır, sunucuya gönderilmez ve kaydedilmez. Sunucu yalnızca sayfa görüntülerini hazırlar ve
  tarayıcıdan dönen JSON yanıtlarını karşılaştırır.
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

import fitz

from models import ExtractionResult, Finding, Severity, Unit
from pdf_extract import norm_label, parse_code
from schema_detect import _edit_distance

PROMPT = """Bu görüntü bir Türkçe öğretim programı PDF'sinin tek bir sayfasıdır. Sayfanın YERLEŞİMİNİ
bildir; metni düzeltme, çevirme, tamamlama. Her öğeyi sayfada yazdığı gibi, yukarıdan aşağıya sırayla ver.

- unit_titles: "1. TEMA: …", "2. ÜNİTE: …", "3. ÖĞRENME ALANI: …" biçimindeki tema/ünite başlıkları.
- section_headings: sayfanın sol sütunundaki renkli bölüm başlıkları (ör. "DERS SAATİ", "ALAN BECERİLERİ",
  "ÖĞRENME ÇIKTILARI VE SÜREÇ BİLEŞENLERİ", "Köprü Kurma"). Birden çok satıra bölünmüş başlığı tek öğe yap.
  Gövde metnini, sayfa üst bilgisini ve sayfa numarasını ekleme.
- learning_outcome_codes: öğrenme çıktıları bölümünde çıktı başlığının başındaki kodlar (ör. "MAT.1.1.1.").
- application_codes: öğrenme-öğretme uygulamaları bölümünde her uygulama bloğunun başındaki kodlar.
Sayfada ilgili öğe yoksa boş liste ver."""

DEFAULT_MODEL = "gemini-3.5-flash-lite"
# Gemini REST API (v1beta generateContent) responseSchema biçimi
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "unit_titles": {"type": "ARRAY", "items": {"type": "STRING"}},
        "section_headings": {"type": "ARRAY", "items": {"type": "STRING"}},
        "learning_outcome_codes": {"type": "ARRAY", "items": {"type": "STRING"}},
        "application_codes": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["unit_titles", "section_headings", "learning_outcome_codes", "application_codes"],
}
KINDS = ("unit_titles", "section_headings", "learning_outcome_codes", "application_codes")
KIND_TR = {
    "unit_titles": "Birim başlığı",
    "section_headings": "Bölüm başlığı",
    "learning_outcome_codes": "Öğrenme çıktısı kodu",
    "application_codes": "Uygulama bloğu kodu",
}


def render_page(pdf_path: str, page: int, zoom: float = 1.5, quality: int = 70) -> bytes:
    with fitz.open(pdf_path) as doc:
        return doc[page - 1].get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("jpg", jpg_quality=quality)


def page_images(pdf_path: str, pages: Iterable[int]) -> list[dict]:
    """Tarayıcıya gönderilecek sayfa görüntüleri (JPEG, base64)."""
    return [{"page": p, "image": base64.b64encode(render_page(pdf_path, p)).decode("ascii")} for p in sorted(pages)]


def parse_response(raw) -> dict:
    """Tarayıcıdan dönen yanıtı (JSON metni veya sözlük) doğrular; beklenen dört liste dışında bir şey alınmaz."""
    data = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise ValueError("Gemini yanıtı JSON nesnesi değil")
    return {k: [str(x) for x in (data.get(k) or []) if str(x).strip()] for k in KINDS}


# ---------------------------------------------------------------- bizim çıkarımın sayfa bazında görünümü


def _page_of(field_) -> int | None:
    return field_.pages[0] if field_ is not None and field_.pages else None


def extracted_page_items(res: ExtractionResult, pages: Iterable[int]) -> dict[int, dict[str, list[tuple[str, str]]]]:
    """Sayfa -> tür -> [(birim, PDF'den çıkarılan metin)]. Başlık/kod, başladığı sayfaya yazılır."""
    wanted = set(pages)
    out: dict[int, dict[str, list[tuple[str, str]]]] = {p: {k: [] for k in KINDS} for p in wanted}

    def add(page, kind, uid, text):
        if page in wanted:
            out[page][kind].append((uid, text))

    for u in res.units:
        add(_page_of(u.title), "unit_titles", u.id, u.title.text.replace("\n", " "))
        for s in u.sections:
            if s.label is not None:
                add(_page_of(s.label), "section_headings", u.id, s.label.text.replace("\n", " "))
        for lo in u.learning_outcomes:
            add(_page_of(lo.header) or _page_of(lo.title), "learning_outcome_codes", u.id, lo.code.raw)
        for b in u.applications:
            if b.code is not None:
                add(_page_of(b.header), "application_codes", u.id, b.code.raw)
    return out


# ---------------------------------------------------------------- karşılaştırma


def _key(kind: str, text: str) -> str:
    if kind in ("learning_outcome_codes", "application_codes"):
        try:
            return parse_code(text).normalized
        except ValueError:
            return norm_label(text)
    return norm_label(text)


def _same(kind: str, a: str, b: str) -> bool:
    ka, kb = _key(kind, a), _key(kind, b)
    if ka == kb:
        return True
    if kind in ("section_headings", "unit_titles") and len(ka) >= 6:
        # Görüntüden okumada küçük harf farkları olabilir (ı/i, ş/s); kod karşılaştırması birebirdir
        return _edit_distance(ka, kb) <= max(1, len(ka) // 10)
    return False


@dataclass
class PageCheck:
    page: int
    unit_id: str | None
    kind: str
    status: str  # "UYUMLU" | "YALNIZCA_PDF_CIKARIMI" | "YALNIZCA_GEMINI" | "HATA"
    extracted: str | None = None
    gemini: str | None = None


@dataclass
class GeminiReport:
    model: str
    pages: list[int]
    checks: list[PageCheck] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    raw: dict[int, dict] = field(default_factory=dict)  # sayfa -> Gemini JSON (yalnızca inceleme için)


def compare_page(page: int, ours: dict[str, list[tuple[str, str]]], theirs: dict[str, list[str]], page_unit: str | None) -> tuple[list[PageCheck], list[Finding]]:
    checks: list[PageCheck] = []
    findings: list[Finding] = []
    for kind in KINDS:
        left = list(ours.get(kind, []))
        right = list(theirs.get(kind, []))
        used = [False] * len(right)
        for uid, text in left:
            j = next((j for j, g in enumerate(right) if not used[j] and _same(kind, text, g)), None)
            if j is not None:
                used[j] = True
                checks.append(PageCheck(page, uid, kind, "UYUMLU", text, right[j]))
            else:
                checks.append(PageCheck(page, uid, kind, "YALNIZCA_PDF_CIKARIMI", text, None))
                findings.append(
                    Finding(
                        severity=Severity.NEEDS_REVIEW,
                        check="GEMINI_NOT_CONFIRMED",
                        unit_id=uid,
                        message=f"{KIND_TR[kind]} PDF'den çıkarıldı ama Gemini sayfa görüntüsünde görmedi",
                        details={"page": page, "kind": kind, "extracted": text},
                    )
                )
        for j, g in enumerate(right):
            if used[j]:
                continue
            checks.append(PageCheck(page, page_unit, kind, "YALNIZCA_GEMINI", None, g))
            findings.append(
                Finding(
                    severity=Severity.NEEDS_REVIEW,
                    check="GEMINI_NOT_EXTRACTED",
                    unit_id=page_unit,
                    message=f"Gemini sayfa görüntüsünde bir {KIND_TR[kind].lower()} gördü; PDF çıkarımında bu sayfada karşılığı yok",
                    # Gemini'nin metni yalnızca incelemeye yardımcı bilgi olarak gösterilir, çıkarıma girmez
                    details={"page": page, "kind": kind, "gemini_reported": g},
                )
            )
    return checks, findings


def unit_pages(res: ExtractionResult, unit_ids: Iterable[str] | None = None) -> dict[int, str]:
    """Doğrulanacak sayfalar -> sayfanın ait olduğu birim."""
    ids = set(unit_ids) if unit_ids is not None else None
    out: dict[int, str] = {}
    for u in res.units:
        if ids is None or u.id in ids:
            for p in u.pages:
                out.setdefault(p, u.id)
    return out


def build_report(res: ExtractionResult, model: str, unit_ids: Iterable[str] | None, responses: dict[int, dict]) -> GeminiReport:
    """Tarayıcıdan dönen sayfa yanıtlarını ({sayfa: {"ok": JSON} | {"error": metin}}) çıkarımla karşılaştırır."""
    pages = unit_pages(res, unit_ids)
    report = GeminiReport(model=model, pages=sorted(pages))
    ours = extracted_page_items(res, pages)
    for page in report.pages:
        resp = responses.get(page) or responses.get(str(page)) or {"error": "yanıt yok"}
        try:
            if "error" in resp:
                raise RuntimeError(resp["error"])
            theirs = parse_response(resp["ok"])
        except Exception as e:  # ağ/kota/model/biçim hatası: analiz durmaz, bilgi olarak raporlanır
            report.checks.append(PageCheck(page, pages[page], "-", "HATA", None, _short_error(e)))
            report.findings.append(
                Finding(severity=Severity.INFO, check="GEMINI_ERROR", unit_id=pages[page], message="Gemini bu sayfayı doğrulayamadı", details={"page": page, "error": _short_error(e)})
            )
            continue
        report.raw[page] = theirs
        c, f = compare_page(page, ours[page], theirs, pages[page])
        report.checks += c
        report.findings += f
    return report


def verify(res: ExtractionResult, model: str, unit_ids: Iterable[str] | None, asker: Callable[[bytes], dict]) -> GeminiReport:
    """Sunucu tarafında sahte/yerel yanıtla doğrulama (testler için). Gerçek çağrı tarayıcıdadır."""
    responses: dict[int, dict] = {}
    for page in unit_pages(res, unit_ids):
        try:
            responses[page] = {"ok": asker(render_page(res.source, page))}
        except Exception as e:
            responses[page] = {"error": _short_error(e)}
    return build_report(res, model, unit_ids, responses)


def _short_error(e: Exception) -> str:
    msg = str(e) if isinstance(e, RuntimeError) else f"{type(e).__name__}: {e}"
    return re.sub(r"\s+", " ", msg)[:300]
