"""İşaretli PDF: seçilen bulgular orijinal PDF'nin bir kopyasında işaretlenir (kayıt ve inceleme için).

- PDF'nin kendi içeriği değişmez ve sayfa eklenmez (sayfa numaraları aynı kalır). Bulgusu olan sayfalar SAĞA doğru
  genişletilir; açıklama kutuları yalnızca bu yeni şeride yazılır ve işaretli yere çizgiyle bağlanır.
- Yer, PDF açıklaması (highlight) olarak vurgulanır; kutudaki açıklama vurgunun notunda da durur (yorumlar paneli).
- Konumlar "PDF'de göster" ile aynıdır (pdf_locate.Locator). Bulunamayan yer tahmin edilmez; kutuda yazar.
- Kutulardaki metin aracın bulgu açıklamasıdır, PDF metni gibi sunulmaz; içindeki kod ve metinler bulgunun
  ayrıntısından (PDF'den birebir alınmış değerler) gelir.
- "Kullanılmış ama tanımlanmamış kod" için kanıtın öbür ucu da işaretlenir: temanın ilgili tanım bölümü (mavi) ve
  orada tanımlı aynı önekli kodlar. Kullanım ve tanım kutuları birbirine tıklanabilir bağlantılıdır.
- Bulgular yer imlerinde (bookmarks) tema > bulgu olarak listelenir.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field

import fitz

from models import ExtractionResult, Finding, Section, Unit
from pdf_extract import parse_code
from pdf_locate import Loc, Locator, Rect

SEVERITY_TR = {"FAIL": "Hata", "NEEDS_REVIEW": "İnceleme gerekli", "WARNING": "Uyarı", "INFO": "Bilgi"}
# (çizgi/başlık rengi, kutu dolgusu)
SEVERITY_COLORS = {
    "FAIL": ((0.78, 0.12, 0.12), (1.0, 0.93, 0.93)),
    "NEEDS_REVIEW": ((0.85, 0.42, 0.0), (1.0, 0.95, 0.88)),
    "WARNING": ((0.65, 0.52, 0.0), (1.0, 0.98, 0.86)),
    "INFO": ((0.4, 0.4, 0.4), (0.95, 0.95, 0.95)),
}
EVIDENCE_COLORS = ((0.12, 0.38, 0.78), (0.91, 0.95, 1.0))
FINDING_HIGHLIGHT = (1.0, 0.88, 0.1)  # pdf_view.FILL ile aynı sarı
EVIDENCE_HIGHLIGHT = (0.55, 0.8, 1.0)

COL_W = 215.0  # açıklama sütunu genişliği (pt)
PAD = 4.0
GAP = 5.0
TOP, BOTTOM = 18.0, 18.0
FS = 7.0  # kutu yazı boyutu
LH = FS * 1.28
# Türkçe harfleri içeren yerleşik yazı tipleri; belgeye bir kez gömülür (TextWriter)
_REG, _BOLD = fitz.Font("helv"), fitz.Font("hebo")
AUTHOR = "Öğretim Programı Kontrol"

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
}
SKIP_DETAILS = {"spans", "label_spans", "matched_label_norm"}
SUMMARY_TABLE_CHECKS = {"LO_TOTAL_MISMATCH", "UNIT_COUNT_MISMATCH"}


@dataclass
class _Note:
    page: int
    anchor: Rect | None  # çizginin bağlanacağı işaret; None: işaret yok (kutu sayfanın üstünde)
    head: str
    lines: list[str]
    colors: tuple
    num: int | None = None
    link: tuple[int, Rect | None] | None = None  # kutuya tıklayınca gidilecek (sayfa, konum)
    h: float = 0.0
    wrapped: list = field(default_factory=list)
    rect: fitz.Rect | None = None


@dataclass
class _Evidence:
    unit: Unit
    section: Section | None  # None: temada bu önekli tanım bölümü yok
    loc: Loc
    codes: list[tuple[str, int]] = field(default_factory=list)  # (kullanılan kod ham, bulgu no)
    usage: list[tuple[int, Rect | None]] = field(default_factory=list)


def _fmt(v) -> str:
    s = ", ".join(map(str, v)) if isinstance(v, (list, tuple, set)) else str(v)
    s = s.replace("\n", " ")
    return s if len(s) <= 220 else s[:219] + "…"


def detail_lines(f: Finding) -> list[str]:
    return [f"{DETAIL_TR.get(k, k)}: {_fmt(v)}" for k, v in f.details.items() if k not in SKIP_DETAILS and v not in (None, "", [])]


def _first_anchor(loc: Loc, page: int) -> Rect | None:
    rs = loc.rects.get(page) or []
    return min(rs, key=lambda r: (r[1], r[0])) if rs else None


def _unit_label(u: Unit) -> str:
    return " — ".join(x for x in (u.id, u.context.text if u.context else "", u.title.text) if x).replace("\n", " ")


def _decl_sections(res: ExtractionResult, u: Unit, code_raw: str) -> tuple[str | None, list[Section]]:
    """Tanımsız kullanılan kodun tanımlanması beklenen bölüm(ler): kod kontrolünde yerleştirildiği kategori; o yoksa
    temada aynı önekli kod tanımlayan tüm bölümler (aday hepsi işaretlenir, seçim yapılmaz)."""
    try:
        c = parse_code(code_raw)
    except ValueError:
        return None, []
    rep = next((r for r in res.unit_reports if r.unit_id == u.id), None)
    cats = [cc.category for cc in rep.code_checks if c.normalized in cc.used_not_declared] if rep else []
    if not cats:
        cats = [p for p, ds in u.declarations.items() if any(d.code.prefix == c.prefix for d in ds)]
    return c.prefix, [s for s in u.sections if s.path in cats]


def _wrap(text: str, font: fitz.Font, width: float) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        line = ""
        for w in para.split(" "):
            cand = f"{line} {w}" if line else w
            if font.text_length(cand, fontsize=FS) <= width:
                line = cand
                continue
            if line:
                out.append(line)
            while font.text_length(w, fontsize=FS) > width:  # tek başına sığmayan uzun kelime
                k = len(w) - 1
                while k > 1 and font.text_length(w[:k], fontsize=FS) > width:
                    k -= 1
                out.append(w[:k])
                w = w[k:]
            line = w
        out.append(line)
    return out


def _measure(n: _Note) -> float:
    width = COL_W - 6 - 2 * PAD
    n.wrapped = [(True, t) for t in _wrap(n.head, _BOLD, width)] + [(False, t) for line in n.lines for t in _wrap(line, _REG, width)]
    return len(n.wrapped) * LH + 2 * PAD + 1


def _write(page: fitz.Page, n: _Note) -> None:
    head, body = fitz.TextWriter(page.rect), fitz.TextWriter(page.rect)
    x, y = n.rect.x0 + PAD, n.rect.y0 + PAD + FS * 0.95
    rows = n.wrapped
    fit = max(1, int((n.rect.height - 2 * PAD) // LH))
    if len(rows) > fit:  # sütuna sığmayan kutu (çok kalabalık sayfa): kesilir, yorum notunda tamamı var
        rows = rows[: fit - 1] + [(False, "… (devamı vurgunun notunda)")]
    for bold, t in rows:
        (head if bold else body).append((x, y), t, font=_BOLD if bold else _REG, fontsize=FS)
        y += LH
    head.write_text(page, color=n.colors[0])
    body.write_text(page, color=(0.1, 0.1, 0.1))


def _layout(notes: list[_Note], page_h: float, x0: float) -> int:
    """Kutuları sağ şeride yerleştirir: tek sütuna sığıyorsa işaretin hizasına yakın, sığmıyorsa sütunlara sırayla.
    Kullanılan sütun sayısını döndürür."""
    top, bottom = TOP, page_h - BOTTOM
    notes.sort(key=lambda n: (n.anchor[1] if n.anchor else -1.0, n.num or 0))
    total = sum(n.h for n in notes) + GAP * (len(notes) - 1)
    if total <= bottom - top:
        ys, cur = [], top
        for n in notes:
            y = max((n.anchor[1] - 4) if n.anchor else top, cur)
            ys.append(y)
            cur = y + n.h + GAP
        limit = bottom
        for i in range(len(notes) - 1, -1, -1):
            if ys[i] + notes[i].h > limit:
                ys[i] = limit - notes[i].h
            limit = ys[i] - GAP
        for n, y in zip(notes, ys):
            n.rect = fitz.Rect(x0 + 6, y, x0 + COL_W, y + n.h)
        return 1
    col, y = 0, top
    for n in notes:
        h = min(n.h, bottom - top)
        if y + h > bottom and y > top:
            col, y = col + 1, top
        cx = x0 + col * COL_W
        n.rect = fitz.Rect(cx + 6, y, cx + COL_W, y + h)
        y += h + GAP
    return col + 1


def _highlight(page: fitz.Page, rects: list[Rect], color, title: str, content: str) -> None:
    a = page.add_highlight_annot([fitz.Rect(r) for r in rects])
    a.set_colors(stroke=color)
    a.set_info(title=AUTHOR, subject=title, content=content)
    a.update(opacity=0.45)


def build_annotated_pdf(res: ExtractionResult, findings: list[Finding], L: Locator) -> bytes:
    units = {u.id: u for u in res.units}
    notes: list[_Note] = []
    marks: list[tuple[int, list[Rect], tuple, str, str]] = []  # (sayfa, kutular, renk, başlık, not)
    evidence: dict[tuple[str, str | None, str], _Evidence] = {}
    toc_items: list[tuple[str, int, int, Rect | None, str]] = []  # (birim, no, sayfa, konum, başlık)
    finding_notes: dict[int, _Note] = {}
    summary_page = next((t.page for t in res.expected_tables if t.role.value == "SUMMARY"), None)

    for num, f in enumerate(findings, 1):
        u = units.get(f.unit_id or "")
        loc = L.finding_loc(f)
        sev = f.severity.value
        head = f"#{num} {SEVERITY_TR.get(sev, sev)} · {f.check}" + (f" · {f.unit_id}" if f.unit_id else "")
        lines = [f.message] + detail_lines(f)
        if loc.note:
            lines.append(loc.note)
        marked = [p for p in loc.all_pages() if loc.rects.get(p)]
        if marked:
            page = marked[0]
        elif loc.pages:
            page = loc.pages[0]
        elif f.check in SUMMARY_TABLE_CHECKS and summary_page:
            page = summary_page
            lines.append("Konum işaretlenmedi; not, özet/süre tablosunun sayfasına konuldu.")
        else:
            page = 1
            lines.append("Bu bulgunun PDF'de konumu yok; not ilk sayfaya konuldu.")
        content = "\n".join([head] + lines)
        for p in marked:
            marks.append((p, loc.rects[p], FINDING_HIGHLIGHT, f.check, content))
        n = _Note(page, _first_anchor(loc, page), head, lines, SEVERITY_COLORS.get(sev, SEVERITY_COLORS["INFO"]), num)
        notes.append(n)
        finding_notes[num] = n
        for p in marked[1:]:
            notes.append(_Note(p, _first_anchor(loc, p), f"#{num} (devam) · {f.check}", [f"İlk işaret: s.{page}"], n.colors))
        toc_items.append((f.unit_id or "", num, page, n.anchor, f"#{num} {SEVERITY_TR.get(sev, sev)} · {f.check}" + (f" · {f.details['code_raw']}" if f.details.get("code_raw") else "")))

        if f.check == "USED_NOT_DECLARED" and u is not None and f.details.get("code_raw"):
            prefix, secs = _decl_sections(res, u, f.details["code_raw"])
            for s in secs or [None]:
                key = (u.id, s.path if s is not None else None, prefix or "")
                ev = evidence.get(key)
                if ev is None:
                    eloc = L.section_loc(u, s) if s is not None else L.fields_loc(f"{u.id} — tema başlığı", [u.title])
                    ev = evidence[key] = _Evidence(u, s, eloc)
                ev.codes.append((f.details["code_raw"], num))
                ev.usage.append((page, n.anchor))

    # Kanıt kutuları (tanım bölümü) ve iki yönlü bağlantılar
    for (uid, path, prefix), ev in evidence.items():
        marked = [p for p in ev.loc.all_pages() if ev.loc.rects.get(p)]
        page = marked[0] if marked else (ev.loc.pages[0] if ev.loc.pages else (ev.unit.pages[0] if ev.unit.pages else 1))
        used = ", ".join(f"{c} (#{k})" for c, k in ev.codes)
        if ev.section is not None:
            declared = [d.code.normalized for d in ev.unit.declarations.get(ev.section.path, []) if d.code.prefix == prefix]
            head = f"Kanıt · {uid} tanım bölümü: {ev.section.path}"
            lines = [f"Uygulamalarda kullanılmış, bu bölümde tanımlı değil: {used}"]
            lines.append(f"Bu bölümde tanımlı {prefix} kodları: {', '.join(declared)}" if declared else f"Bu bölümde {prefix} önekli tanım yok.")
        else:
            head = f"Kanıt · {uid} tanım bölümleri"
            lines = [f"Temanın hiçbir tanım bölümünde {prefix} önekli kod tanımlanmamış.", f"Uygulamalarda kullanılan: {used}"]
        if ev.loc.note:
            lines.append(ev.loc.note)
        lines.append(f"Kullanım yeri: s.{ev.usage[0][0]} (kutuya tıklayın)")
        for p in marked:
            marks.append((p, ev.loc.rects[p], EVIDENCE_HIGHLIGHT, "Tanım bölümü (kanıt)", "\n".join([head] + lines)))
        anchor = _first_anchor(ev.loc, page)
        notes.append(_Note(page, anchor, head, lines, EVIDENCE_COLORS, link=ev.usage[0]))
        for p in marked[1:]:
            notes.append(_Note(p, _first_anchor(ev.loc, p), f"{head} (devam)", [f"İlk işaret: s.{page}"], EVIDENCE_COLORS))
        for _, k in ev.codes:
            fn = finding_notes[k]
            if fn.link is None:
                fn.link = (page, anchor)
                fn.lines.append(f"Tanım bölümü: s.{page}" + (f" ({ev.section.path}, mavi işaret)" if ev.section is not None else "") + " — kutuya tıklayın")

    # Orijinalin kopyası üzerinde çalışılır ve ARTIMLI kaydedilir: orijinal baytlar aynen kalır, değişiklikler sona
    # eklenir (yeniden kaydetmek nesne akışlarını açıp dosyayı birkaç kat büyütüyor).
    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    shutil.copyfile(res.source, tmp)
    doc = fitz.open(tmp)
    try:
        _draw(doc, res, findings, notes, marks, toc_items)
        if not doc.can_save_incrementally():
            return doc.tobytes(garbage=3, deflate=True)
        doc.save(tmp, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
        doc.close()
        with open(tmp, "rb") as fh:
            return fh.read()
    finally:
        if not doc.is_closed:
            doc.close()
        os.remove(tmp)


def _draw(doc: fitz.Document, res: ExtractionResult, findings: list[Finding], notes: list[_Note], marks: list, toc_items: list) -> None:
    by_page: dict[int, list[_Note]] = {}
    for n in notes:
        by_page.setdefault(n.page, []).append(n)
    for p, ns in by_page.items():
        page = doc[p - 1]
        w0, h = page.rect.width, page.rect.height
        for n in ns:
            n.h = _measure(n)
        cols = _layout(ns, h, w0)
        mb, cb = page.mediabox, page.cropbox
        extra = cols * COL_W + 8
        page.set_mediabox(fitz.Rect(mb.x0, mb.y0, mb.x1 + extra, mb.y1))
        page.set_cropbox(fitz.Rect(cb.x0, cb.y0, cb.x1 + extra, cb.y1))
        page.draw_line((w0 + 2, 0), (w0 + 2, h), color=(0.75, 0.75, 0.75), width=0.5)
    for p, rects, color, title, content in marks:
        _highlight(doc[p - 1], rects, color, title, content)
    for n in notes:
        page = doc[n.page - 1]
        stroke, fill = n.colors
        if n.anchor is not None:
            a = n.anchor
            page.draw_line((a[2] + 1, (a[1] + a[3]) / 2), (n.rect.x0, n.rect.y0 + 6), color=stroke, width=0.6, dashes="[2 1.5] 0", stroke_opacity=0.7)
            page.draw_circle((a[2] + 1, (a[1] + a[3]) / 2), 1.3, color=stroke, fill=stroke)
        page.draw_rect(n.rect, color=stroke, fill=fill, width=0.7)
        _write(page, n)
        if n.link is not None:
            tp, ta = n.link
            to = fitz.Point(0, max(0.0, ta[1] - 20)) if ta else fitz.Point(0, 0)
            page.insert_link({"kind": fitz.LINK_GOTO, "from": n.rect, "page": tp - 1, "to": to, "zoom": 0})

    _set_toc(doc, res, findings, toc_items)


def _set_toc(doc: fitz.Document, res: ExtractionResult, findings: list[Finding], items) -> None:
    if not items:
        return
    labels = {u.id: _unit_label(u) for u in res.units}
    order = [u.id for u in res.units if any(i[0] == u.id for i in items)] + ([""] if any(i[0] == "" for i in items) else [])
    first = min(i[2] for i in items)
    toc: list[list] = [[1, f"Program Kontrol bulguları ({len(findings)})", first]]
    for uid in order:
        its = [i for i in items if i[0] == uid]
        toc.append([2, labels.get(uid, "Genel bulgular") if uid else "Genel bulgular", its[0][2]])
        for _, _, page, anchor, title in its:
            dest = {"kind": fitz.LINK_GOTO, "to": fitz.Point(0, max(0.0, anchor[1] - 20)) if anchor else fitz.Point(0, 0), "zoom": 0}
            toc.append([3, title, page, dest])
    original = doc.get_toc(simple=False)
    try:
        doc.set_toc(toc + original)
    except Exception:  # orijinal içindekiler bozuksa yalnızca bulgular
        doc.set_toc(toc)
