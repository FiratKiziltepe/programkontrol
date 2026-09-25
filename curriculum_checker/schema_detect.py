"""Program yapısının PDF'in kendi yapı/tanıtım sayfasından keşfi + özet/süre tablosunun okunması.

Program bazında başlık/kod hardcode edilmez:
- bölüm başlıkları (metin, sıra, stil) yapı sayfasındaki etiket span'larından,
- tema/ünite başlık anahtar kelimesi ve rengi yapı sayfasındaki örnek başlıktan,
- öğrenme çıktısı kod öneki ve segment sayısı yapı sayfasındaki örnek koddan öğrenilir.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

import fitz

from models import ExpectedLoListColumn, ExpectedRow, ExpectedTable, LabelDef, ProgramSchema, Span, TableRole, TextField
from pdf_extract import (
    UPPER_SEGMENT,
    PdfDoc,
    font_rank,
    group_rows,
    lo_code_regex,
    make_field,
    norm_label,
    row_text,
    tr_lower,
    tr_upper,
)

# Yapı/tanıtım bölümünü bulmak için başlık ipuçları (PRD §7).
STRUCTURE_HINTS = ("YAPISI", "STRUCTURE")
# Özet tablosu sütun ipuçları (Türkçe / İngilizce programlar).
LO_COLUMN_HINTS = (("öğrenme", "çıktı"), ("learning", "outcome"))
HOURS_COLUMN_HINTS = (("saat",), ("hour",))
ORDER_COLUMN_HINTS = (("sıra",), ("order",), ("sequence",))
# Alan becerileri tanım bölümü başlığı ipuçları (kod çapraz kontrolü dışında tutulur).
FIELD_SKILL_HINTS = (("alan", "beceri"), ("field", "skill"))

NUMBERED_NAME_RE = re.compile(r"^\s*(\d+)\s*\.\s*(\S.*)$", re.S)
# Anahtar kelime birden fazla sözcük olabilir (Hayat Bilgisi "3. ÖĞRENME ALANI: AİLEM VE TOPLUM").
UNIT_TITLE_RE = re.compile(r"^\s*(\d+)\s*\.\s*([^\W\d_]+(?:[ \t]+[^\W\d_]+){0,2})\s*:\s*(\S.*)$", re.S)


class SchemaError(Exception):
    pass


def body_color(doc: PdfDoc) -> int:
    c: Counter[int] = Counter()
    for s in doc.spans:
        if s.id not in doc.furniture:
            c[s.color] += len(s.text.strip())
    return c.most_common(1)[0][0]


BODY_COLOR_TOL = 40


def near_colors(doc: PdfDoc, base: int, tol: int = 10) -> frozenset[int]:
    """Baskın gövde rengine gözle ayırt edilemeyecek kadar yakın renkler (ör. #221F1F ve #231F20).

    Bazı PDF'lerde gövde metni bu iki tonla karışık basılır; ikisi de gövde metnidir."""
    def rgb(c: int) -> tuple[int, int, int]:
        return (c >> 16) & 255, (c >> 8) & 255, c & 255

    b = rgb(base)
    return frozenset(
        s.color for s in doc.spans if max(abs(x - y) for x, y in zip(rgb(s.color), b)) <= tol
    ) | {base}


def _content_spans(doc: PdfDoc, page: int) -> list[Span]:
    return [s for s in doc.page_spans(page) if s.id not in doc.furniture and s.text.strip()]


def find_structure(doc: PdfDoc, body: frozenset[int]) -> tuple[Span, Span, list[int]]:
    """(yapı başlığı span'ı, örnek tema başlığı span'ı, yapı sayfaları)."""
    for s in doc.spans:
        if s.id in doc.furniture or s.color in body:
            continue
        if not any(h in tr_upper(s.text) for h in STRUCTURE_HINTS):
            continue
        # İçindekiler sayfasını elemek için: aynı sayfada gövde renginde olmayan
        # "N. KELİME: ..." biçiminde örnek bir birim başlığı bulunmalı.
        titles = [
            t
            for t in _content_spans(doc, s.page)
            if t.color not in body and t.color != s.color and UNIT_TITLE_RE.match(t.text)
        ]
        if not titles:
            continue
        sample = titles[0]
        pages = [s.page]
        for p in range(s.page + 1, doc.page_count + 1):
            spans = _content_spans(doc, p)
            big = any(x.size >= s.size * 0.95 for x in spans)
            has_title = any(x.color == sample.color and UNIT_TITLE_RE.match(x.text) for x in spans)
            if big or has_title or not spans:
                break
            pages.append(p)
        return s, sample, pages
    raise SchemaError("Program yapısı/tanıtım sayfası bulunamadı")


def merge_label_lines(label_spans: list[Span]) -> list[list[Span]]:
    """Aynı etikete ait çok satırlı etiket span'larını birleştirir (layout ile)."""
    rows = group_rows(label_spans)
    # Aynı satırda farklı renkteki etiketleri ayır
    lines: list[list[Span]] = []
    for r in rows:
        by_color: dict[int, list[Span]] = {}
        for s in r:
            by_color.setdefault(s.color, []).append(s)
        lines.extend(by_color.values())
    labels: list[list[Span]] = []
    for ln in lines:
        if labels:
            prev = labels[-1][-1]
            cur = ln[0]
            gap = cur.y0 - prev.y0
            x_ok = min(prev.x1, ln[-1].x1) - max(labels[-1][0].x0, cur.x0) > -2 or abs(prev.x1 - ln[-1].x1) < 4
            # Font derecesi değişiyorsa ayrı başlıktır (ör. Kurmanca: "ÖĞRENME-ÖĞRETME YAŞANTILARI" Bold,
            # hemen altındaki "Temel Kabuller" Medium); parantezle başlayan devam satırı hariç
            # ("ÖĞRENME KANITLARI" + "(Ölçme ve Değerlendirme)").
            rank_ok = font_rank(cur.font) == font_rank(prev.font) or cur.text.lstrip().startswith("(")
            if cur.page == prev.page and cur.color == prev.color and 0 < gap <= 1.6 * prev.size and x_ok and rank_ok:
                labels[-1].extend(ln)
                continue
        labels.append(list(ln))
    return labels


def learn_labels(doc: PdfDoc, heading: Span, sample_title: Span, pages: list[int], body: frozenset[int]) -> tuple[list[int], list[LabelDef]]:
    cand: list[Span] = []
    for p in pages:
        for s in _content_spans(doc, p):
            if s.id == heading.id or s.color in body or s.color == sample_title.color or s.size >= heading.size * 0.95:
                continue
            cand.append(s)
    colors = sorted({s.color for s in cand})
    labels: list[LabelDef] = []
    for grp in merge_label_lines(cand):
        f = make_field(grp)
        # Bileşik başlık ("İlkeler/ Anahtar Kavramlar/"): tema sayfalarında parçaları ayrı
        # başlık olarak basılabilir; parçalar da bu başlığa ait tanınır.
        parts = [norm_label(p) for p in f.text.split("/") if norm_label(p)]
        labels.append(
            LabelDef(
                text=f.text.replace("\n", " "),
                norm=norm_label(f.text),
                parts=parts if len(parts) > 1 else [],
                rank=font_rank(grp[0].font),
                color=grp[0].color,
                source_spans=f.source_spans,
            )
        )
    return colors, labels


def learn_lo_code(doc: PdfDoc, pages: list[int], body: frozenset[int]) -> tuple[str, list[str], Span]:
    """Yapı sayfasındaki örnek öğrenme çıktısı kodundan önek ve segment tipleri.

    En az üç segment (en az ikisi sayı) aranır; son segment büyük harfli bir kısaltma
    olabilir (ör. "ARN.5.1.D." -> ["n", "n", "a"]).
    """
    pat = re.compile(rf"^\s*([^\W\d_]+)[\s.]*(\d+(?:[\s.]+\d+)+(?:[\s.]+{UPPER_SEGMENT}(?=[.\s]|$))?)")
    for p in pages:
        for s in _content_spans(doc, p):
            if s.color not in body:
                continue
            m = pat.match(s.text)
            if m:
                types = ["n" if x.isdigit() else "a" for x in re.findall(r"\d+|[^\W\d_]+", m.group(2))]
                if len(types) >= 3:
                    return m.group(1), types, s
    raise SchemaError("Yapı sayfasında örnek öğrenme çıktısı kodu bulunamadı")


def confirm_label_colors(doc: PdfDoc, labels: list[LabelDef], structure_colors: list[int], excluded: frozenset[int], data_start: int) -> list[int]:
    """Bölüm başlığı renkleri tema sayfalarında doğrulanır.

    Yapı sayfasındaki başlık rengi tema sayfalarındakinden farklı olabilir (Kimya: yapı sayfasında
    #0098B9, tema sayfalarında #01B49C; #0098B9 orada "9. SINIF TEMALARI" gibi sınıf başlıklarında).
    Tema sayfalarında en az iki farklı sözlük başlığıyla birebir eşleşen renkler başlık rengidir.
    Hiçbir renk doğrulanamazsa yapı sayfasındaki renkler kullanılır (tahmin yok)."""
    vocab = {l.norm for l in labels} | {p for l in labels for p in l.parts}
    by_color: dict[int, list[Span]] = defaultdict(list)
    for s in doc.spans:
        if s.page >= data_start and s.id not in doc.furniture and s.text.strip() and s.color not in excluded:
            by_color[s.color].append(s)
    matched: dict[int, set[str]] = {}
    for color, spans in by_color.items():
        matched[color] = {n for grp in merge_label_lines(spans) if (n := norm_label(" ".join(x.text for x in grp))) in vocab}
    confirmed = [c for c, m in matched.items() if len(m) >= 2]
    # Onaylı bir başlık rengine gözle ayırt edilemeyecek kadar yakın ve sözlük başlığıyla birebir eşleşen
    # ton da başlık rengidir (Hayat Bilgisi s.50: "Öğrenme-Öğretme Uygulamaları" #A04D84, diğerleri #A25394).
    near = [c for c, m in matched.items() if m and c not in confirmed and any(_color_dist(c, k) <= LABEL_COLOR_TOL for k in confirmed)]
    return sorted(confirmed + near) or structure_colors


LABEL_COLOR_TOL = 20


def _color_dist(a: int, b: int) -> int:
    return max(abs(((a >> s) & 255) - ((b >> s) & 255)) for s in (16, 8, 0))


def detect_schema(doc: PdfDoc) -> ProgramSchema:
    dominant = body_color(doc)
    # Gövde kümesi daha geniş tutulur: Fen s.16 açıklamaları #000000/#000C14, gövde #221F1F;
    # s.127'de bileşen içindeki tek kelime "Işığın" #000000. Hepsi siyaha yakın gövde metnidir.
    body = near_colors(doc, dominant, tol=BODY_COLOR_TOL)
    heading, sample, pages = find_structure(doc, body)
    label_colors, labels = learn_labels(doc, heading, sample, pages, body)
    keyword = UNIT_TITLE_RE.match(sample.text).group(2)
    prefix, seg_types, lo_span = learn_lo_code(doc, pages, body)
    data_start = None
    for s in doc.spans:
        if s.page > pages[-1] and s.color == sample.color and _is_unit_title(s.text, keyword):
            data_start = s.page
            break
    if data_start is None:
        raise SchemaError("Yapı sayfasından sonra gerçek tema/ünite başlığı bulunamadı")
    title_colors = near_colors(doc, sample.color)
    label_colors = confirm_label_colors(doc, labels, label_colors, body | title_colors, data_start)
    return ProgramSchema(
        structure_pages=pages,
        structure_heading=make_field([heading]),
        unit_keyword=keyword,
        unit_title_color=sample.color,
        unit_title_colors=sorted(title_colors),
        body_color=dominant,
        body_colors=sorted(body),
        label_colors=label_colors,
        labels=labels,
        lo_prefix=prefix,
        lo_segments=len(seg_types),
        lo_segment_types=seg_types,
        lo_example=make_field([lo_span]),
        data_start_page=data_start,
    )


def parse_unit_title(text: str, keyword: str) -> tuple[int, str, bool] | None:
    """(sıra, ad, standart_biçim). Standart biçim yapı sayfasındaki "N. KELİME: Ad" biçimidir;
    "KELİME N: Ad" biçimi de birim başlığı sayılır ama standart dışıdır (ör. "TEMA 3: SEYAHAT")."""
    t = text.replace("\n", " ")
    m = UNIT_TITLE_RE.match(t)
    if m and norm_label(m.group(2)) == norm_label(keyword):
        return int(m.group(1)), m.group(3).strip(), True
    m = re.match(r"^\s*([^\W\d_]+(?:[ \t]+[^\W\d_]+){0,2})\s+(\d+)\s*:\s*(\S.*)$", t, re.S)
    if m and norm_label(m.group(1)) == norm_label(keyword):
        return int(m.group(2)), m.group(3).strip(), False
    return None


def label_lookup(schema: ProgramSchema) -> dict[str, int]:
    """Başlık anahtarı (norm) -> yapı sayfasındaki başlığın sırası. Bileşik başlıkların parçaları dahil."""
    out: dict[str, int] = {}
    for i, l in enumerate(schema.labels):
        out[l.norm] = i
        for p in l.parts:
            out.setdefault(p, i)
    return out


def compound_subset_of(text: str, labels: list[LabelDef], partial: bool = False, allow_unknown: bool = False) -> str | None:
    """Tema sayfasındaki başlık, yapı sayfasındaki bileşik başlığın ("Genellemeler/ İlkeler/ Anahtar
    Kavramlar/ Semboller vb.") parçalarından birkaçının "/" ile yazılmış hali mi? (ör. Fen s.98
    "Genellemeler/Anahtar Kavramlar"). Parçalar yapı sayfasındaki sırayla gelmelidir.
    partial=True: son parça henüz tamamlanmamış olabilir (çok satırlı başlık birleştirilirken).
    allow_unknown=True: yapı sayfasında olmayan parçalar atlanır, en az bir parça eşleşmelidir (yalnızca
    çok satırlı başlığın satırlarını birleştirmek için; ör. Fen s.217 "Yasalar/Anahtar" + "Kavramlar").
    Eşleşen bileşik başlığın anahtarını döndürür."""
    pieces = [norm_label(p) for p in text.split("/")]
    if pieces and not pieces[-1]:
        pieces = pieces[:-1]  # sondaki "/"
    if len(pieces) < 2 or not all(pieces):
        return None
    for l in labels:
        if not l.parts:
            continue
        pos, hits = -1, 0
        for n, piece in enumerate(pieces):
            last = partial and n == len(pieces) - 1
            nxt = next((i for i in range(pos + 1, len(l.parts)) if l.parts[i] == piece or (last and l.parts[i].startswith(piece))), None)
            if nxt is None:
                if allow_unknown:
                    continue
                break
            pos, hits = nxt, hits + 1
        else:
            if hits:
                return l.norm
    return None


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def label_variant_of(norm: str, keys) -> str | None:
    """Öğrenilmiş başlıklardan birinin küçük bir yazım varyantı mı? (ör. "…Uygulamalar" ~ "…Uygulamaları")

    Yalnızca tek bir aday küçük farkla eşleşiyorsa döner; aksi halde None (tahmin yok). Kısa başlıklarda
    tek harf farkı kabul edilir: "Deneyler" ile "Değerler" (2 harf) farklı başlıklardır (Fizik s.26)."""
    if len(norm) < 8:
        return None
    limit = 1 if len(norm) < 12 else 2
    cands = [k for k in keys if len(k) >= 8 and _edit_distance(norm, k) <= limit]
    return cands[0] if len(cands) == 1 else None


def label_prefix_variant(norm: str, keys) -> bool:
    """Birleşmekte olan başlık metni, öğrenilmiş bir başlığın başına küçük yazım farkıyla uyuyor mu?
    (ör. "Öğrenme-Öğreme" ~ "Öğrenme-Öğretme …"; ikinci satır ancak bu durumda birleştirilir)"""
    if len(norm) < 8:
        return False
    return any(
        _edit_distance(norm, k[:n]) <= 2 for k in keys for n in (len(norm) - 1, len(norm), len(norm) + 1) if len(k) >= n
    )


def _is_unit_title(text: str, keyword: str) -> bool:
    return parse_unit_title(text, keyword) is not None


# ---------------------------------------------------------------- özet / süre tablosu


def _hint(text: str, hints) -> bool:
    # noktalı/noktasız i farkı yok sayılır ("ALAN BECERILERI" gibi kodlanmış başlıklar için)
    t = tr_lower(text).replace("ı", "i")
    return any(all(h.replace("ı", "i") in t for h in group) for group in hints)


def _int(text: str | None) -> int | None:
    if text is None:
        return None
    t = text.strip()
    return int(t) if t.isdigit() else None


def parse_expected_tables(doc: PdfDoc, schema: ProgramSchema) -> list[ExpectedTable]:
    fz = fitz.open(doc.path)
    tables: list[ExpectedTable] = []
    small_glyphs = fitz.TOOLS.set_small_glyph_heights()  # find_tables bu global ayarı değiştirir
    try:
        last_page = schema.structure_pages[0] - 1
        for pno in range(1, last_page + 1):
            spans = _content_spans(doc, pno)
            page_txt = " ".join(s.text for s in spans)
            if not _hint(page_txt, LO_COLUMN_HINTS):
                continue
            prev_bottom = 0.0
            for t in fz[pno - 1].find_tables().tables:
                title = _table_title(t.bbox, spans, schema, prev_bottom)
                prev_bottom = t.bbox[3]
                et = _parse_lo_list(t, spans, pno, len(tables), schema, title) or _parse_table(t, spans, pno, len(tables), schema, title)
                if et is not None:
                    tables.append(et)
    finally:
        fz.close()
        fitz.TOOLS.set_small_glyph_heights(small_glyphs)
    _assign_alternatives(tables)
    return tables


def _table_total_hours(t: ExpectedTable) -> int | None:
    total = next((r for r in t.rows if r.is_total), None)
    return total.hours if total is not None else None


def _assign_alternatives(tables: list[ExpectedTable]) -> None:
    """Aynı başlıklı birden fazla süre tablosu (Afet: "AFET BİLİNCİ I. DÜZEY" haftada 2 saat ve 1 saat):
    toplam ders saati tek başına en büyük olan tam program tablosudur (beklenen sayılar ondan alınır),
    diğerleri sınırlı (alternatif) tablodur. En büyük saat tekil değilse roller değişmez; eşleştirme
    belirsiz kalır ve NEEDS_REVIEW üretilir (tahmin yok)."""
    groups: dict[str, list[ExpectedTable]] = defaultdict(list)
    for t in tables:
        if t.role == TableRole.SUMMARY and t.title is not None:
            groups[norm_label(t.title.text)].append(t)
    for group in groups.values():
        if len(group) < 2:
            continue
        hours = [_table_total_hours(t) for t in group]
        if any(h is None for h in hours):
            continue
        top = max(hours)
        if hours.count(top) != 1:
            continue
        for t, h in zip(group, hours):
            if h != top:
                t.role = TableRole.ALTERNATIVE


def _table_title(bbox, spans: list[Span], schema: ProgramSchema, prev_bottom: float) -> TextField | None:
    """Tablonun başlığı: tablonun üstündeki en yakın başlık renkli (gövde renginde olmayan) satır bloğu.

    Başlık ile tablo arasında açıklama cümlesi olabilir (Afet s.10: "AFET BİLİNCİ I. DÜZEY" / "Afet
    bilinci I. düzey dersinin haftalık ders çizelgesinde iki (2) ders saati …" / tablo). Aynı renk ve
    boyuttaki sıkı satırlar tek başlıktır (Afet s.12 iki satırlık başlık). Başlık renkli satır yoksa
    tablonun hemen üstündeki satır alınır."""
    tx0, ty0, tx1, _ = bbox
    body = set(schema.body_colors) or {schema.body_color}
    band = [s for s in spans if s.y1 <= ty0 + 1 and s.y0 >= max(prev_bottom, ty0 - 90) and s.x1 >= tx0 and s.x0 <= tx1]
    rows = group_rows(band)

    def heading(r: list[Span]) -> bool:
        return sum(len(s.text.strip()) for s in r if s.color not in body) > sum(len(s.text.strip()) for s in r) / 2

    idx = [i for i, r in enumerate(rows) if heading(r)]
    if idx:
        k = idx[-1]
        block = [rows[k]]
        while k > 0 and heading(rows[k - 1]):
            a, b = rows[k - 1][0], block[0][0]
            if a.color != b.color or abs(a.size - b.size) > 0.5 or b.y0 - a.y1 > 0.6 * a.size:
                break
            k -= 1
            block.insert(0, rows[k])
        return make_field([s for r in block for s in r])
    near = [r for r in rows if r[0].y1 >= ty0 - 40]
    return make_field(near[-1]) if near else None


def _parse_lo_list(t, spans: list[Span], pno: int, index: int, schema: ProgramSchema, title: TextField | None) -> ExpectedTable | None:
    """Yatay birim -> öğrenme çıktısı kodları tablosu (Afet s.12): ilk sütunda birim anahtar kelimesi
    ("ÜNİTE") ve öğrenme çıktısı satır başlıkları, diğer sütunlarda birim adı ve kodlar."""
    rows = [[c for c in r.cells if c is not None] for r in t.rows]
    if len(rows) < 2 or any(len(r) < 2 for r in rows):
        return None
    first = [make_field(_spans_in(spans, r[0])) for r in rows]
    kw = norm_label(schema.unit_keyword)
    name_i = next((i for i, f in enumerate(first) if f is not None and norm_label(f.text) == kw), None)
    lo_i = next((i for i, f in enumerate(first) if f is not None and _hint(f.text, LO_COLUMN_HINTS)), None)
    if name_i is None or lo_i is None or len(rows[name_i]) != len(rows[lo_i]):
        return None
    lo_re = re.compile(lo_code_regex(schema.lo_prefix, schema.lo_segment_types).pattern + r"\s*$")
    cols: list[ExpectedLoListColumn] = []
    for j in range(1, len(rows[name_i])):
        name = make_field(_spans_in(spans, rows[name_i][j]))
        order = None
        if name is not None and (m := NUMBERED_NAME_RE.match(name.text)):
            order = int(m.group(1))
        codes, unparsed = [], []
        for r in group_rows(_spans_in(spans, rows[lo_i][j])):
            f = make_field(r)
            (codes if lo_re.match(f.text) else unparsed).append(f)
        cols.append(ExpectedLoListColumn(order=order, name=name, codes=codes, unparsed=unparsed))
    return ExpectedTable(index=index, page=pno, title=title, rows=[], role=TableRole.LO_LIST, lo_columns=cols)


def _spans_in(spans: list[Span], bbox) -> list[Span]:
    x0, y0, x1, y1 = bbox
    return [s for s in spans if x0 - 1 <= (s.x0 + s.x1) / 2 <= x1 + 1 and y0 - 1 <= s.yc <= y1 + 1]


def _parse_table(t, spans: list[Span], pno: int, index: int, schema: ProgramSchema, title: TextField | None) -> ExpectedTable | None:
    rows = []
    for r in t.rows:
        cells = []
        for c in r.cells:
            if c is None:
                continue
            f = make_field(_spans_in(spans, c))
            cells.append((c, f))
        rows.append(cells)
    header_cells, data_rows = [], []
    for cells in rows:
        numeric = any(f is not None and (_int(f.text) is not None or f.text.strip() == "-") for _, f in cells)
        if numeric or data_rows:
            data_rows.append(cells)
        else:
            header_cells.extend(c for c in cells if c[1] is not None)
    if not header_cells:
        return None

    # Ad sütunu: başlığı birim anahtar kelimesine eşit olan (ör. "TEMA"), yoksa anahtar kelimeyi
    # içeren en soldaki sütun (ör. "Ana Temalar"; sağındaki "Alt Temalar" ad değildir).
    kw = norm_label(schema.unit_keyword)
    name_cands = [(c, f) for c, f in header_cells if kw in norm_label(f.text) and not _hint(f.text, LO_COLUMN_HINTS)]
    exact = [cf for cf in name_cands if norm_label(cf[1].text) == kw]
    name_cell = (exact or sorted(name_cands, key=lambda cf: cf[0][0]) or [None])[0]

    def role_of(x: float) -> str | None:
        covering = [(c, f) for c, f in header_cells if c[0] - 1 <= x <= c[2] + 1]
        if not covering:
            return None
        c, f = min(covering, key=lambda cf: cf[0][2] - cf[0][0])
        if _hint(f.text, LO_COLUMN_HINTS):
            return "lo"
        if _hint(f.text, HOURS_COLUMN_HINTS):
            return "hours"
        if _hint(f.text, ORDER_COLUMN_HINTS):
            return "order"
        if name_cell is not None and c == name_cell[0]:
            return "name"
        return None

    if not any(_hint(f.text, LO_COLUMN_HINTS) for _, f in header_cells):
        return None
    has_order_col = any(_hint(f.text, ORDER_COLUMN_HINTS) for _, f in header_cells)
    out_rows: list[ExpectedRow] = []
    for cells in data_rows:
        # Aynı sütun başlığı altına düşen hücreler birleştirilir. Başlıksız ve yalnızca "N."
        # içeren hücre (ör. Temel Dinî Bilgiler'de ad hücresinin solundaki "1.") sıra hücresidir.
        role_spans: dict[str, list[Span]] = {}
        for c, f in cells:
            if f is None:
                continue
            role = role_of((c[0] + c[2]) / 2)
            if (
                role is None
                and not has_order_col
                and name_cell is not None
                and c[2] <= name_cell[0][0] + 1
                and re.fullmatch(r"\s*\d+\s*\.\s*", f.text)
            ):
                role = "order"
            if role:
                role_spans.setdefault(role, []).extend(_spans_in(spans, c))
        vals = {r: f for r, sp in role_spans.items() if (f := make_field(sp)) is not None}
        if not vals:
            continue  # tablo çizgilerinin oluşturduğu boş satır (ör. Fen s.12 toplamın altı)
        order = _int(vals["order"].text.strip().rstrip(".")) if "order" in vals else None
        if order is None and "order" not in vals and not has_order_col and "name" in vals:
            # Sıra sütunu yoksa sıra, ad hücresinin başındaki "N." ifadesidir (ör. "1. Yapay Zekâ")
            m = NUMBERED_NAME_RE.match(vals["name"].text)
            order = int(m.group(1)) if m else None
        lo_f = vals.get("lo")
        out_rows.append(
            ExpectedRow(
                table_index=index,
                order=order,
                name=vals.get("name"),
                lo_count_raw=lo_f.text if lo_f else None,
                lo_count=_int(lo_f.text) if lo_f else None,
                hours=_int(vals["hours"].text) if "hours" in vals else None,
            )
        )
    # Sıra numarası olmayan ve sayısal öğrenme çıktısı değeri olan son satır: tablonun toplam satırı
    if out_rows and out_rows[-1].order is None and out_rows[-1].lo_count is not None:
        out_rows[-1].is_total = True
    if not out_rows:
        return None  # veri satırı olmayan tablo (ör. Hayat Bilgisi s.3 içindekiler)
    return ExpectedTable(index=index, page=pno, title=title, rows=out_rows)
