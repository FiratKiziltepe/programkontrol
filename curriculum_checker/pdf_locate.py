"""PDF'de konum bulma: tablolardaki bir hücrenin PDF'de nereden geldiği (sayfa + sarı işaretlenecek kutular).

Tüm sekmeler aynı kuralı kullanır ve deterministiktir:
- Metin hücreleri: çıkarımın kaynak span'leri (PDF bbox'ları) işaretlenir.
- Kodlar: kaynak span'lerin içinde (ya da verilen sayfalarda) PDF metin katmanındaki kelimelerden kodla
  BİREBİR eşleşenler işaretlenir ("D1", "D10" ya da "D1.1" ile eşleşmez).
- Bulunamayan yer tahmin edilmez: sayfa işaretsiz gösterilir ve not düşülür (NEEDS_REVIEW).
Burada PDF'de olmayan metin üretilmez; yalnızca konum hesaplanır.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable

import fitz

from models import ExtractionResult, Finding, LearningOutcome, ProcessComponent, Section, TextField, Unit
from pdf_extract import PdfDoc

Rect = tuple[float, float, float, float]

NOT_FOUND = "Bu konum PDF'de birebir bulunamadı; sayfa işaretsiz gösteriliyor (inceleme gerekli)."
NO_LOCATION = "Bu satır için PDF konumu yok."

_WORD_CHARS = "0-9A-Za-zÇĞİÖŞÜÂÎÛçğıöşüâîû"
CODE_LIKE = re.compile(r"^[^\W\d_]{1,6}\d+(?:[.,]\d+)*\.?$")


@dataclass
class Loc:
    title: str
    pages: list[int] = field(default_factory=list)
    rects: dict[int, list[Rect]] = field(default_factory=dict)
    note: str = ""

    @property
    def found(self) -> bool:
        return any(self.rects.values())

    def all_pages(self) -> list[int]:
        return sorted(set(self.pages) | {p for p, rs in self.rects.items() if rs})


def code_pattern(code: str) -> re.Pattern:
    """Kelime başında kod; ardından rakam/harf ya da ".<rakam>" gelmez (D1 ≠ D10 ≠ D1.1). "E1.1.Merak" gibi
    bitişik yazımda E1.1 bulunur."""
    c = code.strip().rstrip(".,;:")
    return re.compile(r"^[\(\[\"'“‘]*" + re.escape(c) + rf"(?![{_WORD_CHARS}]|\.[0-9])")


@lru_cache(maxsize=1024)
def page_words(path: str, page: int) -> tuple[tuple[float, float, float, float, str], ...]:
    fitz.TOOLS.set_small_glyph_heights(False)  # extract_spans ile aynı kutu yüksekliği
    with fitz.open(path) as d:
        return tuple((w[0], w[1], w[2], w[3], w[4]) for w in d[page - 1].get_text("words"))


def _inside(w: tuple, boxes: list[Rect], tol: float = 1.5) -> bool:
    cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
    return any(b[0] - tol <= cx <= b[2] + tol and b[1] - tol <= cy <= b[3] + tol for b in boxes)


def _fields(*fs: TextField | None) -> list[TextField]:
    return [f for f in fs if f is not None]


class Locator:
    def __init__(self, res: ExtractionResult, doc: PdfDoc):
        self.res, self.doc, self.path = res, doc, res.source
        self.span = {s.id: s for s in doc.spans}
        self.units = {u.id: u for u in res.units}

    # ------------------------------------------------------------ temel yapı taşları
    def span_rects(self, ids: Iterable[str]) -> dict[int, list[Rect]]:
        out: dict[int, list[Rect]] = {}
        for i in ids:
            s = self.span.get(i)
            if s is not None:
                out.setdefault(s.page, []).append(tuple(s.bbox))
        return out

    def spans_loc(self, title: str, ids: Iterable[str], pages: Iterable[int] = ()) -> Loc:
        rects = self.span_rects(ids)
        loc = Loc(title, sorted(set(pages) | set(rects)), rects)
        if not loc.found:
            loc.note = NOT_FOUND if loc.pages else NO_LOCATION
        return loc

    def fields_loc(self, title: str, fields: Iterable[TextField | None]) -> Loc:
        fs = [f for f in fields if f is not None]
        return self.spans_loc(title, [i for f in fs for i in f.source_spans], [p for f in fs for p in f.pages])

    def code_rects(self, codes: Iterable[str], span_ids: Iterable[str] | None = None, pages: Iterable[int] = ()) -> dict[int, list[Rect]]:
        """Kodların PDF'deki yazımları: span_ids verilirse yalnızca o span'lerin içinde, yoksa verilen sayfalarda."""
        pats = [code_pattern(c) for c in dict.fromkeys(c for c in codes if c and c.strip())]
        if span_ids is not None:
            within = self.span_rects(span_ids)
        else:
            within = {p: None for p in pages}
        out: dict[int, list[Rect]] = {}
        for page, boxes in within.items():
            for w in page_words(self.path, page):
                if boxes is not None and not _inside(w, boxes):
                    continue
                if any(p.match(w[4]) for p in pats):
                    out.setdefault(page, []).append((w[0], w[1], w[2], w[3]))
        return out

    def code_loc(self, title: str, codes: Iterable[str], span_ids: Iterable[str] | None = None, pages: Iterable[int] = ()) -> Loc:
        span_ids = list(span_ids) if span_ids is not None else None
        rects = self.code_rects(codes, span_ids, pages)
        base_pages = set(pages) | (set(self.span_rects(span_ids)) if span_ids is not None else set())
        loc = Loc(title, sorted(base_pages | set(rects)), rects)
        if not loc.found:
            loc.note = NOT_FOUND if loc.pages else NO_LOCATION
        return loc

    # ------------------------------------------------------------ birim içi aramalar
    def unit_loc(self, u: Unit) -> Loc:
        return self.fields_loc(f"{u.id} — tema başlığı", _fields(u.context, u.title))

    def section_loc(self, u: Unit, s: Section) -> Loc:
        return self.fields_loc(f"{u.id} — {s.path or 'başlıksız bölüm'}", _fields(s.label, s.content))

    def lo_loc(self, u: Unit, lo: LearningOutcome, comp: ProcessComponent | None = None) -> Loc:
        fs = _fields(lo.header or lo.title)
        if comp is not None:
            fs += _fields(comp.full or comp.text)
        return self.fields_loc(f"{u.id} — {lo.code.raw}" + (f" {comp.marker}" if comp is not None and comp.marker else ""), fs)

    def block_spans(self, u: Unit, lo_normalized: str) -> list[str]:
        return [
            i
            for b in u.applications
            if b.code is not None and b.code.normalized == lo_normalized
            for f in _fields(b.header, b.body)
            for i in f.source_spans
        ]

    def declared_code_loc(self, u: Unit, code: str, category: str | None = None) -> Loc:
        """Kodun tanımı (tanım bölümündeki girdi). Kod kelimesi girdi içinde bulunamazsa girdinin tamamı işaretlenir."""
        ds = [
            d
            for path, lst in u.declarations.items()
            if category is None or path == category
            for d in lst
            if d.code.normalized == code or d.code.raw.rstrip(".") == code
        ]
        title = f"{u.id} — {code} (tanım)"
        if not ds:
            return Loc(title, list(u.pages[:1]), note=NOT_FOUND)
        ids = [i for d in ds for i in d.entry.source_spans]
        loc = self.code_loc(title, [code] + [d.code.raw for d in ds], ids)
        return loc if loc.found else self.fields_loc(title, [d.entry for d in ds])

    def used_code_loc(self, u: Unit, code: str) -> Loc:
        """Kodun öğrenme-öğretme uygulamalarındaki tüm kullanımları."""
        raws, ids = [code], []
        for b in u.applications:
            hits = [c for c in b.used_codes if c.normalized == code]
            if hits or code in b.malformed_codes:
                raws += [c.raw for c in hits]
                ids += [i for f in _fields(b.header, b.body) for i in f.source_spans]
        title = f"{u.id} — {code} (uygulamalarda kullanım)"
        if not ids:
            return self.code_loc(title, [code], pages=u.pages)
        return self.code_loc(title, raws, ids)

    def unit_fields(self, u: Unit) -> list[TextField]:
        fs = _fields(u.context, u.title, u.subtitle)
        for s in u.sections:
            fs += _fields(s.label, s.content) + list(s.content_rows)
        for lo in u.learning_outcomes:
            fs += _fields(lo.header, lo.title)
            for c in lo.components:
                fs += _fields(c.full, c.text)
        for b in u.applications:
            fs += _fields(b.header, b.body)
        for ds in u.declarations.values():
            fs += [d.entry for d in ds]
        return fs

    def text_loc(self, u: Unit | None, text: str, pages: Iterable[int] = (), title: str = "", code: str = "") -> Loc:
        """PDF değeri bir çıkarım alanıyla BİREBİR aynıysa o alanın span'leri (code verilirse alan içindeki kod
        yazımı); tek kelimelik değer kod gibi sayfada aranır; bulunamazsa işaretsiz sayfa."""
        pages = list(pages)
        t = (text or "").strip()
        units = [u] if u is not None else self.res.units
        hits = [f for x in units for f in self.unit_fields(x) if t and f.text.strip() == t and (not pages or set(f.pages) & set(pages))]
        title = title or (u.id if u else "")
        if hits:
            if code and CODE_LIKE.match(code):
                loc = self.code_loc(title, [code], [i for f in hits for i in f.source_spans])
                if loc.found:
                    return loc
            return self.fields_loc(title, hits)
        if t and not re.search(r"\s", t) and pages:
            loc = self.code_loc(title, [t], pages=pages)
            if loc.found:
                return loc
        return Loc(title, pages, note=NOT_FOUND if (t and pages) else NO_LOCATION)

    def raw_text_loc(self, title: str, text: str, pages: Iterable[int], min_len: int = 8) -> Loc:
        """PDF metin katmanından alınmış ham metin (ör. tamamlanan hücre): her satırı verilen sayfalarda aranır;
        yalnızca TEK yerde geçen satırlar işaretlenir (birden çok yerde geçen satır belirsizdir, işaretlenmez)."""
        pages = sorted(set(pages))
        rects: dict[int, list[Rect]] = {}
        fitz.TOOLS.set_small_glyph_heights(False)
        with fitz.open(self.path) as d:
            for line in dict.fromkeys(ln.strip() for ln in (text or "").split("\n")):
                if len(line) < min_len:
                    continue
                hits = [(p, r) for p in pages for r in d[p - 1].search_for(line)]
                if len(hits) == 1:
                    p, r = hits[0]
                    rects.setdefault(p, []).append((r.x0, r.y0, r.x1, r.y1))
        loc = Loc(title, pages, rects)
        if not loc.found:
            loc.note = NOT_FOUND if pages else NO_LOCATION
        return loc

    # ------------------------------------------------------------ bulgular
    def finding_loc(self, f: Finding) -> Loc:
        d, u = f.details, self.units.get(f.unit_id or "")
        title = f"{f.check}" + (f" — {f.unit_id}" if f.unit_id else "")
        ids = list(d.get("spans") or []) + list(d.get("label_spans") or [])
        if ids:
            return self.spans_loc(title, ids)
        code = d.get("code_raw") or d.get("normalized")
        if code and u is not None:
            if d.get("in_application_of"):
                loc = self.code_loc(title, [code], self.block_spans(u, d["in_application_of"]))
                if loc.found:
                    return loc
            if d.get("category"):
                loc = self.declared_code_loc(u, code.rstrip("."), d["category"])
                if loc.found:
                    loc.title = title
                    return loc
            return self.code_loc(title, [code], pages=u.pages)
        if u is not None:
            loc = self.unit_loc(u)
            loc.title, loc.note = title, "Bulgunun ayrıntılı konumu yok; tema başlığı işaretlendi."
            return loc
        return Loc(title, note=NO_LOCATION)


    # ------------------------------------------------------------ kod kontrol tablosu (2. sekme)
    def code_check_cell(self, unit_id: str, category: str | None, column: str, value: str) -> Loc | list[tuple[str, Loc]]:
        u = self.units.get(unit_id)
        if u is None:
            return Loc(unit_id, note=NO_LOCATION)
        if column in DECLARED_COLUMNS:
            return [(c, self.declared_code_loc(u, c, category)) for c in split_codes(value)] or self.unit_loc(u)
        if column in USED_COLUMNS:
            return [(c, self.used_code_loc(u, c)) for c in split_codes(value)] or self.unit_loc(u)
        if column == "Kategori" and category:
            s = next((s for s in u.sections if s.path == category), None)
            if s is not None:
                return self.section_loc(u, s)
        return self.unit_loc(u)


DECLARED_COLUMNS = {"Tanımlanan", "Tanımlı ama kullanılmamış"}
USED_COLUMNS = {"Kullanılan", "Kullanılmış ama tanımlı değil"}


def split_codes(cell: str) -> list[str]:
    return [c.strip() for c in (cell or "").split(",") if c.strip()]


def code_check_refs(res: ExtractionResult) -> list[tuple[str, str | None]]:
    """excel_export.code_checks_df satırlarıyla aynı sırada (birim, kategori); kategorisi belirlenemeyen satırda None."""
    out: list[tuple[str, str | None]] = []
    for r in res.unit_reports:
        out += [(r.unit_id, c.category) for c in r.code_checks]
        placed = {x for c in r.code_checks for x in c.used_not_declared}
        if any(x not in placed for x in r.used_not_declared):
            out.append((r.unit_id, None))
    return out


def page_list(text: str) -> list[int]:
    """"31, 32" / "27-38" gibi sayfa metninden sayfa numaraları."""
    out: list[int] = []
    for a, b in re.findall(r"(\d+)(?:\s*-\s*(\d+))?", text or ""):
        out += list(range(int(a), int(b) + 1)) if b else [int(a)]
    return out
