"""Arayüz ve raporlarda gösterilen Türkçe adlar.

İç kodlar (FAIL, USED_NOT_DECLARED, U01, PDF_DE_VAR_EXCELDE_YOK …) testlerde, eşleştirmede ve renklendirmede
kullanılmaya devam eder; burada yalnızca GÖSTERİM karşılıkları vardır. Bilinmeyen kod olduğu gibi gösterilir.
"""
from __future__ import annotations

from models import ExtractionResult, Unit

SEVERITY_ORDER = ["FAIL", "NEEDS_REVIEW", "WARNING", "INFO"]
SEVERITY_TR = {"FAIL": "Hata", "NEEDS_REVIEW": "İnceleme gerekli", "WARNING": "Uyarı", "INFO": "Bilgi"}
STATUS_TR = {"PASS": "Geçti", "WARNING": "Uyarılarla geçti", "NEEDS_REVIEW": "İnceleme gerekli", "FAIL": "Hata"}

# Kontrol adları (bulgunun ayrıntılı açıklaması ayrıca "Açıklama" sütununda durur)
CHECK_TR = {
    # sayılar / süre tablosu
    "LO_COUNT_MISMATCH": "ÖÇ sayısı tabloyla uyuşmuyor",
    "LO_TOTAL_MISMATCH": "Program ÖÇ toplamı tabloyla uyuşmuyor",
    "UNIT_COUNT_MISMATCH": "Tema/ünite sayısı tabloyla uyuşmuyor",
    "MISSING_UNIT": "Tablodaki tema/ünite PDF'de bulunamadı",
    "HOURS_MISMATCH": "Ders saati tabloyla uyuşmuyor",
    "HOURS_NOT_FOUND": "Ders saati bulunamadı",
    "HOURS_UNREADABLE": "Ders saati okunamadı",
    "EXPECTED_COUNT_MISSING": "Beklenen ÖÇ sayısı bilinmiyor",
    "EXPECTED_COUNT_UNREADABLE": "Tablodaki ÖÇ sayısı okunamadı",
    "EXPECTED_HOURS_MISSING": "Tabloda ders saati yok",
    "EXPECTED_ROW_AMBIGUOUS": "Tablo satırı tekil eşleşmedi",
    "EXPECTED_TABLE_AMBIGUOUS": "Özet tablosu tekil eşleşmedi",
    "EXPECTED_TABLE_NOT_FOUND": "Özet/süre tablosu bulunamadı",
    "EXPECTED_TABLE_UNMATCHED": "Özet tablosu eşleştirilemedi",
    "EXPECTED_TOTAL_UNKNOWN": "Program toplamı karşılaştırılamadı",
    "TABLE_TOTAL_INCONSISTENT": "Tablo toplamı satırlarla tutmuyor",
    "UNIT_NAME_MISMATCH": "Tablodaki ad tema başlığından farklı",
    # sınırlı süre tabloları
    "LIMITED_LO_COUNT_MISMATCH": "Sınırlı tablo ÖÇ sayısı listeyle uyuşmuyor",
    "LIMITED_LO_NOT_FOUND": "Listedeki ÖÇ temada yok",
    "LIMITED_ROW_AMBIGUOUS": "Sınırlı tablo satırı tekil değil",
    "LIMITED_TABLE_AMBIGUOUS": "Sınırlı tablo tekil eşleşmedi",
    "LO_LIST_UNPARSED": "ÖÇ listesinde okunamayan satır",
    # bölümler
    "MISSING_SECTION": "Bölüm başlığı eksik",
    "DUPLICATE_SECTION": "Bölüm başlığı tekrarlı",
    "SECTION_ORDER": "Bölüm sırası farklı",
    "SECTION_LEAKAGE": "Bölüm içinde başka bölüm başlığı",
    "EMPTY_SECTION": "Bölüm boş",
    "UNKNOWN_LABEL": "Yapı sayfasında olmayan başlık",
    "LABEL_TEXT_VARIANT": "Bölüm başlığı farklı yazılmış",
    "ORPHAN_LABEL": "Tema dışında bölüm başlığı",
    "GROUP_HAS_CONTENT": "Üst başlığın altında içerik var",
    "GROUP_STYLE_VARIANT": "Başlık hiyerarşisi farklı",
    "APPLICATIONS_LABEL_MISSING": "Uygulamalar başlığı eksik",
    "UNIT_TITLE_FORMAT": "Tema başlığı biçimi farklı",
    # öğrenme çıktıları
    "LO_CODE_IDENTITY": "ÖÇ kodu tema/sırayla uyuşmuyor",
    "DUPLICATE_LO_CODE": "ÖÇ kodu tekrarlı",
    "LO_SECTION_NOT_FOUND": "Öğrenme çıktıları bölümü yok",
    "LO_TITLE_EMPTY": "ÖÇ başlığı boş",
    "LO_SKILL_ORDER": "ÖÇ kısaltma sırası farklı",
    "COMPONENT_LETTER_SEQUENCE": "Süreç bileşeni harf sırası bozuk",
    "UNPARSED_TEXT": "ÖÇ bölümünde koda bağlanamayan metin",
    # uygulamalar
    "APPLICATION_MISSING": "ÖÇ'nün uygulaması yok",
    "APPLICATION_DUPLICATE": "ÖÇ'nün birden çok uygulaması var",
    "APPLICATION_UNKNOWN_CODE": "Uygulama temada olmayan ÖÇ'ye ait",
    "APPLICATION_EMPTY": "Uygulama bloğu boş",
    "APPLICATION_ORDER": "Uygulama sırası ÖÇ sırasından farklı",
    "UNATTACHED_APPLICATION_TEXT": "Uygulamada ÖÇ'ye bağlanamayan metin",
    # kod çapraz kontrolü
    "USED_NOT_DECLARED": "Tanımlanmamış kod kullanılmış",
    "DECLARED_NOT_USED": "Tanımlanmış kod kullanılmamış",
    "USED_CODE_INCOMPLETE": "Eksik yazılmış kod",
    "USED_CODE_MALFORMED": "Bozuk yazılmış kod",
    "CODE_FORMAT_ANOMALY": "Kod yazım biçimi farklı",
    "DECLARATION_NAME_MISSING": "Tanımda kod adı yok",
    "DECLARATION_UNPARSED_CODE": "Tanımda okunamayan kod",
    # yapı / metin sadakati
    "STRUCTURE_PAGE_NOT_FOUND": "Program yapısı sayfası bulunamadı",
    "MANUAL_SCHEMA": "Yapı elle verildi",
    "CONTROL_CHARS_REMOVED": "Görünmez karakterler atıldı",
    "DOUBLE_ASSIGNED_SPANS": "Metin iki bölüme atanmış",
    "UNASSIGNED_SPANS": "Bölüme atanmamış metin",
    "NO_SOURCE_SPANS": "Metnin PDF kaynağı yok",
    "TEXT_NOT_IN_SOURCE": "Metin PDF kaynağında birebir yok",
    "GEMINI_ERROR": "Gemini doğrulayamadı",
}

# Bulgu ayrıntısındaki anahtarlar
DETAIL_TR = {
    "code_raw": "Kod",
    "code": "Kod",
    "in_application_of": "Uygulama bloğu",
    "category": "Bölüm",
    "expected": "Beklenen",
    "extracted": "Bulunan",
    "found": "Bulunan",
    "diff": "Fark",
    "letters": "Harfler",
    "labels": "Başlıklar",
    "table": "Özet tablodaki ad",
    "unit_name": "Tema başlığındaki ad",
    "title": "Başlık",
    "text": "Metin",
    "where": "Yer",
    "dominant_format": "Baskın biçim",
    "previous_section": "Önceki bölüm",
    "first_code_row": "İlk kod satırı",
    "section": "Bölüm",
    "label": "Başlık",
    "count": "Adet",
    "pages": "Sayfalar",
    "raw": "Ham değer",
    "candidates": "Aday sayısı",
    "table_page": "Tablo sayfası",
    "page": "Sayfa",
    "normalized": "Normalize",
    "entry": "Tanım girdisi",
    "error": "Hata",
    "lo_prefix": "ÖÇ kodu öneki",
}
SKIP_DETAILS = {"spans", "label_spans", "matched_label_norm"}

SECTION_KIND_TR = {
    "unit_description": "Tema açıklaması",
    "group": "Üst başlık",
    "declaration": "Kod tanımı",
    "learning_outcomes": "Öğrenme çıktıları",
    "applications": "Uygulamalar",
    "other": "Diğer",
}

# 4. sekme (öğe bazında karşılaştırma) durumları
CMP_TR = {
    "AYNI": "Aynı",
    "SADECE_BİÇİM_FARKI": "Yalnızca biçim farkı",
    "PDF_DE_VAR_EXCELDE_YOK": "PDF'de var, Excel'de yok",
    "EXCELDE_VAR_PDF_DE_YOK": "Excel'de var, PDF'de yok",
    "YANLIŞ_BÖLÜM": "Yanlış bölüm",
    "KOD_FARKLI": "Kod farklı",
    "METİN_FARKLI": "Metin farklı",
    "SAYI_FARKLI": "Sayı farklı",
    "İNCELEME_GEREKLİ": "İnceleme gerekli",
    "KAPSAM_DIŞI": "Kapsam dışı",
}


def check_tr(code: str) -> str:
    return CHECK_TR.get(code, code)


def detail_text(details: dict, limit: int = 400) -> str:
    def fmt(v) -> str:
        return ", ".join(map(str, v)) if isinstance(v, (list, tuple, set)) else str(v)

    s = "; ".join(f"{DETAIL_TR.get(k, k)}: {fmt(v)}" for k, v in details.items() if k not in SKIP_DETAILS and v not in (None, "", []))
    return s.replace("\n", " ")[:limit]


def _short(u: Unit) -> str:
    title = u.title.text.replace("\n", " ").strip()
    head = title.split(":", 1)[0].strip() if u.name and ":" in title else title  # "1. TEMA: MÜZİK DİLİ" -> "1. TEMA"
    ctx = u.context.text.replace("\n", " ").strip() if u.context else ""
    return f"{ctx} · {head}" if ctx else head


def unit_labels(res: ExtractionResult) -> dict[str, str]:
    """Birim kimliği (U01 …) -> PDF'deki bağlam ve numara (ör. "6. SINIF · 1. TEMA"). Metinler PDF'den birebir;
    kısa ad iki birimde aynı çıkarsa o birimlerde tam başlık kullanılır."""
    short = {u.id: _short(u) for u in res.units}
    seen: dict[str, int] = {}
    for v in short.values():
        seen[v] = seen.get(v, 0) + 1
    out = {}
    for u in res.units:
        if seen[short[u.id]] == 1:
            out[u.id] = short[u.id]
        else:
            ctx = u.context.text.replace("\n", " ").strip() if u.context else ""
            title = u.title.text.replace("\n", " ").strip()
            out[u.id] = f"{ctx} · {title}" if ctx else title
    return out
