"""Gerçek tema/ünitelerin çok sayfalı olarak çıkarılması.

Bölüm sınırları metin kesme ile değil, layout ile belirlenir:
- etiket span'ları yapı sayfasından öğrenilen etiket stilleriyle (renk) tanınır,
- çok satırlı etiketler geometri + öğrenilen başlık sözlüğü ile birleştirilir,
- içerik span'ı, okuma sırasında kendisinden önce başlayan son etikete aittir,
- tema/ünite, bir sonraki gerçek tema/ünite başlığına veya tema dışı bir başlığa
  (ör. repertuvar listesi, ekler) kadar açık kalır. Tema dışı içerik alınmaz.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from models import (
    ApplicationBlock,
    Code,
    DeclaredCode,
    ExcludedRegion,
    Finding,
    LearningOutcome,
    ProcessComponent,
    ProgramSchema,
    Section,
    SectionKind,
    Severity,
    Span,
    TextField,
    Unit,
)
from pdf_extract import (
    GENERIC_CODE_RE,
    PdfDoc,
    font_rank,
    group_rows,
    lo_code_regex,
    loose_lo_code_regex,
    make_field,
    compare_key,
    context_in_title,
    dehyphen_view,
    make_field_from_rows,
    norm_label,
    parse_code,
    sub_field,
    tr_upper,
)
from schema_detect import _is_unit_title, compound_subset_of, label_lookup, label_prefix_variant, label_variant_of, parse_unit_title

SUB_ITEM_RE = re.compile(r"^\s*([a-zçğıöşü])\)\s*")
# Kod tanım girdisi. Standart yazım "E1.1. Merak"; standart dışı yazımlar da tanınır
# ("E.1.1. Merak", "E1.1 Merak", "E3.8.Soru") ve raporda CODE_FORMAT_ANOMALY olur.
# Adı yazılmamış girdi ("KB2.13. Yapılandırma, KB2.14, KB2.15. ...") de girdi sayılır; NEEDS_REVIEW olur.
DECL_ENTRY_RE = re.compile(r"(?:(?<=^)|(?<=[\s,;(]))([^\W\d_]{1,5}\.?\d+(?:\.\d+)*(?:\.(?=\s|[^\W\d_])|(?=\s)|(?=,)))")
# Tanım metninde kalmış olabilecek kod benzeri ifadeler (girdi başlangıcı olarak tanınmamışsa incelenir)
LOOSE_CODE_RE = re.compile(r"(?<![\w.])[^\W\d_]{1,5}\.?\d+(?:\.\d+)*")
STD_DECL_CODE_RE = re.compile(r"^[^\W\d_]{1,5}\d+(?:\.\d+)*\.$")


@dataclass
class _Label:
    spans: list[Span]
    norm: str
    known: bool
    variant_of: str | None = None  # ham başlık öğrenilmiş başlığın yazım varyantıysa ham norm

    @property
    def anchor(self) -> Span:
        return self.spans[0]


@dataclass
class _RawSection:
    label: _Label | None
    content: list[Span] = field(default_factory=list)


@dataclass
class _RawUnit:
    context: list[Span]
    title: list[Span]
    subtitle: list[Span] = field(default_factory=list)
    sections: list[_RawSection] = field(default_factory=list)


# ---------------------------------------------------------------- etiket birleştirme


def merge_labels(label_spans: list[Span], schema: ProgramSchema) -> list[_Label]:
    """Etiket satırlarını, öğrenilen başlık sözlüğüne göre birleştirir.

    Aynı sayfa/renk, dikey yakınlık ve yatay örtüşme şartıyla; birleşik metin
    sözlükteki bir başlığın öneki olduğu sürece birleştirme devam eder.
    """
    vocab = list(label_lookup(schema))
    rows = group_rows(label_spans)
    lines: list[list[Span]] = []
    for r in rows:
        by_color: dict[int, list[Span]] = {}
        for s in r:
            by_color.setdefault(s.color, []).append(s)
        lines.extend(by_color.values())

    out: list[_Label] = []
    cur: list[Span] | None = None
    for ln in lines:
        if cur is not None:
            prev = cur[-1]
            first = ln[0]
            gap = first.yc - prev.yc
            # Satırlar arası boşluk yazı boyuna göre ölçülür (Fen 6-8. sınıf başlıklarında satır
            # aralığı daha geniştir: "ALAN" y1=233.3, "BECERİLERİ" y0=238.2).
            leading = first.y0 - prev.y1
            x_ok = min(max(s.x1 for s in cur), max(s.x1 for s in ln)) - max(min(s.x0 for s in cur), min(s.x0 for s in ln)) > -2
            merged_text = " ".join(s.text for s in cur + ln)
            merged_norm = norm_label(merged_text)
            if (
                first.page == prev.page
                and first.color == prev.color
                and 0 < gap
                and (gap <= 1.6 * prev.size or leading <= 0.6 * prev.size)
                and x_ok
                and (
                    any(v.startswith(merged_norm) for v in vocab)
                    or label_prefix_variant(merged_norm, vocab)
                    or compound_subset_of(merged_text, schema.labels, partial=True, allow_unknown=True)
                    # Yapı sayfasında olmayan çok satırlı başlık (Fen s.88 "ÖĞRENCİ" + "PROFİLİ"): hiçbir
                    # satırı bilinen bir başlığa uymuyorsa yalnızca sıkı layout ile birleştirilir;
                    # sonuç yine bilinmeyen başlık (NEEDS_REVIEW) olarak raporlanır.
                    or (
                        leading <= 0.6 * prev.size
                        and font_rank(first.font) == font_rank(prev.font)
                        and not _known_start(" ".join(s.text for s in cur), vocab)
                        and not _known_start(" ".join(s.text for s in ln), vocab)
                    )
                )
            ):
                cur.extend(ln)
                continue
            out.append(_finish_label(cur, vocab, schema))
        cur = list(ln)
    if cur is not None:
        out.append(_finish_label(cur, vocab, schema))
    return out


def _continues(prev: Span, s: Span, same_row_ok: bool = False) -> bool:
    """s, prev'in hemen altındaki (veya aynı satırdaki) devam parçası mı? (layout ile)"""
    if s.page != prev.page:
        return False
    if same_row_ok and abs(s.yc - prev.yc) < 3:
        return True
    return 0 <= s.y0 - prev.y1 <= 0.8 * prev.size and min(s.x1, prev.x1) - max(s.x0, prev.x0) > 0


def _pull_aligned_rows(prev: _RawSection, lab: _Label) -> list[Span]:
    """İçerik bloğu başlığa göre dikey ortalanmışsa ilk satırları başlıktan biraz yukarıda başlar
    (ör. Arnavutça s.143: içerik y=291, "ALAN BECERİLERİ" y=297). Önceki bölümün sonundaki, yeni
    başlıkla aynı hizada duran ve önceki içerikten paragraf boşluğuyla ayrılan satırlar yeni başlığa
    aittir. Önceki bölümde bu satırlardan önce içerik yoksa hiçbir şey taşınmaz."""
    a = lab.anchor
    same_page = [s for s in prev.content if s.page == a.page]
    if not same_page:
        return []
    rows = group_rows(same_page)
    k = len(rows)
    # Satırın dikey merkezi başlığın üst kenarında veya altında olmalı (başlıkla aynı hizada). Başlığa
    # göre ortalanan blok başlığın birkaç pt üstünden başlayabilir (Matematik s.57: "E1.1. Merak, …"
    # yc=312, "EĞİLİMLER" y0=313); bu toleransla alınan satır ancak önceki içerikten paragraf
    # boşluğuyla ayrılıyorsa taşınır (Arnavutça s.218: paragrafın son satırı yc=264, "FARKLILAŞTIRMA"
    # y0=265, önceki satırla arası normal satır aralığı -> taşınmaz).
    tol = 0.5 * a.size
    while k > 0 and rows[k - 1][0].yc >= a.y0 - tol and min(s.x0 for s in rows[k - 1]) >= a.x1 - 2:
        k -= 1
    if k == len(rows):
        return []
    first = rows[k]
    if k > 0:
        if first[0].yc < a.y0 and min(s.y0 for s in first) - max(s.y1 for s in rows[k - 1]) <= 0.5 * a.size:
            return []
        before_yc = rows[k - 1][0].yc  # önceki bölümün son satırı
    elif prev.label is not None and prev.label.anchor.page == a.page:
        before_yc = prev.label.anchor.yc  # önceki bölümün başka satırı yok: önceki başlık
    else:
        return []
    # Satır, önceki içeriğe/başlığa değil yeni başlığa daha yakınsa yeni başlığa aittir.
    if abs(first[0].yc - a.yc) >= abs(first[0].yc - before_yc):
        return []
    moved = [s for r in rows[k:] for s in r]
    ids = {s.id for s in moved}
    prev.content = [s for s in prev.content if s.id not in ids]
    return moved


def _known_start(text: str, vocab: list[str]) -> bool:
    n = norm_label(text)
    return bool(n) and (any(v.startswith(n) for v in vocab) or label_prefix_variant(n, vocab) or label_variant_of(n, vocab) is not None)


def _finish_label(spans: list[Span], vocab: list[str], schema: ProgramSchema) -> _Label:
    text = " ".join(s.text for s in spans)
    n = norm_label(text)
    if n in vocab:
        return _Label(spans=spans, norm=n, known=True)
    c = compound_subset_of(text, schema.labels)
    if c is not None:
        # bileşik başlığın parçalarından birkaçı ("Genellemeler/Anahtar Kavramlar"): o başlığın yerindedir
        return _Label(spans=spans, norm=c, known=True)
    v = label_variant_of(n, vocab)
    if v is not None:
        # yazım varyantı: öğrenilmiş başlığa eşlenir, ham metin korunur, raporda NEEDS_REVIEW
        return _Label(spans=spans, norm=v, known=True, variant_of=n)
    return _Label(spans=spans, norm=n, known=False)


# ---------------------------------------------------------------- ana akış


def extract_units(
    doc: PdfDoc, schema: ProgramSchema, context_hints: list[str] = ()
) -> tuple[list[Unit], list[ExcludedRegion], list[Finding]]:
    """context_hints: özet tablosu başlıkları (ör. "9. SINIF BİYOLOJİ DERSİ (2 SAAT)")."""
    findings: list[Finding] = []
    body_colors = set(schema.body_colors) or {schema.body_color}
    # ör. Zazaca s.69: "6. SINIF (" #FFFFFF, "A1.1" #FEFEFE
    title_colors = set(schema.unit_title_colors) or {schema.unit_title_color}
    spans = [
        s
        for s in doc.spans
        if s.page >= schema.data_start_page and s.id not in doc.furniture and s.text.strip()
    ]
    label_spans = [s for s in spans if s.color in schema.label_colors]
    labels = merge_labels(label_spans, schema)
    anchor_of: dict[str, _Label] = {l.anchor.id: l for l in labels}
    label_member = {s.id for l in labels for s in l.spans}

    raw_units: list[_RawUnit] = []
    excluded: list[tuple[list[Span], list[Span]]] = []  # (başlık, içerik)
    margin_notes: list[Span] = []
    # Sağa yaslı başlık sütununun sayfadaki sağ kenarı
    label_right: dict[int, float] = {}
    for s in label_spans:
        label_right[s.page] = max(label_right.get(s.page, s.x1), s.x1)
    unit: _RawUnit | None = None
    pending_context: list[Span] = []
    outside_heading: list[Span] = []
    outside: list[Span] = []  # tema dışı bölge içeriği

    def close_unit():
        nonlocal unit
        if unit is not None:
            raw_units.append(unit)
            unit = None

    def flush_outside():
        nonlocal outside, outside_heading
        if outside or outside_heading:
            excluded.append((outside_heading, outside))
        outside, outside_heading = [], []

    context_used = False

    def drop_context():
        nonlocal pending_context, context_used
        if pending_context and not context_used:
            outside.extend(pending_context)  # hiçbir birime bağlanmayan bağlam başlığı
        pending_context, context_used = [], False

    body_size = Counter(round(s.size) for s in spans if s.color in body_colors).most_common(1)[0][0]

    def heading_like(s: Span) -> bool:
        # Renkli tek bir noktalama işareti vb. başlık sayılmaz; harf/rakam ve başlık biçimi gerekir.
        return any(ch.isalnum() for ch in s.text) and (font_rank(s.font) >= 2 or s.size >= body_size * 1.15)

    for row in group_rows(spans):
        row_has_label = any(x.id in label_member for x in row)
        for s in row:
            if s.color in title_colors:
                if unit is not None and not unit.sections:
                    if unit.title[-1].page == s.page and abs(unit.title[-1].yc - s.yc) < 3 and not unit.subtitle:
                        # aynı satırda parçalara bölünmüş başlık (Din Hizmetleri s.14: "1. ÜNİTE: " + "DİN HİZMETLERİ …")
                        unit.title.append(s)
                        continue
                    if _continues(unit.title[-1], s) and abs(s.size - unit.title[-1].size) < 0.5:
                        unit.title.append(s)  # birden fazla satıra bölünmüş birim başlığı
                    else:
                        unit.subtitle.append(s)  # başlığın altındaki ek satır (ör. "Alt Temalar: ...")
                    continue
                close_unit()
                # Başlık aynı satırda birden çok parçaya bölünmüş olabilir: satırdaki bu ve sağındaki başlık renkli
                # parçaların birleşimi de denenir.
                row_title = " ".join(x.text.strip() for x in row if x.color in title_colors and x.x0 >= s.x0)
                if _is_unit_title(s.text, schema.unit_keyword) or _is_unit_title(row_title, schema.unit_keyword):
                    # Bağlam başlığı başka renkte olabilir (ör. Biyoloji "10. SINIF"): birim başlığının
                    # hemen üstünde, arada içerik olmadan duran ve bir özet tablosu başlığının başıyla
                    # eşleşen tema dışı başlık bağlam sayılır ("10. SINIF" ~ "10. SINIF BİYOLOJİ DERSİ").
                    heading_text = " ".join(h.text for h in outside_heading)
                    if (
                        (not pending_context or context_used)
                        and outside_heading
                        and not outside
                        and all(h.page == s.page and h.y1 <= s.y0 + 1 for h in outside_heading)
                        and any(context_in_title(heading_text, h) for h in context_hints)
                    ):
                        drop_context()
                        pending_context, outside_heading = outside_heading, []
                    flush_outside()
                    # Bağlam (ör. "5. SINIF") yalnızca ilk birimin önünde yazılı olabilir;
                    # yeni bir bağlam başlığı gelene kadar sonraki birimler için de geçerlidir.
                    unit = _RawUnit(context=list(pending_context), title=[s])
                    context_used = context_used or bool(pending_context)
                else:
                    # Birim üstü yapısal başlık (ör. "1. SINIF").
                    if pending_context and not context_used and _continues(pending_context[-1], s, same_row_ok=True):
                        pending_context.append(s)
                    else:
                        drop_context()
                        pending_context = [s]
                continue
            if s.id in label_member:
                if s.id not in anchor_of:
                    continue  # çok satırlı etiketin devam satırı
                lab = anchor_of[s.id]
                if unit is None:
                    findings.append(
                        Finding(
                            severity=Severity.NEEDS_REVIEW,
                            check="ORPHAN_LABEL",
                            message="Tema/ünite dışında bölüm başlığı bulundu",
                            details={"spans": [x.id for x in lab.spans], "text": " ".join(x.text for x in lab.spans)},
                        )
                    )
                    continue
                moved = _pull_aligned_rows(unit.sections[-1], lab) if unit.sections else []
                unit.sections.append(_RawSection(label=lab, content=moved))
                continue
            if s.color in body_colors or not heading_like(s):
                # Gövde metni veya içerik içinde renklendirilmiş parça (ör. kırmızı bir nokta)
                if unit is not None and not row_has_label and s.page in label_right and s.x0 < label_right[s.page] - 20:
                    # Başlık sütununun sağ kenarının belirgin biçimde solunda (başlık sütununda) başlayan
                    # ve aynı satırda başlık olmayan gövde satırı: sayfa notu (ör. Arnavutça
                    # "5. sınıf öğretim programı bütüncül yaklaşıma göre yapılandırılmıştır.").
                    # Hiçbir bölüme ait değildir; tema dışı bırakılır.
                    margin_notes.append(s)
                    continue
                if unit is not None:
                    if not unit.sections:
                        unit.sections.append(_RawSection(label=None))
                    unit.sections[-1].content.append(s)
                else:
                    outside.append(s)
                continue
            # Tema dışı başlık stili (gövde, etiket, birim başlığı renginde olmayan) -> tema kapanır
            close_unit()
            if outside_heading and not outside and outside_heading[-1].page == s.page and abs(outside_heading[-1].yc - s.yc) < 3:
                outside_heading.append(s)  # aynı satırdaki başlık parçası (ör. "3." + "EKLER")
            else:
                flush_outside()
                outside_heading = [s]
            drop_context()
    close_unit()
    drop_context()
    flush_outside()
    for page in sorted({s.page for s in margin_notes}):
        excluded.append(([], [s for s in margin_notes if s.page == page]))

    units = [_build_unit(i + 1, ru, schema, findings) for i, ru in enumerate(raw_units)]
    _assign_groups(units, findings)
    regions = [
        ExcludedRegion(
            heading=make_field(h) if h else None,
            pages=sorted({x.page for x in h + c}),
            span_count=len(h) + len(c),
            source_spans=[x.id for x in h + c],
        )
        for h, c in excluded
    ]
    for l in labels:
        if l.variant_of is not None:
            findings.append(
                Finding(
                    severity=Severity.NEEDS_REVIEW,
                    check="LABEL_TEXT_VARIANT",
                    unit_id=next((u.id for u in units if any(s.label and l.anchor.id in s.label.source_spans for s in u.sections)), None),
                    message="Bölüm başlığı yapı sayfasındakinden farklı yazılmış; en yakın tek başlığa eşlendi (kaynak PDF)",
                    details={"text": " ".join(x.text for x in l.spans), "matched_label_norm": l.norm, "spans": [x.id for x in l.spans]},
                )
            )
        if not l.known:
            findings.append(
                Finding(
                    severity=Severity.NEEDS_REVIEW,
                    check="UNKNOWN_LABEL",
                    unit_id=next((u.id for u in units if any(s.label and l.anchor.id in s.label.source_spans for s in u.sections)), None),
                    message="Yapı sayfasında olmayan başlık stili metin",
                    details={"spans": [x.id for x in l.spans], "text": " ".join(x.text for x in l.spans)},
                )
            )
    _classify_sections(units, schema, findings)
    by_id = {s.id: s for s in doc.spans}
    for u in units:
        _parse_unit_content(u, schema, findings, by_id)
    known_prefixes = {d.code.prefix for u in units for decls in u.declarations.values() for d in decls}
    for u in units:
        for b in u.applications:
            if b.body is not None:
                b.used_codes = extract_used_codes(b.body.text, known_prefixes, schema.lo_prefix)
                b.malformed_codes = extract_malformed_codes(b.body.text, known_prefixes)
    _canonicalize_codes(units)
    return units, regions, findings


def _all_codes(units: list[Unit]):
    for u in units:
        for lo in u.learning_outcomes:
            yield lo.code
        for b in u.applications:
            if b.code is not None:
                yield b.code
            yield from b.used_codes
        for ds in u.declarations.values():
            for d in ds:
                yield d.code


def _canonicalize_codes(units: list[Unit]) -> None:
    """Normalize değer önek bazında tek biçime getirilir (ör. "E.1.1" ve "E1.1" -> "E1.1").

    Önek ile ilk sayı arasındaki ayırıcı, o önek için PDF'deki çoğunluk yazımından öğrenilir.
    Raw değer değişmez; kimlik (önek + sayılar) zaten yazımdan bağımsızdır.
    """
    votes: dict[str, Counter] = {}
    codes = list(_all_codes(units))
    for c in codes:
        sep = bool(re.match(rf"\s*{re.escape(c.prefix)}[\s.]", c.raw))
        votes.setdefault(c.prefix, Counter())[sep] += 1
    for c in codes:
        sep = votes[c.prefix].most_common(1)[0][0]
        c.normalized = c.prefix + ("." if sep else "") + ".".join(c.segments)
    # parantez içi alt tanımların üst kod referansları da aynı biçime çekilir
    by_key = {c.key: c.normalized for c in codes}
    for u in units:
        for ds in u.declarations.values():
            for d in ds:
                if d.parent is not None:
                    parent = parse_code(d.parent)
                    d.parent = by_key.get(parent.key, d.parent)


# ---------------------------------------------------------------- birim kurulumu


def _build_unit(idx: int, ru: _RawUnit, schema: ProgramSchema, findings: list[Finding]) -> Unit:
    title = make_field(ru.title)
    parsed = parse_unit_title(title.text, schema.unit_keyword)
    order, name = (parsed[0], parsed[1]) if parsed else (None, None)
    if parsed and not parsed[2]:
        findings.append(
            Finding(
                severity=Severity.NEEDS_REVIEW,
                check="UNIT_TITLE_FORMAT",
                unit_id=f"U{idx:02d}",
                message="Birim başlığı yapı sayfasındaki biçimden farklı yazılmış (kaynak PDF)",
                details={"title": title.text, "spans": title.source_spans},
            )
        )
    sections: list[Section] = []
    for rs in ru.sections:
        rows = group_rows(rs.content) if rs.content else []
        content_rows = [make_field_from_rows([r]) for r in rows]
        if rs.label is None:
            sections.append(
                Section(
                    label=None,
                    label_norm=None,
                    path="",
                    kind=SectionKind.UNIT_DESCRIPTION,
                    content=make_field(rs.content),
                    content_rows=content_rows,
                )
            )
            continue
        lf = make_field(rs.label.spans)
        sections.append(
            Section(
                label=lf,
                label_norm=rs.label.norm,
                path=lf.text.replace("\n", " "),
                rank=font_rank(rs.label.anchor.font),
                content=make_field(rs.content),
                content_rows=content_rows,
            )
        )
    all_spans = ru.title + ru.subtitle + [s for rs in ru.sections for s in (rs.content + (rs.label.spans if rs.label else []))]
    return Unit(
        id=f"U{idx:02d}",
        context=make_field(ru.context) if ru.context else None,
        title=title,
        subtitle=make_field(ru.subtitle) if ru.subtitle else None,
        order=order,
        name=name,
        pages=sorted({s.page for s in all_spans}),
        sections=sections,
    )


def _group_candidate(sections: list[Section], i: int) -> bool:
    sec = sections[i]
    nxt = sections[i + 1] if i + 1 < len(sections) else None
    return sec.content is None and nxt is not None and nxt.label is not None and nxt.rank < sec.rank


def _assign_groups(units: list[Unit], findings: list[Finding]) -> None:
    """Üst başlık (grup) ve alt başlık ilişkisinin tespiti.

    Birim içinde: içeriği olmayan ve ardından daha düşük dereceli (font) başlık gelen etiket
    grup adayıdır; alt başlıklar eşit/üst dereceli bir başlığa kadar gruba aittir.
    Tek bir birimdeki font farkı yapıyı bozmasın diye karar temaların çoğunluğundan verilir
    (ör. Adigece s.47: FARKLILAŞTIRMA diğer temalarda Bold, burada Medium). Çoğunluktan sapan
    birim WARNING (GROUP_STYLE_VARIANT) alır; üst başlığın altında içerik varsa NEEDS_REVIEW.
    Grup başlığı bir birimde PDF'de yoksa alt başlıklara grup yolu eklenmez (başlık uydurulmaz).
    """
    group_votes: dict[str, Counter] = {}
    parent_votes: dict[str, Counter] = {}
    local: dict[str, dict[int, str | None]] = {}  # birim -> bölüm indeksi -> birim içi üst başlık
    for u in units:
        local[u.id] = {}
        group: Section | None = None
        for i, sec in enumerate(u.sections):
            if sec.label_norm is None:
                continue
            is_cand = _group_candidate(u.sections, i)
            group_votes.setdefault(sec.label_norm, Counter())[is_cand] += 1
            if group is not None and sec.rank >= group.rank:
                group = None
            if is_cand:
                group = sec
                continue
            parent = group.label_norm if group is not None else None
            local[u.id][i] = parent
            parent_votes.setdefault(sec.label_norm, Counter())[parent] += 1
    groups = {n for n, c in group_votes.items() if c[True] > c[False]}
    major_parent = {n: c.most_common(1)[0][0] for n, c in parent_votes.items()}
    for u in units:
        group: Section | None = None
        variant: list[str] = []
        for i, sec in enumerate(u.sections):
            if sec.label_norm is None:
                continue
            if sec.label_norm in groups:
                if sec.content is not None:
                    findings.append(
                        Finding(
                            severity=Severity.NEEDS_REVIEW,
                            check="GROUP_HAS_CONTENT",
                            unit_id=u.id,
                            message="Diğer temalarda üst başlık olan başlığın altında içerik var",
                            details={"label": sec.path, "spans": sec.content.source_spans[:10]},
                        )
                    )
                    group = None
                    continue
                if not _group_candidate(u.sections, i):
                    variant.append(sec.path)
                sec.kind = SectionKind.GROUP
                group = sec
                continue
            want = major_parent.get(sec.label_norm)
            if want is not None and group is not None and group.label_norm == want:
                sec.group_label = group.label
                sec.path = f"{group.path} > {sec.path}"
            else:
                if want is None:
                    group = None
            if local[u.id].get(i) != (want if (group is not None and group.label_norm == want) else None) and local[u.id].get(i) is not None:
                variant.append(sec.path)
        if variant:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    check="GROUP_STYLE_VARIANT",
                    unit_id=u.id,
                    message="Başlık hiyerarşisi (font) diğer temalardan farklı; çoğunluk yapısı kullanıldı",
                    details={"labels": variant},
                )
            )


# ---------------------------------------------------------------- bölüm türleri


def _classify_sections(units: list[Unit], schema: ProgramSchema, findings: list[Finding]) -> None:
    lo_re = lo_code_regex(schema.lo_prefix, schema.lo_segment_types)
    for u in units:
        lo_idx = None
        for i, sec in enumerate(u.sections):
            if sec.kind in (SectionKind.GROUP, SectionKind.UNIT_DESCRIPTION) or not sec.content_rows:
                continue
            first = sec.content_rows[0].text
            m = lo_re.match(first)
            if lo_idx is None and m and first[m.end():].strip():
                sec.kind = SectionKind.LEARNING_OUTCOMES
                lo_idx = i
                continue
            if lo_idx is not None:
                code_only = [r for r in sec.content_rows if (mm := lo_re.match(r.text)) and not r.text[mm.end():].strip()]
                if code_only:
                    sec.kind = SectionKind.APPLICATIONS
                continue
            if _declaration_entries(sec.content.text):
                sec.kind = SectionKind.DECLARATION
        if lo_idx is None:
            findings.append(
                Finding(
                    severity=Severity.FAIL,
                    check="LO_SECTION_NOT_FOUND",
                    unit_id=u.id,
                    message="Öğrenme çıktıları bölümü bulunamadı",
                )
            )
    _split_unlabeled_applications(units, lo_re, findings)


def _code_only_rows(sec: Section, lo_re) -> list[int]:
    return [i for i, r in enumerate(sec.content_rows) if (m := lo_re.match(r.text)) and not r.text[m.end():].strip()]


def _split_unlabeled_applications(units: list[Unit], lo_re, findings: list[Finding]) -> None:
    """Uygulamalar başlığı PDF'de eksikse bir önceki bölüm uygulama kod bloklarını içine alır.

    Uygulamalar başlığı, programdaki temaların çoğunluğunda kod bloklarıyla başlayan bölümün
    başlığı olarak öğrenilir. Başka başlıklı bir bölümde kod blokları varsa bölüm ilk kod
    satırından ikiye ayrılır: kod blokları başlıksız bir uygulamalar bölümü olur (başlık
    uydurulmaz) ve birim NEEDS_REVIEW alır.
    """
    votes = Counter(
        s.label_norm
        for u in units
        for s in u.sections
        if s.kind == SectionKind.APPLICATIONS and _code_only_rows(s, lo_re)[:1] == [0]
    )
    if not votes:
        return
    app_norm = votes.most_common(1)[0][0]
    for u in units:
        for i, sec in enumerate(list(u.sections)):
            if sec.kind != SectionKind.APPLICATIONS or sec.label_norm == app_norm:
                continue
            k = _code_only_rows(sec, lo_re)[0]
            head, tail = sec.content_rows[:k], sec.content_rows[k:]
            sec.content_rows = head
            sec.content = _field_slice(head, 0, len(head))
            sec.kind = SectionKind.OTHER
            new = Section(
                label=None,
                label_norm=None,
                path="",
                kind=SectionKind.APPLICATIONS,
                content=_field_slice(tail, 0, len(tail)),
                content_rows=tail,
            )
            u.sections.insert(i + 1, new)
            findings.append(
                Finding(
                    severity=Severity.NEEDS_REVIEW,
                    check="APPLICATIONS_LABEL_MISSING",
                    unit_id=u.id,
                    message="Öğrenme-öğretme uygulamaları başlığı PDF'de yok; kod blokları önceki bölümden ayrıldı",
                    details={"previous_section": sec.path, "first_code_row": tail[0].text, "spans": tail[0].source_spans},
                )
            )


def _declaration_entries(text: str) -> list[tuple[int, int, str, int | None, bool]]:
    """Kod tanım girdileri: (başlangıç, bitiş, raw_kod, üst_girdi_indeksi, standart_yazım);
    indeksler ham metne göredir.

    Metin tamamen girdilerden oluşmalıdır. Parantez içindeki alt tanımlar
    ("BTYAB2. Bilgi İşlemsel Düşünme (BTYAB2.1. Algoritmik Düşünme, ...)") ayrı girdidir ve
    üst girdiye bağlanır; üst girdinin metni parantez içini de kapsar. Satır sonunda tireyle
    bölünmüş kodlar ("BT-\nYAB3.3.") tanınır; raw kod ham metindeki haliyle kalır.
    """
    view, idx = dehyphen_view(text)
    ms = list(DECL_ENTRY_RE.finditer(view))
    if not ms or ms[0].start() != 0:
        return []
    depth_at = []
    depth = 0
    for ch in view:
        depth_at.append(depth)
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
    out: list[tuple[int, int, str, int | None, bool]] = []
    stack: list[tuple[int, int]] = []  # (derinlik, girdi indeksi)
    for i, m in enumerate(ms):
        d = depth_at[m.start()]
        end_v = len(view)
        for n in ms[i + 1 :]:
            if depth_at[n.start()] <= d:
                end_v = n.start()
                break
        if d > 0:
            # parantez grubunun kapanışı
            close = next((k for k in range(m.start(), end_v) if view[k] == ")" and depth_at[k] == d), None)
            if close is not None:
                end_v = close
        while stack and stack[-1][0] >= d:
            stack.pop()
        parent = stack[-1][1] if stack else None
        stack.append((d, i))
        st = idx[m.start()]
        en = idx[end_v - 1] + 1 if end_v > m.start() else st
        code_raw = text[idx[m.start(1)] : idx[m.end(1) - 1] + 1]
        standard = bool(STD_DECL_CODE_RE.match(m.group(1))) and view[m.end(1) : m.end(1) + 1].isspace()
        out.append((st, en, code_raw, parent, standard))
    return out


# ---------------------------------------------------------------- içerik ayrıştırma


def _field_slice(sec_rows: list[TextField], start: int, end: int) -> TextField | None:
    """Satır listesinden [start, end) satır aralığının alanı."""
    rows = sec_rows[start:end]
    if not rows:
        return None
    text = "\n".join(r.text for r in rows)
    return TextField(
        text=text,
        pages=sorted({p for r in rows for p in r.pages}),
        source_spans=[s for r in rows for s in r.source_spans],
        compare_key=compare_key(text),
    )


def _parse_unit_content(u: Unit, schema: ProgramSchema, findings: list[Finding], by_id: dict[str, Span]) -> None:
    lo_re = lo_code_regex(schema.lo_prefix, schema.lo_segment_types)
    loose_re = loose_lo_code_regex(schema.lo_prefix, schema.lo_segments)
    for sec in u.sections:
        if sec.kind == SectionKind.LEARNING_OUTCOMES:
            u.learning_outcomes = _parse_los(
                u, sec, lo_re, findings, by_id, loose_lo_code_regex(schema.lo_prefix, schema.lo_segments, schema.lo_segments)
            )
        elif sec.kind == SectionKind.APPLICATIONS:
            u.applications.extend(_parse_applications(u, sec, lo_re, loose_re, findings, by_id))
        elif sec.kind == SectionKind.DECLARATION:
            u.declarations[sec.path] = _parse_declarations(sec, by_id)
            _check_declaration_residue(u, sec, findings)


def _lo_header(text: str, lo_re, loose_full):
    """Öğrenme çıktısı başlık satırı: standart kod veya tüm segmentleri olan ama tipi uymayan kod
    (ör. Zazaca s.26 "ZAZ.5.1.0." — O yerine sıfır). İkincisi önceki çıktıya sessizce karışmasın
    diye ayrı çıktı olarak alınır; kimlik uyuşmazlığı LO_CODE_IDENTITY olarak raporlanır."""
    return lo_re.match(text) or loose_full.match(text)


def _parse_los(u: Unit, sec: Section, lo_re, findings, by_id, loose_full=None) -> list[LearningOutcome]:
    loose_full = loose_full or lo_re
    rows = sec.content_rows
    los: list[LearningOutcome] = []
    kinds = []
    for r in rows:
        if _lo_header(r.text, lo_re, loose_full):
            kinds.append("lo")
        elif SUB_ITEM_RE.match(r.text):
            kinds.append("sub")
        else:
            kinds.append("cont")

    def row_font(r: TextField) -> str:
        c: Counter[str] = Counter()
        for i in r.source_spans:
            c[by_id[i].font] += len(by_id[i].text.strip())
        return c.most_common(1)[0][0]

    # İşaretsiz süreç bileşeni (ör. Arnavutça DBS/SÖS/SES çıktılarında tek bileşen, "a)" yok):
    # başlık satırlarından font farkıyla ayrılır. Bileşen fontu, aynı bölümdeki işaretli
    # bileşenlerden öğrenilir; öğrenilemiyorsa ayırma yapılmaz (tahmin yok).
    # italiklik farkı yok sayılır (ör. Abazaca s.178: bileşen "Light", diğerleri "LightItalic")
    family = lambda f: f.replace("Italic", "").replace("Oblique", "")
    comp_fonts = {family(row_font(r)) for r, k in zip(rows, kinds) if k == "sub"}
    for i in range(len(rows)):
        if kinds[i] != "lo":
            continue
        title_font = row_font(rows[i])
        j = i + 1
        while j < len(rows) and kinds[j] == "cont":
            f = row_font(rows[j])
            if family(f) in comp_fonts and f != title_font:
                kinds[j] = "usub"
                j += 1
                while j < len(rows) and kinds[j] == "cont" and row_font(rows[j]) == f:
                    j += 1
                break
            j += 1
    if kinds and kinds[0] != "lo":
        findings.append(
            Finding(
                severity=Severity.NEEDS_REVIEW,
                check="UNPARSED_TEXT",
                unit_id=u.id,
                message="Öğrenme çıktıları bölümünde koda bağlanamayan metin",
                details={"text": rows[0].text, "spans": rows[0].source_spans},
            )
        )
    i = 0
    while i < len(rows):
        if kinds[i] != "lo":
            i += 1
            continue
        m = _lo_header(rows[i].text, lo_re, loose_full)
        j = i + 1
        while j < len(rows) and kinds[j] == "cont":
            j += 1
        block = _field_slice(rows, i, j)
        title = sub_field(block, m.end(), len(block.text), by_id)
        code_f = sub_field(block, m.start(1), m.end(1), by_id)
        comps: list[ProcessComponent] = []
        k = j
        while k < len(rows) and kinds[k] in ("sub", "usub"):
            e = k + 1
            while e < len(rows) and kinds[e] == "cont":
                e += 1
            f = _field_slice(rows, k, e)
            if kinds[k] == "usub":
                comps.append(ProcessComponent(marker="", letter="", text=f, full=f))
            else:
                mm = SUB_ITEM_RE.match(f.text)
                comps.append(
                    ProcessComponent(
                        marker=f.text[: mm.end()].strip(),
                        letter=mm.group(1),
                        text=sub_field(f, mm.end(), len(f.text), by_id),
                        full=f,
                    )
                )
            k = e
        if title is None:
            findings.append(
                Finding(severity=Severity.NEEDS_REVIEW, check="LO_TITLE_EMPTY", unit_id=u.id, message="Öğrenme çıktısı başlığı boş", details={"code_raw": code_f.text})
            )
            title = code_f
        los.append(
            LearningOutcome(
                code=parse_code(code_f.text),
                title=title,
                components=comps,
                header=sub_field(block, m.start(1), len(block.text), by_id),
            )
        )
        i = k
    return los


def _header_match(text: str, lo_re, loose_re):
    """Uygulama bloğu başlığı: standart kod veya (yalnızca koddan oluşan satırda) gevşek kod.

    Gevşek eşleşme, "ARN.6.4.0." gibi hatalı yazılmış bir başlığın önceki bloğun metnine
    sessizce karışmasını önler; kimlik uyuşmazlığı ayrıca raporlanır."""
    m = lo_re.match(text)
    if m:
        return m
    m = loose_re.match(text)
    if m and not text[m.end():].strip():
        return m
    return None


def _parse_applications(u: Unit, sec: Section, lo_re, loose_re, findings, by_id) -> list[ApplicationBlock]:
    rows = sec.content_rows
    starts = [i for i, r in enumerate(rows) if _header_match(r.text, lo_re, loose_re)]
    blocks: list[ApplicationBlock] = []
    if not starts or starts[0] != 0:
        end = starts[0] if starts else len(rows)
        body = _field_slice(rows, 0, end)
        blocks.append(ApplicationBlock(code=None, header=None, body=body, used_codes=[]))
        findings.append(
            Finding(
                severity=Severity.NEEDS_REVIEW,
                check="UNATTACHED_APPLICATION_TEXT",
                unit_id=u.id,
                message="Öğrenme-öğretme uygulamalarında bir öğrenme çıktısı koduna bağlanamayan metin",
                details={"text": body.text[:200], "spans": body.source_spans[:10]},
            )
        )
    for n, st in enumerate(starts):
        en = starts[n + 1] if n + 1 < len(starts) else len(rows)
        whole = _field_slice(rows, st, en)
        m = _header_match(rows[st].text, lo_re, loose_re)
        header = sub_field(whole, m.start(1), m.end(1), by_id)
        body = sub_field(whole, m.end(), len(whole.text), by_id)
        blocks.append(ApplicationBlock(code=parse_code(header.text), header=header, body=body))
    return blocks


def _parse_declarations(sec: Section, by_id) -> list[DeclaredCode]:
    text = sec.content.text
    out: list[DeclaredCode] = []
    for st, en, raw, parent, standard in _declaration_entries(text):
        seg = text[st:en]
        cut = len(seg.rstrip().rstrip(",;").rstrip())
        out.append(
            DeclaredCode(
                code=parse_code(raw),
                entry=sub_field(sec.content, st, st + cut, by_id),
                parent=out[parent].code.normalized if parent is not None else None,
                standard_format=standard,
            )
        )
    return out


def _check_declaration_residue(u: Unit, sec: Section, findings: list[Finding]) -> None:
    """Girdi başlangıcı olarak tanınmamış kod benzeri ifade, başka bir girdinin metnine
    sessizce karışmış bir tanım olabilir: NEEDS_REVIEW."""
    view, idx = dehyphen_view(sec.content.text)
    starts = {m.start() for m in DECL_ENTRY_RE.finditer(view)}
    for m in LOOSE_CODE_RE.finditer(view):
        if m.start() not in starts:
            findings.append(
                Finding(
                    severity=Severity.NEEDS_REVIEW,
                    check="DECLARATION_UNPARSED_CODE",
                    unit_id=u.id,
                    message="Tanım bölümünde girdi olarak ayrıştırılamayan kod benzeri ifade",
                    details={"section": sec.path, "text": sec.content.text[idx[m.start()] : idx[m.end() - 1] + 1]},
                )
            )


MALFORMED_COMMA_RE = re.compile(r",\d")


def extract_malformed_codes(text: str, known_prefixes: set[str]) -> list[str]:
    """Parantez içindeki bozuk kod yazımları (tahminle düzeltilmez, ham haliyle döner):
    nokta yerine virgül ("KB2,4") ve sayısız önek ("SDB")."""
    view, idx = dehyphen_view(text)
    out: list[str] = []
    for pm in re.finditer(r"\(([^()]*)\)", view, re.S):
        a = pm.start(1)
        inner = pm.group(1)
        for m in re.finditer(r"(?<![\w.])([^\W\d_]{1,5})(\d*(?:\.\d+)*,\d+(?:\.\d+)*|(?=\s*(?:,|$)))", inner):
            if m.group(1) not in known_prefixes:
                continue
            if m.group(2) or re.match(r"\s*(?:,|$)", inner[m.end(1) :]):
                s, e = a + m.start(), a + m.end()
                out.append(text[idx[s] : idx[e - 1] + 1])
    return out


def extract_used_codes(text: str, known_prefixes: set[str], lo_prefix: str) -> list[Code]:
    """Uygulama metnindeki kodlar. Parantez içindeki her kod ya da programda tanımlı bir
    önek taşıyan kod alınır; öğrenme çıktısı kodları hariçtir. Raw değer korunur."""
    view, idx = dehyphen_view(text)
    paren_ranges = [(m.start(), m.end()) for m in re.finditer(r"\([^()]*\)", view, re.S)]
    out: list[Code] = []
    for m in GENERIC_CODE_RE.finditer(view):
        if MALFORMED_COMMA_RE.match(view, m.end(1)):
            continue  # "KB2,4": bozuk yazım, extract_malformed_codes ile raporlanır
        raw = text[idx[m.start(1)] : idx[m.end(1) - 1] + 1]
        c = parse_code(raw)
        if c.prefix == lo_prefix:
            continue
        in_paren = any(a < m.start() < b for a, b in paren_ranges)
        # Küçük harf içeren önek kod değildir: ölçü birimi vb. (Fen s.133 "santimetreküp (cm3)")
        if (in_paren and c.prefix == tr_upper(c.prefix)) or c.prefix in known_prefixes:
            out.append(c)
    return out
