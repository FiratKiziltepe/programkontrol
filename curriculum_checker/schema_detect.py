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


def learn_labels(doc: PdfDoc, heading: Span | None, sample_title: Span, pages: list[int], body: frozenset[int], size_cap: float) -> tuple[list[int], list[LabelDef]]:
    cand: list[Span] = []
    for p in pages:
        for s in _content_spans(doc, p):
            if (heading is not None and s.id == heading.id) or s.color in body or s.color == sample_title.color or s.size >= size_cap * 0.95:
                continue
            if not any(ch.isalnum() for ch in s.text):
                continue  # başlık renginde örnek içerik işareti (Afet s.13: "ALAN" yanında "-")
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


def _labels_used_in_units(doc: PdfDoc, labels: list[LabelDef], excluded: frozenset[int], data_start: int) -> list[LabelDef]:
    """Tema sayfalarında hiç geçmeyen yapı sayfası metni bölüm başlığı değildir (ör. yapı sayfasının
    kendi başlığı ya da açıklama notu). Hiçbiri geçmiyorsa liste değiştirilmez (tahmin yok)."""
    by_color: dict[int, list[Span]] = defaultdict(list)
    for s in doc.spans:
        if s.page >= data_start and s.id not in doc.furniture and s.text.strip() and s.color not in excluded:
            by_color[s.color].append(s)
    seen: set[str] = set()
    for spans in by_color.values():
        for grp in merge_label_lines(spans):
            seen.add(norm_label(" ".join(x.text for x in grp)))
            seen.update(norm_label(p) for p in " ".join(x.text for x in grp).split("/"))
    used = [l for l in labels if l.norm in seen or any(p in seen for p in l.parts) or any(v.startswith(l.norm) for v in seen if len(l.norm) >= 4)]
    return used or labels


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


def find_unit_titles(doc: PdfDoc, body: frozenset[int]) -> tuple[str, list[Span]]:
    """Belge genelinde birim başlıkları ("N. TEMA: …", "N. ÜNİTE: …", "N. ÖĞRENME ALANI: …").

    Gövde renginde olmayan ve birim başlığı biçimindeki span'lar toplanır; en çok sayfada geçen
    anahtar kelime birim anahtar kelimesidir. Program bazında kelime hardcode edilmez."""
    cands = [s for s in doc.spans if s.id not in doc.furniture and s.color not in body and UNIT_TITLE_RE.match(s.text)]
    pages_by_kw: dict[str, set[int]] = defaultdict(set)
    for s in cands:
        pages_by_kw[norm_label(UNIT_TITLE_RE.match(s.text).group(2))].add(s.page)
    if not pages_by_kw:
        raise SchemaError("PDF'de tema/ünite/öğrenme alanı başlığı (\"1. TEMA: …\" biçiminde) bulunamadı")
    kw_norm = max(pages_by_kw, key=lambda k: len(pages_by_kw[k]))
    titles = [s for s in cands if norm_label(UNIT_TITLE_RE.match(s.text).group(2)) == kw_norm]
    keyword = Counter(UNIT_TITLE_RE.match(s.text).group(2) for s in titles).most_common(1)[0][0]
    return keyword, titles


def locate_structure(doc: PdfDoc, body: frozenset[int], titles: list[Span]) -> tuple[Span | None, Span | None, list[int]]:
    """(yapı başlığı, yapı sayfasındaki örnek birim başlığı, yapı sayfaları); bulunamazsa (None, None, []).

    Yapı sayfası, gerçek bir tema sayfasının küçültülmüş örneğidir. Şunlardan biriyle tanınır:
    - "…YAPISI" başlığından sonraki ilk birim başlıklı sayfa (başlık ile şema ayrı sayfalarda
      olabilir; Matematik: başlık s.12, şema s.17-18),
    - birim başlığı diğer birim başlıklarından belirgin biçimde küçük basılmış sayfa.
    İçindekiler sayfasındaki "…YAPISI" satırı elenir: ilk birim başlıklı sayfadan önceki son ipucu alınır."""
    title_color = Counter(s.color for s in titles).most_common(1)[0][0]
    titles = sorted((s for s in titles if s.color in near_colors(doc, title_color)), key=lambda s: (s.page, s.y0))
    if not titles:
        return None, None, []
    median_size = sorted(s.size for s in titles)[len(titles) // 2]
    first_title_page = titles[0].page
    hints = [
        s
        for s in doc.spans
        if s.id not in doc.furniture and s.color not in body and s.page <= first_title_page and any(h in tr_upper(s.text) for h in STRUCTURE_HINTS)
    ]
    heading = hints[-1] if hints else None
    sample = None
    if heading is not None:
        after = [t for t in titles if t.page >= heading.page]
        if after and after[0].page - heading.page <= 10:
            t = after[0]
            # Örnek şemadan hemen sonraki birim başlığı aynı birimdir (Matematik s.17 şema, s.19 gerçek tema).
            # Yalnızca "sonra bir yerde tekrar geçiyor" yetmez: aynı ad farklı sınıflarda da geçer.
            nxt = next((o for o in titles if o.page > t.page), None)
            again = nxt is not None and norm_label(nxt.text) == norm_label(t.text)
            if t.page == heading.page or again or t.size < median_size * 0.9 or _scaled_down_page(doc, body, titles, t.page):
                sample = t
    if sample is None and (titles[0].size < median_size * 0.9 or _scaled_down_page(doc, body, titles, titles[0].page)):
        sample = titles[0]
    if sample is None:
        return heading, None, []
    stop_size = heading.size if heading is not None else median_size
    pages = [sample.page]
    for p in range(sample.page + 1, doc.page_count + 1):
        spans = _content_spans(doc, p)
        big = any(x.size >= stop_size * 0.95 for x in spans)
        has_title = any(x.id in {t.id for t in titles} for x in spans)
        if big or has_title or not spans:
            break
        pages.append(p)
    return heading, sample, pages


def _heading_sizes(doc: PdfDoc, body: frozenset[int], title_ids: set[str], page: int) -> list[float]:
    return [
        s.size
        for s in _content_spans(doc, page)
        if s.color not in body and s.id not in title_ids and font_rank(s.font) >= 1 and any(ch.isalpha() for ch in s.text)
    ]


def _scaled_down_page(doc: PdfDoc, body: frozenset[int], titles: list[Span], page: int) -> bool:
    """Sayfadaki başlık benzeri (renkli, kalın) metinler diğer birim sayfalarındakilerden belirgin biçimde
    küçük mü? Yapı sayfası tema sayfasının küçültülmüş örneğidir (Kimya s.11: başlıklar 8 pt, tema
    sayfalarında 10 pt); birim başlığı küçültülmemiş olsa da böyle tanınır."""
    ids = {t.id for t in titles}
    here = _heading_sizes(doc, body, ids, page)
    others = [x for p in sorted({t.page for t in titles if t.page != page})[:6] for x in _heading_sizes(doc, body, ids, p)]
    if len(here) < 5 or len(others) < 5:
        return False
    med = lambda xs: sorted(xs)[len(xs) // 2]
    return med(here) < 0.85 * med(others)


def _adaptive_label_groups(spans: list[Span]) -> list[list[Span]]:
    """Başlık satırlarını, birimin kendi başlık satır aralığına göre birleştirir.

    Sabit eşik yetmez: Zazaca'da başlık içi aralık 2 pt, başlıklar arası 3,7 pt; Fen 6-8. sınıfta başlık
    içi 4,9 pt. Birimde aynı renk/kalınlıktaki alt alta başlık satırları arasındaki en küçük boşluk
    başlık içi aralıktır; bundan belirgin biçimde büyük boşluk yeni başlıktır."""
    lines: list[list[Span]] = []
    for r in group_rows(spans):
        by_color: dict[int, list[Span]] = {}
        for x in r:
            by_color.setdefault(x.color, []).append(x)
        lines.extend(by_color.values())

    def joinable(a: list[Span], b: list[Span]) -> float | None:
        p, c = a[-1], b[0]
        if c.page != p.page or c.color != p.color:
            return None
        if not (font_rank(c.font) == font_rank(p.font) or c.text.lstrip().startswith("(")):
            return None
        if min(max(x.x1 for x in a), max(x.x1 for x in b)) - max(min(x.x0 for x in a), min(x.x0 for x in b)) <= -2:
            return None
        lead = c.y0 - max(x.y1 for x in a)
        return lead if -0.3 * p.size <= lead <= 1.0 * p.size else None

    leads = [l for a, b in zip(lines, lines[1:]) if (l := joinable(a, b)) is not None]
    if not leads:
        return lines
    # En sık görülen aralık başlık içi aralıktır (en küçüğü değil: Zazaca "ÖĞRENME ÇIKTILARI" / "SÜREÇ
    # BİLEŞENLERİ" arası 0 pt, başlık içi aralıkların çoğu 2 pt)
    intra = max(Counter(round(l * 2) / 2 for l in leads).most_common(1)[0][0], 0.0)
    limit = intra * 1.4 + 0.5
    groups: list[list[Span]] = []
    for ln in lines:
        if groups and (l := joinable(groups[-1], ln)) is not None and l <= limit:
            groups[-1].extend(ln)
        else:
            groups.append(list(ln))
    return groups


def learn_labels_from_units(doc: PdfDoc, body: frozenset[int], title_colors: frozenset[int], titles: list[Span], data_start: int) -> tuple[list[int], list[LabelDef]]:
    """Yapı sayfası yoksa bölüm başlıkları tema sayfalarından öğrenilir: gövde/başlık renginde olmayan,
    kalın/orta kalın ve birimlerin en az yarısında tekrar eden başlık metinleri. Sıra, birimlerdeki
    ortalama sıradır."""
    unit_pages = sorted({t.page for t in titles if t.page >= data_start})
    if not unit_pages:
        return [], []

    def unit_of(page: int) -> int:
        return max(i for i, p in enumerate(unit_pages) if p <= page) if page >= unit_pages[0] else -1

    cand = [
        s
        for s in doc.spans
        if s.page >= data_start
        and s.id not in doc.furniture
        and s.text.strip()
        and s.color not in body
        and s.color not in title_colors
        and font_rank(s.font) >= 1
        and any(ch.isalpha() for ch in s.text)
    ]
    by_unit: dict[int, list[Span]] = defaultdict(list)
    for x in cand:
        by_unit[unit_of(x.page)].append(x)
    groups = [g for u, xs in sorted(by_unit.items()) if u >= 0 for g in _adaptive_label_groups(xs)]
    occ: dict[str, list[tuple[int, int, list[Span]]]] = defaultdict(list)  # norm -> (birim, birimdeki sıra, span'lar)
    per_unit_counter: Counter[int] = Counter()
    for grp in groups:
        n = norm_label(" ".join(x.text for x in grp))
        if len(n) < 3 or GENERIC_CODE_START_RE.match(grp[0].text):
            continue
        u = unit_of(grp[0].page)
        if u < 0:
            continue
        occ[n].append((u, per_unit_counter[u], grp))
        per_unit_counter[u] += 1
    n_units = len(unit_pages)
    keep = {n: o for n, o in occ.items() if len({u for u, _, _ in o}) >= max(2, n_units / 2)}
    order = sorted(keep, key=lambda n: sum(i for _, i, _ in keep[n]) / len(keep[n]))
    labels = []
    for n in order:
        grp = keep[n][0][2]
        f = make_field(grp)
        parts = [norm_label(p) for p in f.text.split("/") if norm_label(p)]
        labels.append(
            LabelDef(
                text=Counter(" ".join(x.text for x in g).replace("\n", " ").strip() for _, _, g in keep[n]).most_common(1)[0][0],
                norm=n,
                parts=parts if len(parts) > 1 else [],
                rank=font_rank(grp[0].font),
                color=Counter(g[0].color for _, _, g in keep[n]).most_common(1)[0][0],
                source_spans=f.source_spans,
            )
        )
    return sorted({l.color for l in labels}), labels


GENERIC_CODE_START_RE = re.compile(r"^\s*[^\W\d_]{1,6}[\s.]*\d")


def learn_lo_code_from_units(doc: PdfDoc, body: frozenset[int], data_start: int) -> tuple[str, list[str], Span]:
    """Yapı sayfasında örnek kod yoksa ÖÇ kodu deseni tema sayfalarından öğrenilir: gövde renginde,
    satır başında en sık geçen en az üç segmentli kod biçimi (ör. "MAT.1.1.1.")."""
    pat = re.compile(rf"^\s*([^\W\d_]+)[\s.]*(\d+(?:[\s.]+\d+)+(?:[\s.]+{UPPER_SEGMENT}(?=[.\s]|$))?)")
    shapes: Counter[tuple[str, tuple[str, ...]]] = Counter()
    example: dict[tuple[str, tuple[str, ...]], Span] = {}
    for s in doc.spans:
        if s.page < data_start or s.id in doc.furniture or s.color not in body:
            continue
        m = pat.match(s.text)
        if not m:
            continue
        types = tuple("n" if x.isdigit() else "a" for x in re.findall(r"\d+|[^\W\d_]+", m.group(2)))
        if len(types) >= 3:
            key = (m.group(1), types)
            shapes[key] += 1
            example.setdefault(key, s)
    if not shapes:
        raise SchemaError("Öğrenme çıktısı kodu deseni (ör. \"MAT.1.1.1.\") bulunamadı")
    key = shapes.most_common(1)[0][0]
    return key[0], list(key[1]), example[key]


def detect_schema(doc: PdfDoc) -> ProgramSchema:
    dominant = body_color(doc)
    # Gövde kümesi daha geniş tutulur: Fen s.16 açıklamaları #000000/#000C14, gövde #221F1F;
    # s.127'de bileşen içindeki tek kelime "Işığın" #000000. Hepsi siyaha yakın gövde metnidir.
    body = near_colors(doc, dominant, tol=BODY_COLOR_TOL)
    keyword, titles = find_unit_titles(doc, body)
    heading, sample, pages = locate_structure(doc, body, titles)
    title_color = sample.color if sample is not None else Counter(s.color for s in titles).most_common(1)[0][0]
    title_colors = near_colors(doc, title_color)
    after = [t for t in titles if t.color in title_colors and (not pages or t.page > pages[-1])]
    if not after:
        raise SchemaError("Tema/ünite başlığı bulunamadı")
    data_start = min(t.page for t in after)
    if sample is not None:
        # Boyut üst sınırı: yapı başlığı aynı sayfadaysa onun boyutu, değilse gerçek birim başlıklarının boyutu
        own_heading = heading if heading is not None and heading.page in pages else None
        cap = own_heading.size if own_heading is not None else sorted(t.size for t in after)[len(after) // 2]
        label_colors, labels = learn_labels(doc, own_heading, sample, pages, body, cap)
        labels = _labels_used_in_units(doc, labels, body | title_colors, data_start)
        try:
            prefix, seg_types, lo_span = learn_lo_code(doc, pages, body)
        except SchemaError:
            prefix, seg_types, lo_span = learn_lo_code_from_units(doc, body, data_start)
    else:
        label_colors, labels = learn_labels_from_units(doc, body, title_colors, after, data_start)
        prefix, seg_types, lo_span = learn_lo_code_from_units(doc, body, data_start)
    label_colors = confirm_label_colors(doc, labels, label_colors, body | title_colors, data_start)
    return ProgramSchema(
        structure_pages=pages,
        structure_heading=make_field([heading]) if heading is not None and pages else None,
        unit_keyword=keyword,
        unit_title_color=title_color,
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
        # Özet tabloları yapı sayfasından (yoksa ilk tema sayfasından) öncedir
        last_page = (schema.structure_pages[0] if schema.structure_pages else schema.data_start_page) - 1
        for pno in range(1, last_page + 1):
            spans = _content_spans(doc, pno)
            page_txt = " ".join(s.text for s in spans)
            if not _hint(page_txt, LO_COLUMN_HINTS):
                continue
            prev_bottom = 0.0
            for t in fz[pno - 1].find_tables().tables:
                title = _inner_title(t, spans, schema) or _table_title(t.bbox, spans, schema, prev_bottom)
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


def _inner_title(t, spans: list[Span], schema: ProgramSchema) -> TextField | None:
    """Tablonun ilk satırı tam genişlikte tek hücreyse ve sütun başlığı değilse tablonun başlığıdır
    (Matematik s.10: tablo içinde "1. SINIF MATEMATİK DERSİ")."""
    if not t.rows:
        return None
    cells = [c for c in t.rows[0].cells if c is not None]
    fields = [(c, f) for c in cells if (f := make_field(_spans_in(spans, c))) is not None]
    if len(fields) != 1:
        return None
    c, f = fields[0]
    tx0, _, tx1, _ = t.bbox
    if c[2] - c[0] < 0.8 * (tx1 - tx0):
        return None
    if _hint(f.text, LO_COLUMN_HINTS) or _hint(f.text, HOURS_COLUMN_HINTS) or _hint(f.text, ORDER_COLUMN_HINTS):
        return None
    if norm_label(f.text) == norm_label(schema.unit_keyword):
        return None
    return f


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
    in_title = set(title.source_spans) if title is not None else set()
    for r in t.rows:
        cells = []
        for c in r.cells:
            if c is None:
                continue
            f = make_field(_spans_in(spans, c))
            if f is not None and set(f.source_spans) <= in_title:
                continue  # tablo içindeki başlık satırı
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
