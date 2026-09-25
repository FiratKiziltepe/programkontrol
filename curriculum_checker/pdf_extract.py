"""PDF'den span + layout çıkarımı ve metin yardımcıları.

Ana yöntem page.get_text("dict"); düz metin parser'ı kullanılmaz.
Metin hiçbir şekilde düzeltilmez: yalnızca span'lar görsel satırlara dizilir.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import fitz  # PyMuPDF

from models import Code, Span, TextField

# ---------------------------------------------------------------- span çıkarımı


@dataclass
class PdfDoc:
    path: str
    page_count: int
    page_sizes: dict[int, tuple[float, float]]
    spans: list[Span]
    furniture: set[str]  # sayfa üst/alt bilgisi, sayfa numarası span id'leri
    removed_controls: dict[int, int] = field(default_factory=dict)  # sayfa -> atılan görünmez kontrol karakteri sayısı

    def page_spans(self, page: int) -> list[Span]:
        return [s for s in self.spans if s.page == page]


def extract_spans(path: str) -> PdfDoc:
    # PyMuPDF'in find_tables() çağrısı global "küçük glif yüksekliği" ayarını açık bırakabiliyor;
    # bu, span kutularının yüksekliğini (dolayısıyla dikey hizalamayı) değiştirir. Sonuçların
    # işlem sırasından bağımsız olması için ayar her çıkarımda sabitlenir.
    fitz.TOOLS.set_small_glyph_heights(False)
    doc = fitz.open(path)
    spans: list[Span] = []
    sizes: dict[int, tuple[float, float]] = {}
    removed: dict[int, int] = {}
    for pno, page in enumerate(doc, start=1):
        sizes[pno] = (page.rect.width, page.rect.height)
        idx = 0
        data = page.get_text("dict")
        for bno, block in enumerate(data["blocks"]):
            for lno, line in enumerate(block.get("lines", [])):
                for sp in line["spans"]:
                    idx += 1
                    spans.append(
                        Span(
                            id=f"P{pno}_S{idx}",
                            page=pno,
                            text=_visible(sp["text"], pno, removed),
                            bbox=tuple(sp["bbox"]),
                            font=sp["font"],
                            size=round(sp["size"], 2),
                            color=sp["color"],
                            flags=sp["flags"],
                            block=bno,
                            line=lno,
                        )
                    )
    page_count = doc.page_count
    doc.close()
    furniture = detect_furniture(spans, sizes, page_count)
    return PdfDoc(path, page_count, sizes, spans, furniture, removed)


# Görünür metin olmayan kontrol karakterleri (sekme ve satır sonu hariç). PyMuPDF'in yeni sürümleri, metin
# katmanında karşılığı olmayan glifler için bunları üretir (ör. Arnavutça s.11 madde imleri "\x07"); eski
# sürümler hiç vermez. Görünür metin olmadıkları ve Excel'e yazılamadıkları için atılır, sayısı raporlanır.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _visible(text: str, page: int, removed: dict[int, int]) -> str:
    out, n = _CONTROL_RE.subn("", text)
    if n:
        removed[page] = removed.get(page, 0) + n
    return out


def detect_furniture(spans: list[Span], sizes: dict[int, tuple[float, float]], page_count: int) -> set[str]:
    """Sayfa kenar bandında tekrar eden metinleri (üst bilgi) ve sayfa numaralarını bulur.

    Program bazında metin hardcode edilmez: tekrar sıklığı ve konumdan öğrenilir.
    """
    band = 0.075
    in_band: list[Span] = []
    for s in spans:
        h = sizes[s.page][1]
        if s.y1 <= h * band or s.y0 >= h * (1 - band):
            in_band.append(s)
    shape_pages: dict[str, set[int]] = defaultdict(set)
    for s in in_band:
        t = s.text.strip()
        if t:
            shape_pages[re.sub(r"\d+", "#", t)].add(s.page)
    furniture: set[str] = set()
    for s in in_band:
        t = s.text.strip()
        if not t:
            continue
        if t.isdigit() and int(t) == s.page:
            furniture.add(s.id)
        elif len(shape_pages[re.sub(r"\d+", "#", t)]) >= max(3, page_count * 0.3):
            furniture.add(s.id)
    return furniture


# ---------------------------------------------------------------- metin yardımcıları


def nfc(s: str) -> str:
    """Ayrışık harfleri birleştirir (ör. Fen s.12 "C" + U+0327 -> "Ç"). Yalnızca eşleştirme ve
    karşılaştırma anahtarlarında kullanılır; ham metin değişmez."""
    return unicodedata.normalize("NFC", s)


def tr_lower(s: str) -> str:
    return nfc(s).replace("İ", "i").replace("I", "ı").lower()


def tr_upper(s: str) -> str:
    return nfc(s).replace("i", "İ").replace("ı", "I").upper()


def norm_label(s: str) -> str:
    """Başlık eşleştirme anahtarı: harf/rakam dışı her şey (boşluk, tire, parantez) yok sayılır.

    Noktalı/noktasız i farkı da yok sayılır: bazı PDF'lerde "BİLİŞİM" başlıkları
    "BILIŞIM" olarak kodlanmıştır. Yalnızca eşleştirme içindir; ham metin değişmez.
    """
    return "".join(ch for ch in tr_lower(s) if ch.isalnum()).replace("ı", "i")


def label_tokens(s: str) -> list[str]:
    """norm_label'ın kelime kelime hali (sözcük sınırları korunur)."""
    return [norm_label(w) for w in re.split(r"[^\w]+", s) if norm_label(w)]


def context_in_title(context: str, title: str) -> bool:
    """Bağlam başlığı ("9. SINIF") özet tablosu başlığında ("FİZİK DERSİ 9. SINIF",
    "9. SINIF BİYOLOJİ DERSİ") ardışık sözcükler olarak geçiyor mu? "1. SINIF" ~ "11. SINIF" eşleşmez."""
    c, t = label_tokens(context), label_tokens(title)
    if not c:
        return False
    if any(t[i : i + len(c)] == c for i in range(len(t) - len(c) + 1)):
        return True
    # Bağlam ve tablo başlığı aynı sıra ifadesiyle başlayıp farklı sürüyor olabilir:
    # "9. SINIF TEMALARI" ~ "9. SINIF KİMYA DERSİ" (ortak "9. SINIF"). Ortak kısım bir sayıyla
    # (ya da Roma rakamıyla) başlamalı ve en az bir sözcük daha içermelidir.
    if len(c) >= 2 and _ordinal_token(c[0]):
        return any(t[i : i + 2] == c[:2] for i in range(len(t) - 1))
    return False


def _ordinal_token(tok: str) -> bool:
    return tok.isdigit() or re.fullmatch(r"[ivx]+", tok) is not None


def compare_key(text: str) -> str:
    """Yalnızca karşılaştırma içindir; gösterilen/saklanan metni değiştirmez."""
    k = nfc(text).replace(chr(0xAD), "")
    k = re.sub(r"-[ \t]*\n\s*", "", k)
    k = k.replace("-", "")
    k = re.sub(r"\s+", " ", k)
    return k.strip()


def font_rank(font: str) -> int:
    f = font.lower()
    if "bold" in f or "semibold" in f or "black" in f or "heavy" in f:
        return 2
    if "medium" in f:
        return 1
    return 0


def group_rows(spans: list[Span], tol: float = 3.0) -> list[list[Span]]:
    """Span'ları (sayfa, dikey merkez) ile görsel satırlara dizer; satır içinde x sırası."""
    ordered = sorted(spans, key=lambda s: (s.page, s.yc, s.x0))
    rows: list[list[Span]] = []
    for s in ordered:
        if rows and rows[-1][0].page == s.page and abs(rows[-1][0].yc - s.yc) <= tol:
            rows[-1].append(s)
        else:
            rows.append([s])
    for r in rows:
        r.sort(key=lambda s: s.x0)
    return rows


def _row_with_offsets(row: list[Span]) -> tuple[str, list[tuple[int, int, str]]]:
    out = ""
    offs: list[tuple[int, int, str]] = []
    prev: Span | None = None
    for s in row:
        if prev is not None:
            gap = s.x0 - prev.x1
            if gap > 0.15 * s.size and not out.endswith((" ", "\t")) and not s.text.startswith((" ", "\t")):
                out += " "
        offs.append((len(out), len(out) + len(s.text), s.id))
        out += s.text
        prev = s
    lead = len(out) - len(out.lstrip())
    stripped = out.strip()
    offs = [(max(a - lead, 0), min(b - lead, len(stripped)), i) for a, b, i in offs]
    return stripped, offs


def row_text(row: list[Span]) -> str:
    """Bir görsel satırın metni. Span'lar arasında görsel boşluk varsa tek boşluk eklenir."""
    return _row_with_offsets(row)[0]


def field_with_offsets(spans: list[Span]) -> tuple[str, list[tuple[int, int, str]]]:
    """make_field ile aynı metni ve her span'ın metindeki [başlangıç, bitiş) aralığını verir."""
    rows = group_rows([s for s in spans if s.text.strip()])
    text, offs = "", []
    for n, r in enumerate(rows):
        if n:
            text += "\n"
        t, o = _row_with_offsets(r)
        offs.extend((a + len(text), b + len(text), i) for a, b, i in o)
        text += t
    return text, offs


def make_field(spans: list[Span]) -> TextField | None:
    spans = [s for s in spans if s.text.strip()]
    if not spans:
        return None
    rows = group_rows(spans)
    text = "\n".join(row_text(r) for r in rows)
    ordered = [s for r in rows for s in r]
    return TextField(
        text=text,
        pages=sorted({s.page for s in ordered}),
        source_spans=[s.id for s in ordered],
        compare_key=compare_key(text),
    )


def sub_field(f: TextField, start: int, end: int, by_id: dict[str, Span]) -> TextField | None:
    """Bir alanın [start, end) karakter aralığı; kaynak span'lar yalnızca o aralığı kapsayanlardır."""
    spans = [by_id[i] for i in f.source_spans]
    text, offs = field_with_offsets(spans)
    if text != f.text:
        raise ValueError("alan metni span'lardan yeniden üretilemedi")
    seg = text[start:end]
    start += len(seg) - len(seg.lstrip())
    end -= len(seg) - len(seg.rstrip())
    if end <= start:
        return None
    ids = [i for a, b, i in offs if a < end and b > start]
    t = text[start:end]
    return TextField(
        text=t,
        pages=sorted({by_id[i].page for i in ids}),
        source_spans=ids,
        compare_key=compare_key(t),
    )


def make_field_from_rows(rows: list[list[Span]]) -> TextField | None:
    return make_field([s for r in rows for s in r])


# ---------------------------------------------------------------- kodlar

_LETTERS = r"[^\W\d_]"


_LINE_HYPHEN_RE = re.compile(r"-[ \t]*\n[ \t]*")


_LINE_DOT_BREAK_RE = re.compile(r"[ \t]*\n\s*(?=\d)")
_CODE_HEAD_END_RE = re.compile(r"(?<![\w.])[^\W\d_]{1,5}\d+(?:\.\d+)*\.$")


def dehyphen_view(text: str) -> tuple[str, list[int]]:
    """Satır sonu tire + kırılımın ("BT-\\nYAB3.3") yok sayıldığı görünüm ve her karakterin
    ham metindeki indeksi. Yalnızca kod tanıma içindir; ham metin değişmez."""
    view: list[str] = []
    idx: list[int] = []
    i = 0
    while i < len(text):
        m = _LINE_HYPHEN_RE.match(text, i)
        if m and i > 0 and text[i - 1].isalnum():
            i = m.end()
            continue
        # Noktadan sonra satır sonunda bölünmüş kod (Kimya s.101 "(KB2.\n14, OB2, OB4)")
        m = _LINE_DOT_BREAK_RE.match(text, i)
        if m and _CODE_HEAD_END_RE.search("".join(view[-12:])):
            i = m.end()
            continue
        view.append(text[i])
        idx.append(i)
        i += 1
    return "".join(view), idx


def parse_code(raw: str) -> Code:
    """Raw kodu yapısal kimliğe ayırır. Raw asla değiştirilmez.

    'MÜZ. 5.1.6.' -> MÜZ.5.1.6 ; 'MÜZ 5.1.3.' -> MÜZ.5.1.3 ; 'D11.2' -> D11.2 ;
    'BT-\\nYAB3.3.' (satır sonunda bölünmüş) -> BTYAB3.3
    """
    m = re.match(rf"\s*({_LETTERS}+)([\s.]*)(\d.*)$", _LINE_HYPHEN_RE.sub("", raw), re.S)
    if not m:
        raise ValueError(f"kod ayrıştırılamadı: {raw!r}")
    prefix, sep, rest = m.group(1), m.group(2), m.group(3)
    segments = [str(int(x)) if x.isdigit() else x for x in re.findall(rf"\d+|{_LETTERS}+", rest)]
    nums = [int(x) for x in segments if x.isdigit()]
    normalized = prefix + ("." if sep else "") + ".".join(segments)
    return Code(raw=raw, normalized=normalized, prefix=prefix, numbers=nums, segments=segments)


UPPER_SEGMENT = r"[A-ZÇĞİÖŞÜ]{1,4}"


def lo_code_regex(prefix: str, segment_types: list[str]) -> re.Pattern:
    """Yapı sayfasından öğrenilen önek + segment tipleriyle öğrenme çıktısı kodu deseni.

    Segment tipi "n" sayı, "a" büyük harfli kısaltmadır (ör. ARN.5.1.D, ARN.5.1.SÖS).
    Boşluk/nokta varyasyonlarına toleranslıdır (MÜZ.5.1.3. / MÜZ. 5.1.3. / MÜZ 5.1.3.).
    """
    sep = r"(?:[ \t]*\.[ \t]*|[ \t]+)"
    nums = sep.join(r"\d+" if t == "n" else UPPER_SEGMENT for t in segment_types)
    # Kod "." ile bitiyorsa ardından boşluksuz metin gelebilir (ör. "BTY.6.4.2.Telif").
    return re.compile(rf"^[ \t]*({re.escape(prefix)}[ \t]*\.?[ \t]*{nums}(?:\.|(?=\s|$|[;,)])))")


def loose_lo_code_regex(prefix: str, n_segments: int, min_segments: int = 1) -> re.Pattern:
    """Segment tipine bakmayan gevşek desen (ör. "ARN.6.4.0." — O yerine sıfır).

    Yalnızca kod başlığı satırlarının kaçırılmaması için kullanılır; kimlik kontrolü ayrıca yapılır.
    """
    # Segmenti eksik başlıklar da yakalanır (ör. Lazca s.106 "LAZ.6.2.", Adigece s.66 "ADG.5.4.");
    # yalnızca koddan oluşan satırda kullanıldığı için sıradan metinle karışmaz.
    seg = rf"(?:\d+|{UPPER_SEGMENT})"
    sep = r"(?:[ \t]*\.[ \t]*|[ \t]+)"
    body = seg + rf"(?:{sep}{seg}){{{min_segments - 1},{n_segments - 1}}}"
    return re.compile(rf"^[ \t]*({re.escape(prefix)}[ \t]*\.?[ \t]*{body}(?:\.|(?=\s|$|[;,)])))")


GENERIC_CODE_RE =re.compile(rf"(?<![\w.])({_LETTERS}{{1,5}}\d+(?:\.\d+)*)(?!\w)")
