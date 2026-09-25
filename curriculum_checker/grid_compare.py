"""Sistem Excel'i ile PDF'den çıkarılan Excel'in hücre hücre (yan yana) karşılaştırılması.

Deterministiktir. Satır = bir süreç bileşeni (sistem Excel düzeni). Her satırda sistem Excel'inin
sütunları için sistem değeri ve PDF değeri yan yana durur; hücre durumu hesaplanır.

PDF tarafında eksik/farklı hücreler iki yolla tamamlanabilir; ikisinde de nihai tabloya giren metin
PDF'nin METİN KATMANINDAN alınan ham metindir (PDF'de olmayan metin üretilmez):
1. Deterministik: sistem değeri, birimin sayfalarının metin katmanında (boşluk/tire farkı hariç) birebir
   aranır; bulunursa PDF'deki ham metin alınır ("PDF metin katmanı").
2. Gemini (isteğe bağlı, tarayıcıda): Gemini sayfa görüntüsünde alanın metnini bildirir; bu metin o
   sayfaların metin katmanında birebir bulunursa PDF'deki ham metin alınır ("Gemini + PDF metin katmanı").
   Bulunamazsa nihai tabloya girmez; "Gemini önerisi — doğrulanamadı" olarak incelemeye düşer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from compare import IGNORED_NAME_SUFFIX, Comparer, without_name_suffix
from excel_export import SYSTEM_HEADERS, SYSTEM_LO_CODE_COLUMNS, lo_code_column_codes, section_for_header
from excel_import import Cell, ExcelLO, ExcelTheme, SystemExcel, code_items, strip_placeholder
from models import ExtractionResult, SectionKind, Unit
from pdf_extract import PdfDoc, compare_key, group_rows, nfc, norm_label, parse_code, row_text, tr_lower

# ---------------------------------------------------------------- durumlar

AYNI = "AYNI"
BICIM = "BİÇİM"
FARKLI = "FARKLI"
SADECE_SISTEM = "YALNIZCA_SİSTEM"
SADECE_PDF = "YALNIZCA_PDF"
BOS = "BOŞ"
CELL_STATUSES = [AYNI, BICIM, FARKLI, SADECE_SISTEM, SADECE_PDF, BOS]
DIFF_STATUSES = {FARKLI, SADECE_SISTEM, SADECE_PDF}

# PDF değerinin kaynağı
SRC_EXTRACTION = "çıkarım"
SRC_TEXT_LAYER = "PDF metin katmanı"
SRC_GEMINI = "Gemini + PDF metin katmanı"

THEME, LO, COMPONENT = "theme", "lo", "component"
CODE_COLUMNS = set(SYSTEM_LO_CODE_COLUMNS)


def column_level(header: str) -> str:
    if header == "Süreç Bileşeni":
        return COMPONENT
    if header == "Öğrenme Çıktısı" or header in CODE_COLUMNS:
        return LO
    return THEME


# ---------------------------------------------------------------- hücre karşılaştırma


def _ws(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def text_cell_status(sys_v: str, pdf_v: str) -> str:
    if not sys_v.strip() and not pdf_v.strip():
        return BOS
    if not pdf_v.strip():
        return SADECE_SISTEM
    if not sys_v.strip():
        return SADECE_PDF
    if _ws(sys_v) == _ws(pdf_v):
        return AYNI
    k = lambda t: re.sub(r"\s+", "", compare_key(t))
    if k(sys_v) == k(pdf_v) or tr_lower(k(sys_v)) == tr_lower(k(pdf_v)):
        return BICIM
    return FARKLI


_CODE_LINE_RE = re.compile(r"^\s*([^\W\d_]{1,5}\d+(?:\.\d+)*)\.?\s*(.*)$", re.S)


def _code_map(entries: list[str]) -> dict:
    out = {}
    for e in entries:
        m = _CODE_LINE_RE.match(e.strip())
        if not m:
            out[("?", e.strip())] = e.strip()
            continue
        try:
            out[parse_code(m.group(1)).key] = e.strip()
        except ValueError:
            out[("?", e.strip())] = e.strip()
    return out


def code_cell_status(sys_v: str, pdf_v: str) -> tuple[str, str]:
    """Kod listesi hücresi: kod kümesi + adlar. (durum, açıklama)"""
    sys_entries = [ln for ln, _, _ in code_items(Cell("", "", sys_v, 0, 0)) if norm_label(ln) not in {"yok", ""}]
    pdf_entries = [e for e in re.split(r"\n\s*\n", pdf_v or "") if e.strip()]
    if not sys_entries and not pdf_entries:
        return BOS, ""
    if not pdf_entries:
        return SADECE_SISTEM, ""
    if not sys_entries:
        return SADECE_PDF, ""
    s, p = _code_map(sys_entries), _code_map(pdf_entries)
    only_s = [s[k] for k in s if k not in p]
    only_p = [p[k] for k in p if k not in s]
    notes = []
    if only_s:
        notes.append("Yalnızca sistemde: " + "; ".join(_short(x) for x in only_s))
    if only_p:
        notes.append("Yalnızca PDF'de: " + "; ".join(_short(x) for x in only_p))
    # PDF'de adı olmayan kod (ör. D3.1 kullanılmış, yalnızca D3 tanımlı): ad karşılaştırılamaz, not düşülür
    nameless = [k for k in s if k in p and not _CODE_LINE_RE.match(p[k]).group(2).strip()] if p else []
    compared = [k for k in s if k in p and k not in nameless]
    name_status = {k: name_entry_status(s[k], p[k]) for k in compared}
    if nameless:
        notes.append("Adı PDF'de tanımlı olmayan kodlar (ad karşılaştırılamadı): " + ", ".join(_code_str(k) for k in nameless))
    suffixed = [k for k in compared if name_status[k] != text_cell_status(s[k], p[k])]
    if suffixed:
        notes.append(f"Adın sonundaki \"{IGNORED_NAME_SUFFIX}\" eki yok sayıldı: " + ", ".join(_code_str(k) for k in suffixed))
    if only_s or only_p:
        return FARKLI, " | ".join(notes)
    if all(x == AYNI for x in name_status.values()):
        return AYNI, " | ".join(notes)
    if all(x in (AYNI, BICIM) for x in name_status.values()):
        return BICIM, " | ".join(notes)
    diff = [k for k in compared if name_status[k] == FARKLI]
    return FARKLI, " | ".join(["Kod aynı, ad farklı: " + ", ".join(_code_str(k) for k in diff)] + notes)


def name_entry_status(sys_entry: str, pdf_entry: str) -> str:
    """Kod + ad girdisi karşılaştırması. Kodlar kimlikleriyle zaten eşleşmiştir: adlar karşılaştırılır; kodun
    yazımı farklıysa (ör. "KB2.4 Çözümleme" / "KB2.4. Çözümleme") en fazla biçim farkıdır. Yalnızca bir
    taraftaki sondaki "Becerisi" eki yok sayılır."""
    ms, mp = _CODE_LINE_RE.match(sys_entry.strip()), _CODE_LINE_RE.match(pdf_entry.strip())
    if not (ms and mp):
        return text_cell_status(sys_entry, pdf_entry)
    s_name, p_name = ms.group(2).strip(), mp.group(2).strip()
    st = text_cell_status(s_name, p_name)
    if st == FARKLI:
        s_cut, p_cut = without_name_suffix(s_name), without_name_suffix(p_name)
        if s_cut is not None and p_cut is None:
            st = text_cell_status(s_cut, p_name)
        elif p_cut is not None and s_cut is None:
            st = text_cell_status(s_name, p_cut)
    s_code, p_code = sys_entry.strip()[: ms.start(2)], pdf_entry.strip()[: mp.start(2)]
    if st == AYNI and _ws(s_code) != _ws(p_code):
        st = BICIM  # ad aynı, kodun yazımı farklı (ör. "KB2.4." / "KB2.4")
    return st


def _code_str(k) -> str:
    return f"{k[0]}{'.'.join(k[1])}" if k[0] != "?" else str(k[1])


def _items(text: str, sep: str) -> list[str]:
    t = re.sub(r"-\s*\n\s*", "", text or "")
    parts = t.split(",") if sep == "," else t.split("\n")
    return [x.strip() for x in parts if x.strip()]


def item_cell_status(sys_v: str, pdf_v: str) -> tuple[str, str]:
    """Öğe listesi (ör. Disiplinler Arası İlişkiler): sistemde satır satır, PDF'de virgülle; öğe kümeleri."""
    s = {norm_label(x): x for x in _items(sys_v, "\n")}
    p = {norm_label(x): x for x in _items(pdf_v.replace("\n", " "), ",")}
    if not s and not p:
        return BOS, ""
    if not p:
        return SADECE_SISTEM, ""
    if not s:
        return SADECE_PDF, ""
    only_s = [s[k] for k in s if k not in p]
    only_p = [p[k] for k in p if k not in s]
    if only_s or only_p:
        notes = []
        if only_s:
            notes.append("Yalnızca sistemde: " + "; ".join(only_s))
        if only_p:
            notes.append("Yalnızca PDF'de: " + "; ".join(only_p))
        return FARKLI, " | ".join(notes)
    return (AYNI if all(_ws(s[k]) == _ws(p[k]) for k in s) else BICIM), ""


def _short(t: str, n: int = 60) -> str:
    t = _ws(t)
    return t if len(t) <= n else t[: n - 1] + "…"


# ---------------------------------------------------------------- veri yapıları


@dataclass
class GridCell:
    header: str
    level: str
    sys: str = ""
    pdf: str = ""
    status: str = BOS
    note: str = ""
    pdf_source: str = SRC_EXTRACTION
    pdf_pages: list[int] = field(default_factory=list)
    sys_address: str = ""
    extracted_pdf: str = ""  # tamamlamadan önceki çıkarım değeri
    gemini_unverified: str = ""  # Gemini'nin bildirdiği ama PDF metin katmanında bulunamayan metin
    kind: str = "text"  # "text" | "codes" (kod + ad listesi) | "items" (öğe listesi)

    def recompute(self) -> None:
        if self.kind == "codes":
            self.status, self.note = code_cell_status(self.sys, self.pdf)
        elif self.kind == "items":
            self.status, self.note = item_cell_status(self.sys, self.pdf)
        else:
            self.status = text_cell_status(self.sys, self.pdf)


@dataclass
class GridRow:
    id: int
    theme_id: int
    lo_id: int | None
    unit_id: str | None
    theme_label: str
    lo_code: str
    component: str
    first_of_theme: bool
    first_of_lo: bool


@dataclass
class Grid:
    headers: list[str]
    rows: list[GridRow]
    theme_cells: dict[int, dict[str, GridCell]]
    lo_cells: dict[int, dict[str, GridCell]]
    comp_cells: dict[int, GridCell]  # satır id -> "Süreç Bileşeni" hücresi
    units_pages: dict[int, list[int]]  # tema id -> PDF birim sayfaları
    notes: list[str] = field(default_factory=list)
    theme_side: dict[int, str] = field(default_factory=dict)  # "both" | "pdf" | "sys"
    lo_side: dict[int, str] = field(default_factory=dict)

    def cells_of_row(self, r: GridRow, all_levels: bool = False) -> dict[str, GridCell]:
        out: dict[str, GridCell] = {}
        if all_levels or r.first_of_theme:
            out.update(self.theme_cells.get(r.theme_id, {}))
        if r.lo_id is not None and (all_levels or r.first_of_lo):
            out.update(self.lo_cells.get(r.lo_id, {}))
        if r.id in self.comp_cells:
            out["Süreç Bileşeni"] = self.comp_cells[r.id]
        return out

    def all_cells(self) -> list[tuple[str, GridCell]]:
        """(kapsam anahtarı, hücre) — her hücre bir kez."""
        out = []
        for t, cs in self.theme_cells.items():
            out += [(f"T{t}", c) for c in cs.values()]
        for l, cs in self.lo_cells.items():
            out += [(f"L{l}", c) for c in cs.values()]
        out += [(f"R{r}", c) for r, c in self.comp_cells.items()]
        return out


# ---------------------------------------------------------------- PDF tarafı değerleri


def _pdf_theme_value(u: Unit, header: str) -> tuple[str, list[int], str]:
    """(değer, sayfalar, hücre türü). Tanım bölümleri (kod listesi) tanım girdileri olarak verilir."""
    if header == "Tema":
        return u.title.text, list(u.title.pages), "text"
    sec = section_for_header(u, header)
    if sec is None or sec.content is None:
        return "", sorted({p for s in [sec] if s is not None and s.label for p in s.label.pages}), "text"
    if sec.kind == SectionKind.DECLARATION and u.declarations.get(sec.path):
        return "\n\n".join(d.entry.text for d in u.declarations[sec.path]), list(sec.content.pages), "codes"
    return sec.content.text, list(sec.content.pages), "text"


def _pdf_lo_value(u: Unit, lo, header: str) -> tuple[str, list[int]]:
    if header == "Öğrenme Çıktısı":
        f = lo.header or lo.title
        return (lo.header.text if lo.header else lo.code.raw), list(f.pages)
    entries = lo_code_column_codes(u, lo.code.key, header)
    block = next((b for b in u.applications if b.code is not None and b.code.key == lo.code.key), None)
    pages = list(block.body.pages) if block and block.body else []
    return "\n\n".join(exact if exact else c.raw for c, exact in entries), pages


def _sys(cell: Cell | None) -> tuple[str, str]:
    if cell is None:
        return "", ""
    return strip_placeholder(cell.raw), cell.address


# ---------------------------------------------------------------- ızgara kurulumu


def build_grid(res: ExtractionResult, xl: SystemExcel) -> Grid:
    cmp = Comparer(res, xl)
    matched = cmp.match_units()
    headers = [h for h in SYSTEM_HEADERS if h in xl.headers] or list(SYSTEM_HEADERS)
    theme_headers = [h for h in headers if column_level(h) == THEME]
    lo_headers = [h for h in headers if column_level(h) == LO]
    grid = Grid(headers, [], {}, {}, {}, {})
    lo_counter = 0

    def add_rows(tid: int, u: Unit | None, t: ExcelTheme | None):
        nonlocal lo_counter
        label = (u.title.text if u else t.cell.text.split("\n")[0]).replace("\n", " ")
        if u is not None and u.context:
            label = f"{u.context.text} | {label}"
        grid.units_pages[tid] = list(u.pages) if u else []
        grid.theme_side[tid] = "both" if (u and t) else ("pdf" if u else "sys")
        tc: dict[str, GridCell] = {}
        for h in theme_headers:
            sv, addr = _sys(t.cell if (t and h == "Tema") else (t.columns.get(h) if t else None))
            pv, pages, kind = _pdf_theme_value(u, h) if u else ("", [], "text")
            if kind == "text" and _looks_like_items(sv, pv):
                kind = "items"
            c = GridCell(h, THEME, sv, pv, pdf_pages=pages, sys_address=addr, extracted_pdf=pv, kind=kind)
            c.recompute()
            tc[h] = c
        grid.theme_cells[tid] = tc
        # ÖÇ eşleştirmesi (kod kimliği)
        pdf_los = {lo.code.key: lo for lo in u.learning_outcomes} if u else {}
        xl_los: dict = {}
        xl_unkeyed: list[ExcelLO] = []
        for xlo in (t.los if t else []):
            code = cmp.lo_code_of(xlo.cell.text)
            if code is None or code.key in xl_los:
                xl_unkeyed.append(xlo)
            else:
                xl_los[code.key] = xlo
        order: list[tuple] = []  # (pdf lo | None, excel lo | None)
        seen = set()
        for k, lo in pdf_los.items():
            order.append((lo, xl_los.get(k)))
            seen.add(k)
        for k, xlo in xl_los.items():
            if k not in seen:
                order.append((None, xlo))
        order += [(None, x) for x in xl_unkeyed]
        first_theme_row = True
        for lo, xlo in order:
            lid = lo_counter
            lo_counter += 1
            lc: dict[str, GridCell] = {}
            for h in lo_headers:
                sv, addr = _sys(xlo.cell if (xlo and h == "Öğrenme Çıktısı") else (xlo.columns.get(h) if xlo else None))
                pv, pages = _pdf_lo_value(u, lo, h) if lo is not None else ("", [])
                c = GridCell(h, LO, sv, pv, pdf_pages=pages, sys_address=addr, extracted_pdf=pv, kind="codes" if h in CODE_COLUMNS else "text")
                c.recompute()
                lc[h] = c
            grid.lo_cells[lid] = lc
            grid.lo_side[lid] = "both" if (lo is not None and xlo is not None) else ("pdf" if lo is not None else "sys")
            code = lo.code.normalized if lo is not None else (cmp.lo_code_of(xlo.cell.text).normalized if cmp.lo_code_of(xlo.cell.text) else "?")
            pcs = lo.components if lo is not None else []
            xcs = xlo.components if xlo is not None else []
            n = max(len(pcs), len(xcs), 1)
            for i in range(n):
                p = pcs[i] if i < len(pcs) else None
                x = xcs[i] if i < len(xcs) else None
                pv = (p.full.text if p.full else p.text.text) if p else ""
                sv, addr = _sys(x)
                marker = (p.marker if p and p.marker else "") or _marker_of(sv) or (f"{i + 1}." if (p or x) else "")
                rid = len(grid.rows)
                c = GridCell("Süreç Bileşeni", COMPONENT, sv, pv, pdf_pages=list(p.text.pages) if p else [], sys_address=addr, extracted_pdf=pv)
                c.recompute()
                grid.comp_cells[rid] = c
                grid.rows.append(GridRow(rid, tid, lid, u.id if u else None, label, code, marker, first_theme_row, i == 0))
                first_theme_row = False
        if first_theme_row:  # temada hiç ÖÇ yok
            rid = len(grid.rows)
            grid.rows.append(GridRow(rid, tid, None, u.id if u else None, label, "", "", True, False))

    used_units = set()
    tid = 0
    for i, t in enumerate(xl.themes):
        u = matched.get(i)
        if u is not None and u.id in used_units:
            grid.notes.append(f"Aynı PDF birimine birden fazla Excel teması eşleşti: {u.id}")
            u = None
        if u is not None:
            used_units.add(u.id)
        add_rows(tid, u, t)
        tid += 1
    for u in res.units:
        if u.id not in used_units:
            add_rows(tid, u, None)
            tid += 1
    return grid


def _looks_like_items(sys_v: str, pdf_v: str) -> bool:
    """Kısa öğelerden oluşan liste mi? (sistemde satır satır, PDF'de virgülle; ör. "Görsel Sanatlar, Matematik")"""
    items = _items(sys_v, "\n")
    return len(items) > 1 and all(len(x) <= 60 and not x.endswith(".") for x in items) and "," in (pdf_v or "")


def _marker_of(text: str) -> str:
    m = re.match(r"^\s*([a-zçğıöşü]\))", text or "")
    return m.group(1) if m else ""


def row_status(grid: Grid, r: GridRow) -> str:
    sts = {c.status for c in grid.cells_of_row(r).values()}
    for s in (FARKLI, SADECE_SISTEM, SADECE_PDF, BICIM, AYNI):
        if s in sts:
            return s
    return BOS


# ---------------------------------------------------------------- PDF metin katmanında arama


def _fold(ch: str) -> str:
    ch = tr_lower(ch).replace("ı", "i")
    return {"“": '"', "”": '"', "„": '"', "«": '"', "»": '"', "‘": "'", "’": "'", "ʻ": "'", "`": "'", "–": "-", "—": "-"}.get(ch, ch)


def normalize_with_map(raw: str) -> tuple[str, list[int]]:
    """Eşleştirme görünümü: boşluk, tire ve yumuşak tire yok sayılır; harfler küçültülür, tırnaklar
    tekleştirilir. Her görünüm karakterinin ham metindeki indeksi döner (ham metni geri almak için)."""
    out, idx = [], []
    for i, ch in enumerate(nfc(raw)):
        if ch.isspace() or ch in "-­":
            continue
        f = _fold(ch)
        if f == "-":
            continue
        out.append(f)
        idx.append(i)
    return "".join(out), idx


@dataclass
class PageText:
    """Sayfa(lar)ın bölüm başlıkları hariç okuma sırasındaki metin katmanı."""
    text: str
    norm: str
    idx: list[int]


def page_text(doc: PdfDoc, pages: Iterable[int], label_colors: Iterable[int]) -> PageText:
    labels = set(label_colors)
    rows = []
    for p in sorted(set(pages)):
        spans = [s for s in doc.page_spans(p) if s.id not in doc.furniture and s.text.strip() and s.color not in labels]
        rows += [row_text(r) for r in group_rows(spans)]
    text = "\n".join(rows)
    norm, idx = normalize_with_map(text)
    return PageText(text, norm, idx)


def find_in_text_layer(pt: PageText, wanted: str, min_len: int = 12) -> str | None:
    """wanted metni metin katmanında birebir (boşluk/tire/büyük-küçük harf farkı hariç) geçiyorsa PDF'deki
    ham karşılığını döndürür. Çok kısa metinler (yanlış eşleşme riski) aranmaz."""
    key, _ = normalize_with_map(strip_placeholder(wanted))
    if len(key) < min_len:
        return None
    pos = pt.norm.find(key)
    if pos < 0:
        return None
    start, end = pt.idx[pos], pt.idx[pos + len(key) - 1] + 1
    return pt.text[start:end]


def _cell_pages(grid: Grid, scope: str, c: GridCell) -> list[int]:
    """Aramada kullanılacak sayfalar: hücrenin çıkarımdaki sayfaları; yoksa birimin tüm sayfaları."""
    if c.pdf_pages:
        pages = set(c.pdf_pages)
        # içerik sonraki sayfaya taşmış olabilir
        pages |= {p + 1 for p in c.pdf_pages}
        return sorted(pages)
    kind, n = scope[0], int(scope[1:])
    tid = n if kind == "T" else next((r.theme_id for r in grid.rows if (kind == "L" and r.lo_id == n) or (kind == "R" and r.id == n)), None)
    return grid.units_pages.get(tid, []) if tid is not None else []


def complete_from_text_layer(grid: Grid, doc: PdfDoc, label_colors: Iterable[int]) -> int:
    """Deterministik tamamlama: PDF değeri boş ve sistem değeri dolu hücrelerde sistem metni PDF metin
    katmanında birebir aranır. Bulunursa PDF'deki ham metin alınır. Kod sütunları (liste) hariç."""
    n = 0
    for scope, c in grid.all_cells():
        if c.status != SADECE_SISTEM or c.kind != "text":
            continue
        pages = _cell_pages(grid, scope, c)
        if not pages:
            continue
        found = find_in_text_layer(page_text(doc, pages, label_colors), c.sys)
        if found:
            c.pdf, c.pdf_source = found, SRC_TEXT_LAYER
            c.note = "Çıkarımda boştu; aynı metin PDF metin katmanında bulundu"
            c.recompute()
            n += 1
    return n


# ---------------------------------------------------------------- Gemini görevleri ve doğrulama

GEMINI_FIELD_PROMPT = """Bu görüntü bir Türkçe öğretim programı PDF'sinin tek sayfasıdır. Aşağıdaki alanların bu sayfada
yazan metnini BİREBİR, sayfada göründüğü gibi ver (düzeltme, tamamlama, çeviri, özetleme yapma; satır sonu
tirelerini olduğu gibi bırakabilirsin). Alan bu sayfada yoksa text alanını boş bırak. Sayfada alanın yalnızca
bir kısmı varsa yalnızca o kısmı ver.

Alanlar:
{fields}"""

GEMINI_FIELD_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "fields": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"id": {"type": "STRING"}, "text": {"type": "STRING"}},
                "required": ["id", "text"],
            },
        }
    },
    "required": ["fields"],
}


def _field_description(grid: Grid, scope: str, c: GridCell) -> str:
    kind, n = scope[0], int(scope[1:])
    row = next((r for r in grid.rows if (kind == "T" and r.theme_id == n) or (kind == "L" and r.lo_id == n) or (kind == "R" and r.id == n)), None)
    where = []
    if row is not None:
        where.append(f"tema: {row.theme_label}")
        if kind in "LR" and row.lo_code:
            where.append(f"öğrenme çıktısı: {row.lo_code}")
        if kind == "R" and row.component:
            where.append(f"süreç bileşeni: {row.component}")
    what = {
        "Tema": "tema/ünite başlığı",
        "Öğrenme Çıktısı": "öğrenme çıktısının kodu ve başlığı",
        "Süreç Bileşeni": "süreç bileşeninin harfi ve metni",
    }.get(c.header, f"'{c.header}' bölümünün içeriği")
    if c.header in CODE_COLUMNS:
        what = f"bu öğrenme çıktısının uygulama metninde parantez içinde geçen '{c.header}' kodları (kod ve varsa adı)"
    return f"{what} ({'; '.join(where)})"


def gemini_targets(grid: Grid, max_cells: int = 200) -> list[tuple[str, GridCell]]:
    """Gemini'ye sorulacak hücreler: farklı ya da PDF'de eksik olanlar (kaynağı çıkarım olanlar)."""
    out = [(s, c) for s, c in grid.all_cells() if c.status in (FARKLI, SADECE_SISTEM) and c.pdf_source == SRC_EXTRACTION]
    return out[:max_cells]


def gemini_tasks(grid: Grid, pdf_path: str, targets: list[tuple[str, GridCell]], render) -> list[dict]:
    """Sayfa başına bir görev: sayfa görüntüsü + o sayfada aranacak alanlar. render(pdf, sayfa) -> base64 JPEG."""
    by_page: dict[int, list[tuple[str, GridCell]]] = {}
    for scope, c in targets:
        for p in _cell_pages(grid, scope, c):
            by_page.setdefault(p, []).append((scope, c))
    tasks = []
    for p, items in sorted(by_page.items()):
        lines = [f'- id="{scope}|{c.header}": {_field_description(grid, scope, c)}' for scope, c in items]
        tasks.append(
            {
                "id": f"p{p}",
                "page": p,
                "image": render(pdf_path, p),
                "text": GEMINI_FIELD_PROMPT.format(fields="\n".join(lines)),
                "schema": GEMINI_FIELD_SCHEMA,
            }
        )
    return tasks


def apply_gemini(grid: Grid, doc: PdfDoc, label_colors: Iterable[int], results: dict, parse) -> dict[str, int]:
    """Tarayıcıdan dönen yanıtları uygular. results: {görev id: {"ok": json metni} | {"error": ...}}.
    Gemini'nin metni yalnızca PDF metin katmanında birebir bulunursa (PDF'deki ham metinle) kullanılır."""
    snippets: dict[str, list[tuple[int, str]]] = {}
    errors = 0
    for tid, r in results.items():
        page = int(str(tid).lstrip("p"))
        if "error" in r:
            errors += 1
            continue
        try:
            data = parse(r["ok"])
        except Exception:
            errors += 1
            continue
        for item in data.get("fields", []) if isinstance(data, dict) else []:
            fid, txt = str(item.get("id", "")), str(item.get("text", "") or "")
            if txt.strip():
                snippets.setdefault(fid, []).append((page, txt))
    cells = {f"{s}|{c.header}": (s, c) for s, c in grid.all_cells()}
    stats = {"verified": 0, "unverified": 0, "errors": errors}
    for fid, parts in snippets.items():
        if fid not in cells:
            continue
        scope, c = cells[fid]
        parts.sort()
        pages = sorted({p for p, _ in parts})
        pt = page_text(doc, pages, label_colors)
        joined = " ".join(t for _, t in parts)
        found = find_in_text_layer(pt, joined, min_len=3)
        if found is None and len(parts) > 1:
            pieces = [find_in_text_layer(page_text(doc, [p], label_colors), t, min_len=3) for p, t in parts]
            found = "\n".join(pieces) if all(pieces) else None
        if found is None:
            c.gemini_unverified = joined
            stats["unverified"] += 1
            continue
        if _ws(found) == _ws(c.pdf):
            continue  # Gemini çıkarımı doğruladı; değişiklik yok
        c.pdf, c.pdf_source, c.gemini_unverified = found, SRC_GEMINI, ""
        c.note = "Gemini sayfada buldu; metin PDF metin katmanında doğrulandı (ham PDF metni)"
        c.recompute()
        stats["verified"] += 1
    return stats


# ---------------------------------------------------------------- dışa aktarma (tablo bileşeni için)


def grid_payload(grid: Grid) -> dict:
    def cell(c: GridCell) -> dict:
        return {
            "s": c.sys,
            "p": c.pdf,
            "st": c.status,
            "n": c.note,
            "src": c.pdf_source,
            "pg": c.pdf_pages,
            "a": c.sys_address,
            "x": c.extracted_pdf if c.pdf_source != SRC_EXTRACTION else "",
            "g": c.gemini_unverified,
        }

    return {
        "headers": grid.headers,
        "levels": {h: column_level(h) for h in grid.headers},
        "rows": [
            {
                "id": r.id,
                "t": r.theme_id,
                "l": r.lo_id,
                "u": r.unit_id or "",
                "tl": r.theme_label,
                "lo": r.lo_code,
                "c": r.component,
                "ft": r.first_of_theme,
                "fl": r.first_of_lo,
                "st": row_status(grid, r),
            }
            for r in grid.rows
        ],
        "theme": {str(k): {h: cell(c) for h, c in v.items()} for k, v in grid.theme_cells.items()},
        "lo": {str(k): {h: cell(c) for h, c in v.items()} for k, v in grid.lo_cells.items()},
        "comp": {str(k): cell(c) for k, c in grid.comp_cells.items()},
    }


def grid_counts(grid: Grid) -> dict[str, int]:
    out = {s: 0 for s in CELL_STATUSES}
    for _, c in grid.all_cells():
        out[c.status] += 1
    out["tamamlanan_metin_katmani"] = sum(1 for _, c in grid.all_cells() if c.pdf_source == SRC_TEXT_LAYER)
    out["tamamlanan_gemini"] = sum(1 for _, c in grid.all_cells() if c.pdf_source == SRC_GEMINI)
    out["gemini_dogrulanamayan"] = sum(1 for _, c in grid.all_cells() if c.gemini_unverified)
    return out
