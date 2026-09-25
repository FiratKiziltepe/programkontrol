"""PDF iç tutarlılık kontrolleri ve analiz akışı.

Belirsizlikte tahmin yapılmaz: NEEDS_REVIEW üretilir. Beklenen ile çıkarılan
öğrenme çıktısı sayısı uyuşmuyorsa PASS verilmez.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from models import (
    SEVERITY_ORDER,
    Code,
    CodeCheck,
    ExpectedRow,
    ExpectedTable,
    ExtractionResult,
    Finding,
    ProgramSchema,
    SectionKind,
    Severity,
    Status,
    TableRole,
    TextField,
    Unit,
    UnitReport,
)
from pdf_extract import PdfDoc, context_in_title, extract_spans, lo_code_regex, make_field, norm_label, parse_code
from schema_detect import NUMBERED_NAME_RE, detect_schema, label_lookup, parse_expected_tables
from unit_extract import extract_units

TR_ALPHABET = "abcçdefgğhıijklmnoöprsştuüvyz"


def _f(sev: Severity, check: str, msg: str, unit: Unit | None = None, **details) -> Finding:
    return Finding(severity=sev, check=check, unit_id=unit.id if unit else None, message=msg, details=details)


# ---------------------------------------------------------------- beklenen değer eşleştirme


_ROW_CODE_PREFIX_RE = re.compile(r"^\s*[^\W\d_]+[ \t]*\.[ \t]*\d+(?:[ \t]*\.[ \t]*\d+)*[ \t]*\.?\s*")


def _row_name_key(row: ExpectedRow) -> str | None:
    """Özet tablosu satır adının eşleştirme anahtarı: baştaki sıra ("1.") veya kod ("MAT.1.3.") atılır."""
    if row.name is None:
        return None
    t = row.name.text
    if m := NUMBERED_NAME_RE.match(t):
        t = m.group(2)
    t = _ROW_CODE_PREFIX_RE.sub("", t, count=1)
    return norm_label(t) or None


def merge_title_continuations(units: list[Unit], tables: list[ExpectedTable], doc: PdfDoc, schema: ProgramSchema) -> None:
    """Birim başlığının altındaki satır, başlığın devamı mı yoksa alt başlık mı?

    Geometri tek başına ayırt edemez (Matematik s.156 "7. TEMA: OLAYLARIN OLASILIĞI VE" / "VERİYE DAYALI
    ARAŞTIRMA" ile Adigece s.83 "2. TEMA: OKULUM" / "Alt Temalar: …" aynı boyut ve renkte, satırları
    hafifçe üst üste). PDF'in kendi özet tablosu karar verir: başlık adı + alt satır bir tablo satırının
    adıyla birebir eşleşiyor ve başlık adı tek başına eşleşmiyorsa alt satır başlığın devamıdır."""
    from schema_detect import parse_unit_title

    row_keys = {k for t in tables if t.role == TableRole.SUMMARY for r in t.rows if (k := _row_name_key(r))}
    if not row_keys:
        return
    by_id = {sp.id: sp for sp in doc.spans}
    for u in units:
        if u.subtitle is None or u.name is None or norm_label(u.name) in row_keys:
            continue
        if norm_label(u.name + " " + u.subtitle.text) not in row_keys:
            continue
        title = make_field([by_id[i] for i in u.title.source_spans + u.subtitle.source_spans])
        parsed = parse_unit_title(title.text, schema.unit_keyword)
        if parsed is None:
            continue
        u.title, u.subtitle, u.name = title, None, parsed[1]


def match_expected(units: list[Unit], tables: list[ExpectedTable]) -> tuple[dict[str, ExpectedRow], list[Finding]]:
    findings: list[Finding] = []
    matched: dict[str, ExpectedRow] = {}
    used_rows: set[tuple[int, int]] = set()
    tables = [t for t in tables if t.role == TableRole.SUMMARY]
    for u in units:
        ctx = u.context.text if u.context else ""
        cands = [t for t in tables if t.title is not None and ctx and context_in_title(ctx, t.title.text)]
        if not cands and len(tables) == 1:
            cands = tables
        if len(cands) != 1:
            findings.append(
                _f(Severity.INFO, "EXPECTED_TABLE_AMBIGUOUS", "Birim için özet tablosu tekil olarak eşleşmedi", u, candidates=len(cands))
            )
            continue
        t = cands[0]
        # Satır önce adla eşleştirilir: tablo "işleniş sırası"na göre dizilmiş olabilir ve sıra
        # tema numarasıyla aynı olmayabilir (Matematik s.10: 1. sıra "MAT.1.3. Nesnelerin Geometrisi (1)"
        # = "5. TEMA: NESNELERİN GEOMETRİSİ (1)"). Ad tekil eşleşmezse sıra numarasıyla eşleştirilir.
        rows = [r for r in t.rows if r.order is not None and u.name is not None and _row_name_key(r) == norm_label(u.name)]
        if len(rows) != 1:
            rows = [r for r in t.rows if r.order is not None and r.order == u.order]
        if len(rows) != 1:
            findings.append(_f(Severity.INFO, "EXPECTED_ROW_AMBIGUOUS", "Birim için özet tablosu satırı tekil olarak eşleşmedi", u, table_page=t.page))
            continue
        row = rows[0]
        row_key = _row_name_key(row)  # baştaki sıra ("1.") / kod ("MAT.1.3.") hariç ad
        if row_key is not None and u.name is not None and row_key != norm_label(u.name):
            findings.append(
                _f(Severity.NEEDS_REVIEW, "UNIT_NAME_MISMATCH", "Özet tablosundaki ad ile birim başlığındaki ad farklı", u, table=row.name.text, unit_name=u.name)
            )
        matched[u.id] = row
        used_rows.add((row.table_index, t.rows.index(row)))
    matched_tables = {i for i, _ in used_rows}
    for t in tables:
        if t.index not in matched_tables:
            # Hiçbir birimle eşleşmeyen tablo (başlık/bağlam okunamadı): yalnızca bilgi
            findings.append(_f(Severity.INFO, "EXPECTED_TABLE_UNMATCHED", "Özet tablosu hiçbir birimle eşleştirilemedi", None, table=t.title.text if t.title else None, page=t.page))
            continue
        for n, r in enumerate(t.rows):
            if r.order is not None and (t.index, n) not in used_rows:
                findings.append(
                    _f(
                        Severity.FAIL,
                        "MISSING_UNIT",
                        "Özet tablosunda olan birim PDF'den çıkarılamadı",
                        None,
                        table=t.title.text if t.title else None,
                        order=r.order,
                        name=r.name.text if r.name else None,
                    )
                )
    return matched, findings


def check_tables(tables: list[ExpectedTable]) -> list[Finding]:
    out = []
    for t in tables:
        if t.role == TableRole.LO_LIST:
            for c in t.lo_columns:
                for f in c.unparsed:
                    out.append(_f(Severity.NEEDS_REVIEW, "LO_LIST_UNPARSED", "Öğrenme çıktısı listesi tablosunda kod olarak okunamayan satır", None, table=t.title.text if t.title else None, order=c.order, text=f.text))
            continue
        unit_rows = [r for r in t.rows if r.order is not None]
        total = next((r for r in t.rows if r.is_total), None)
        for r in unit_rows:
            if r.lo_count is None:
                out.append(_f(Severity.INFO, "EXPECTED_COUNT_UNREADABLE", "Özet tablosunda öğrenme çıktısı sayısı okunamadı", None, table=t.title.text if t.title else None, order=r.order, raw=r.lo_count_raw))
        if total is not None and all(r.lo_count is not None for r in unit_rows):
            s = sum(r.lo_count for r in unit_rows)
            if s != total.lo_count:
                out.append(_f(Severity.NEEDS_REVIEW, "TABLE_TOTAL_INCONSISTENT", "Özet tablosunun toplamı satırların toplamıyla uyuşmuyor (kaynak PDF)", None, table=t.title.text if t.title else None, rows_sum=s, table_total=total.lo_count))
    return out


def check_limited_tables(units: list[Unit], tables: list[ExpectedTable]) -> list[Finding]:
    """Sınırlı (alternatif) süre tablosu ve öğrenme çıktısı listesi kontrolü (Afet: haftada 1 saat).

    Beklenen sayılar tam tablodan alınır; sınırlı tablodaki her birimin ÖÇ sayısı, aynı bağlamdaki
    ÖÇ listesi tablosunun o birim sütunundaki kod sayısıyla, listedeki kodlar da birimin PDF'deki
    öğrenme çıktılarıyla karşılaştırılır. Uyuşmazlık NEEDS_REVIEW."""
    out: list[Finding] = []
    alts = [t for t in tables if t.role == TableRole.ALTERNATIVE]
    lists = [t for t in tables if t.role == TableRole.LO_LIST]
    if not alts and not lists:
        return out

    def for_unit(u: Unit, ts: list[ExpectedTable]) -> list[ExpectedTable]:
        return [t for t in ts if t.title is not None and u.context is not None and context_in_title(u.context.text, t.title.text)]

    for u in units:
        u_alts, u_lists = for_unit(u, alts), for_unit(u, lists)
        if not u_alts and not u_lists:
            continue
        if len(u_alts) != 1 or len(u_lists) != 1:
            out.append(_f(Severity.NEEDS_REVIEW, "LIMITED_TABLE_AMBIGUOUS", "Sınırlı süre tablosu ve öğrenme çıktısı listesi birime tekil olarak eşleşmedi", u, alternatives=len(u_alts), lo_lists=len(u_lists)))
            continue
        alt, lst = u_alts[0], u_lists[0]
        rows = [r for r in alt.rows if r.order == u.order]
        cols = [c for c in lst.lo_columns if c.order == u.order]
        if len(rows) != 1 or len(cols) != 1:
            out.append(_f(Severity.NEEDS_REVIEW, "LIMITED_ROW_AMBIGUOUS", "Sınırlı süre tablosunda veya öğrenme çıktısı listesinde birimin satırı/sütunu tekil değil", u, table=alt.title.text, lo_list=lst.title.text))
            continue
        row, col = rows[0], cols[0]
        if row.lo_count != len(col.codes):
            out.append(
                _f(
                    Severity.NEEDS_REVIEW,
                    "LIMITED_LO_COUNT_MISMATCH",
                    "Sınırlı süre tablosundaki öğrenme çıktısı sayısı ile öğrenme çıktısı listesindeki kod sayısı farklı",
                    u,
                    table=alt.title.text,
                    table_count=row.lo_count_raw,
                    listed=[c.text for c in col.codes],
                )
            )
        pdf_keys = {lo.code.key for lo in u.learning_outcomes}
        for c in col.codes:
            if parse_code(c.text).key not in pdf_keys:
                out.append(_f(Severity.NEEDS_REVIEW, "LIMITED_LO_NOT_FOUND", "Öğrenme çıktısı listesindeki kod birimin öğrenme çıktıları arasında yok", u, code_raw=c.text, lo_list=lst.title.text, page=lst.page))
    return out


# ---------------------------------------------------------------- birim kontrolleri


def check_sections(u: Unit, schema: ProgramSchema) -> list[Finding]:
    out: list[Finding] = []
    lookup = label_lookup(schema)  # başlık/parça norm -> yapı sayfasındaki sıra
    seen = [s.label_norm for s in u.sections if s.label_norm is not None]
    dup = [n for n, c in Counter(seen).items() if c > 1]
    if dup:
        out.append(_f(Severity.NEEDS_REVIEW, "DUPLICATE_SECTION", "Aynı bölüm başlığı birimde birden fazla kez geçiyor", u, labels=dup))
    seen_idx = {lookup[n] for n in seen if n in lookup}
    missing = [l.text for i, l in enumerate(schema.labels) if i not in seen_idx]
    if missing:
        out.append(_f(Severity.NEEDS_REVIEW, "MISSING_SECTION", "Yapı sayfasındaki bölüm başlığı birimde bulunamadı", u, labels=missing))
    for sec in u.sections:
        if sec.label is not None and sec.kind != SectionKind.GROUP and sec.content is None:
            # Kapsama kontrolü hiçbir span'ın kaybolmadığını garanti ettiği için boşluk kaynak PDF'dedir.
            out.append(_f(Severity.WARNING, "EMPTY_SECTION", "Bölüm başlığının altı boş (kaynak PDF)", u, section=sec.path, label_spans=sec.label.source_spans))
    known = [n for n in seen if n in lookup]
    order = [lookup[n] for n in known]
    if order != sorted(order):
        out.append(_f(Severity.NEEDS_REVIEW, "SECTION_ORDER", "Bölüm sırası yapı sayfasındaki sıradan farklı", u, labels=known))
    # Bölüm karışması: bir bölümün içeriğinde başka bir bölüm başlığı satır olarak geçiyor
    for sec in u.sections:
        # Bileşik başlığın ("İlkeler/Anahtar Kavramlar") içeriği kendi parçalarını gövde metninde
        # alt başlık olarak yazabilir (Fen s.208: "İlkeler" / "Kütlenin korunumu"); bu karışma değildir.
        own_parts = {norm_label(p) for p in sec.label.text.split("/")} if sec.label is not None and "/" in sec.label.text else set()
        for row in sec.content_rows:
            rn = norm_label(row.text)
            if rn in own_parts:
                continue
            for l in schema.labels:
                if len(l.norm) >= 4 and (rn == l.norm or rn in l.parts):
                    out.append(
                        _f(
                            Severity.FAIL,
                            "SECTION_LEAKAGE",
                            "Bölüm içeriğinde başka bir bölüm başlığı var",
                            u,
                            section=sec.path,
                            leaked_label=l.text,
                            row=row.text,
                            spans=row.source_spans,
                        )
                    )
    return out


def learn_code_scheme(units: list[Unit], schema: ProgramSchema) -> dict:
    """Öğrenme çıktısı kodlarının numaralandırma şeması programın çoğunluğundan öğrenilir.

    - theme_segment: sondan ikinci segment birimin sırası mı? (Müzik MÜZ.5.1.3: evet; Matematik
      MAT.1.3.2: hayır, içerik alanıdır — 5. TEMA "Nesnelerin Geometrisi (1)" MAT.1.3.x)
    - expected_last: son segment sayıysa her ÖÇ için beklenen numara. Çoğunlukta numaralar birim
      içinde 1'den başlıyorsa birim içi sıra; aksi halde aynı kod grubunda (son segment hariç)
      birimler boyunca devam eden sıra (Matematik: MAT.1.1.1-7 1. temada, MAT.1.1.8 2. temada)."""
    types = schema.lo_segment_types
    scored = [u for u in units if u.learning_outcomes]
    theme_ok = sum(
        1 for u in scored if u.order is not None and all(len(lo.code.segments) >= 2 and lo.code.segments[-2] == str(u.order) for lo in u.learning_outcomes)
    )
    theme_segment = len(types) >= 3 and types[-2] == "n" and theme_ok * 2 >= len(scored)
    per_unit = {(u.id, i): i for u in scored for i in range(1, len(u.learning_outcomes) + 1)}
    per_group: dict[tuple[str, int], int] = {}
    counter: Counter = Counter()
    for u in scored:
        for i, lo in enumerate(u.learning_outcomes, start=1):
            g = (lo.code.prefix, tuple(lo.code.segments[:-1]))
            counter[g] += 1
            per_group[(u.id, i)] = counter[g]

    def fits(exp: dict) -> int:
        return sum(1 for u in scored if all(lo.code.segments[-1:] == [str(exp[(u.id, i)])] for i, lo in enumerate(u.learning_outcomes, start=1)))

    expected_last = per_unit if fits(per_unit) >= fits(per_group) else per_group
    return {"theme_segment": theme_segment, "expected_last": expected_last}


def check_learning_outcomes(u: Unit, expected: ExpectedRow | None, schema: ProgramSchema, scheme: dict | None = None) -> list[Finding]:
    scheme = scheme or {"theme_segment": True, "expected_last": {(u.id, i): i for i in range(1, len(u.learning_outcomes) + 1)}}
    out: list[Finding] = []
    los = u.learning_outcomes
    if expected is None or expected.lo_count is None:
        out.append(_f(Severity.INFO, "EXPECTED_COUNT_MISSING", "Beklenen öğrenme çıktısı sayısı bilinmiyor", u, extracted=len(los)))
    elif expected.lo_count != len(los):
        out.append(
            _f(
                Severity.FAIL,
                "LO_COUNT_MISMATCH",
                "Beklenen ve çıkarılan öğrenme çıktısı sayısı farklı",
                u,
                expected=expected.lo_count,
                extracted=len(los),
                diff=len(los) - expected.lo_count,
            )
        )
    # Kod kimliği ve sırası
    grade = None
    if u.context is not None:
        m = re.match(r"\s*(\d+)", u.context.text)
        grade = int(m.group(1)) if m else None
    keys = [lo.code.key for lo in los]
    for k, c in Counter(keys).items():
        if c > 1:
            out.append(_f(Severity.FAIL, "DUPLICATE_LO_CODE", "Öğrenme çıktısı kodu tekrarlı", u, code=".".join(map(str, k[1]))))
    for i, lo in enumerate(los, start=1):
        segs = lo.code.segments
        types = ["n" if x.isdigit() else "a" for x in segs]
        problems = []
        if lo.code.prefix != schema.lo_prefix:
            problems.append("önek")
        if types != schema.lo_segment_types:
            problems.append("segment yapısı")
        else:
            if grade is not None and len(segs) >= 3 and segs[-3] != str(grade):
                problems.append("sınıf")
            if scheme["theme_segment"] and u.order is not None and segs[-2] != str(u.order):
                problems.append("tema sırası")
            # Son segment sayıysa öğrenilen şemaya göre sıra olmalı; kısaltmaysa (ör. beceri) ayrı kontrol edilir
            if types[-1] == "n" and segs[-1] != str(scheme["expected_last"].get((u.id, i), i)):
                problems.append("çıktı sırası")
        if problems:
            out.append(_f(Severity.FAIL, "LO_CODE_IDENTITY", "Öğrenme çıktısı kodu birimle/sırayla uyuşmuyor", u, code_raw=lo.code.raw, problems=problems, position=i))
        # Süreç bileşeni harfleri
        letters = [c.letter for c in lo.components]
        expected_letters = list(TR_ALPHABET[: len(letters)])
        if not letters:
            pass  # süreç bileşeni olmayan öğrenme çıktısı PDF'de geçerlidir (ör. Hayat Bilgisi HB.1.1.1); bulgu değil
        elif letters == [""]:
            pass  # tek, işaretsiz süreç bileşeni (ör. Arnavutça DBS/SÖS/SES): harf kontrolü uygulanmaz
        elif letters != expected_letters:
            out.append(
                _f(Severity.NEEDS_REVIEW, "COMPONENT_LETTER_SEQUENCE", "Süreç bileşeni harfleri sıralı/boşluksuz değil", u, code_raw=lo.code.raw, letters=letters, expected=expected_letters)
            )
    return out


def check_applications(u: Unit) -> list[Finding]:
    out: list[Finding] = []
    lo_keys = [lo.code.key for lo in u.learning_outcomes]
    blocks = [b for b in u.applications if b.code is not None]
    block_keys = Counter(b.code.key for b in blocks)
    for lo in u.learning_outcomes:
        n = block_keys.get(lo.code.key, 0)
        if n == 0:
            out.append(_f(Severity.FAIL, "APPLICATION_MISSING", "Öğrenme çıktısının öğrenme-öğretme uygulaması bulunamadı", u, code_raw=lo.code.raw))
        elif n > 1:
            out.append(_f(Severity.FAIL, "APPLICATION_DUPLICATE", "Öğrenme çıktısı için birden fazla uygulama bloğu var", u, code_raw=lo.code.raw, count=n))
    for b in blocks:
        if b.code.key not in lo_keys:
            out.append(_f(Severity.FAIL, "APPLICATION_UNKNOWN_CODE", "Uygulama bloğu birimde olmayan bir öğrenme çıktısına ait", u, code_raw=b.code.raw))
        if b.body is None:
            out.append(_f(Severity.NEEDS_REVIEW, "APPLICATION_EMPTY", "Uygulama bloğu boş", u, code_raw=b.code.raw))
    # Uygulama sırası öğrenme çıktısı sırasını izlemeli
    order = [b.code.key for b in blocks if b.code.key in lo_keys]
    if order != [k for k in lo_keys if k in order]:
        out.append(_f(Severity.NEEDS_REVIEW, "APPLICATION_ORDER", "Uygulama blokları öğrenme çıktısı sırasında değil", u))
    return out


def _covers(declared: Code, used: Code) -> bool:
    return declared.prefix == used.prefix and used.segments[: len(declared.segments)] == declared.segments


def is_field_skills(path: str) -> bool:
    """Alan becerileri tanım bölümü mü (ör. "ALAN BECERİLERİ", "FIELD SKILLS ...")?"""
    from schema_detect import FIELD_SKILL_HINTS, _hint

    return _hint(path.split(">")[-1], FIELD_SKILL_HINTS)


def field_skill_prefixes(units: list[Unit]) -> set[str]:
    return {d.code.prefix for u in units for path, ds in u.declarations.items() if is_field_skills(path) for d in ds}


def declared_min_segments(units: list[Unit]) -> dict[str, int]:
    """Önek -> program genelinde tanımlı kodların en az segment sayısı (ör. E -> 2: E1.1)."""
    out: dict[str, int] = {}
    for u in units:
        for ds in u.declarations.values():
            for d in ds:
                out[d.code.prefix] = min(out.get(d.code.prefix, 99), len(d.code.segments))
    return out


def check_codes(
    u: Unit, alan_prefixes: set[str] = frozenset(), min_segments: dict[str, int] | None = None
) -> tuple[list[CodeCheck], list[str], list[Finding]]:
    """Girişte tanımlanan kodlar ile uygulamalarda kullanılan kodların iki yönlü kontrolü.

    Alan becerileri kontrol dışıdır (sistem Excel'i ile karşılaştırmada kullanılacak):
    - alan becerileri için "tanımlı ama kullanılmamış" üretilmez,
    - alan becerisi önekli bir kod tanımsız kullanılmışsa FAIL üretilmez.
    Alan becerisi tanımları yine de kullanılan kodu karşılar (ör. SAB9 kullanımı).
    """
    out: list[Finding] = []
    used: list[tuple[Code, Code]] = []  # (kullanılan kod, bulunduğu uygulama bloğunun LO kodu)
    for b in u.applications:
        for c in b.used_codes:
            used.append((c, b.code))
    checks: list[CodeCheck] = []
    all_declared = [(path, d.code) for path, ds in u.declarations.items() for d in ds]
    for path, ds in u.declarations.items():
        if is_field_skills(path):
            continue
        matched_used = sorted({c.normalized for c, _ in used if any(_covers(d.code, c) for d in ds)})
        matched, unused = [], []
        for d in ds:
            if any(_covers(d.code, c) for c, _ in used):
                matched.append(d.code.normalized)
            else:
                unused.append(d.code.normalized)
                out.append(
                    _f(Severity.WARNING, "DECLARED_NOT_USED", "Tanımlanmış ama uygulamalarda kullanılmamış kod", u, category=path, code_raw=d.code.raw)
                )
        checks.append(CodeCheck(category=path, declared=[d.code.normalized for d in ds], used=matched_used, matched=matched, declared_not_used=unused))
    not_declared: list[str] = []
    min_segments = min_segments or {}
    for b in u.applications:
        for raw in b.malformed_codes:
            out.append(
                _f(Severity.NEEDS_REVIEW, "USED_CODE_MALFORMED", "Uygulamada bozuk yazılmış kod (kaynak PDF; tahminle düzeltilmedi)", u, code_raw=raw, in_application_of=b.code.raw if b.code else None)
            )
    for c, lo_code in used:
        if any(_covers(d, c) for _, d in all_declared) or c.prefix in alan_prefixes:
            continue
        if len(c.segments) < min_segments.get(c.prefix, 0):
            # Tanımlardan daha az ayrıntılı (ör. tanımlar E1.1 düzeyinde, kullanım "E1"): eksik kod
            out.append(
                _f(Severity.NEEDS_REVIEW, "USED_CODE_INCOMPLETE", "Uygulamada tanımlardan daha az ayrıntılı (eksik) kod (kaynak PDF)", u, code_raw=c.raw, in_application_of=lo_code.raw if lo_code else None)
            )
            continue
        not_declared.append(c.normalized)
        out.append(
            _f(
                Severity.FAIL,
                "USED_NOT_DECLARED",
                "Uygulamalarda kullanılmış ama tema/ünite girişinde tanımlanmamış kod",
                u,
                code_raw=c.raw,
                in_application_of=lo_code.raw if lo_code else None,
            )
        )
    # Tanımsız kullanılan kodlar, önek ve ilk numarası tanımlarıyla uyan tek kategoriye yazılır (D14.2 -> Değerler;
    # KB2.x -> Kavramsal Beceriler, KB3.x -> Beceriler Arası İlişkiler). Tekil kategori yoksa yalnızca birim
    # raporundaki listede kalır.
    by_path = {c.category: c for c in checks}
    for norm in sorted(set(not_declared)):
        c = parse_code(norm)
        cands = [p for p, ds in u.declarations.items() if p in by_path and any(d.code.prefix == c.prefix for d in ds)]
        if len(cands) > 1:
            cands = [p for p in cands if any(d.code.prefix == c.prefix and d.code.numbers[:1] == c.numbers[:1] for d in u.declarations[p])]
        if len(cands) == 1:
            by_path[cands[0]].used_not_declared.append(norm)
    return checks, sorted(set(not_declared)), out


def check_hours(u: Unit, expected: ExpectedRow | None) -> tuple[int | None, list[Finding]]:
    from schema_detect import HOURS_COLUMN_HINTS, _hint

    secs = [s for s in u.sections if s.label is not None and _hint(s.label.text, HOURS_COLUMN_HINTS)]
    if len(secs) != 1 or secs[0].content is None:
        return None, [_f(Severity.INFO, "HOURS_NOT_FOUND", "Birimde ders saati bölümü tekil olarak bulunamadı", u)]
    txt = secs[0].content.text.strip()
    val = int(txt) if txt.isdigit() else None
    if val is None:
        return None, [_f(Severity.INFO, "HOURS_UNREADABLE", "Ders saati sayı olarak okunamadı", u, raw=txt)]
    if expected is None or expected.hours is None:
        return val, [_f(Severity.INFO, "EXPECTED_HOURS_MISSING", "Özet tablosunda ders saati bulunamadı", u)]
    if expected.hours != val:
        return val, [_f(Severity.FAIL, "HOURS_MISMATCH", "Birimdeki ders saati özet tablosundan farklı", u, expected=expected.hours, extracted=val)]
    return val, []


def check_skill_order(units: list[Unit], schema: ProgramSchema) -> list[Finding]:
    """Son segmenti kısaltma olan kodlarda (ör. ARN.5.1.D / .O / .K ...) kısaltma sırası,
    temaların çoğunluğundaki sıradan öğrenilir; sapan tema NEEDS_REVIEW olur."""
    if not schema.lo_segment_types or schema.lo_segment_types[-1] != "a":
        return []
    seqs = {u.id: tuple(lo.code.segments[-1] for lo in u.learning_outcomes) for u in units}
    common = Counter(seqs.values()).most_common(1)
    if not common:
        return []
    major = common[0][0]
    return [
        _f(Severity.NEEDS_REVIEW, "LO_SKILL_ORDER", "Öğrenme çıktısı kısaltma sırası diğer temalardan farklı", u, found=list(seqs[u.id]), expected=list(major))
        for u in units
        if seqs[u.id] != major
    ]


def check_code_format(units: list[Unit], schema: ProgramSchema) -> list[Finding]:
    """Baskın biçimden sapan raw öğrenme çıktısı kodları: kaynak PDF anomalisi (uyarı)."""
    occ: list[tuple[Unit, str, str]] = []
    for u in units:
        for lo in u.learning_outcomes:
            occ.append((u, lo.code.raw, "öğrenme çıktıları"))
        for b in u.applications:
            if b.code is not None:
                occ.append((u, b.code.raw, "öğrenme-öğretme uygulamaları"))
    def shape(raw: str) -> str:
        # rakamlar "N", önekten sonraki büyük harfli kısaltma segmentleri "A" olur (ARN.5.1.D ~ ARN.5.1.DBS)
        pre = schema.lo_prefix
        head, rest = (raw[: raw.index(pre) + len(pre)], raw[raw.index(pre) + len(pre) :]) if pre in raw else ("", raw)
        return head + re.sub(r"\d+", "N", re.sub(r"[A-ZÇĞİÖŞÜ]+", "A", rest))

    # Baskın biçim bölüm bazında hesaplanır: bazı programlarda öğrenme çıktıları bölümünde
    # "BİY.9.1.1.", uygulama başlıklarında tutarlı biçimde "BİY.9.1.1" yazılır; bu bir anomali değildir.
    dom_by_where = {
        w: Counter(shape(r) for _, r, ww in occ if ww == w).most_common(1)[0][0] for w in {w for _, _, w in occ}
    }
    out = [
        _f(Severity.WARNING, "CODE_FORMAT_ANOMALY", "Kod baskın biçimden farklı yazılmış (kaynak PDF)", u, code_raw=raw, dominant_format=dom_by_where[where], where=where)
        for u, raw, where in occ
        if shape(raw) != dom_by_where[where]
    ]
    for u in units:
        for path, ds in u.declarations.items():
            for d in ds:
                if d.entry.text.strip() == d.code.raw.strip():
                    # ör. Kurmanca "KB2.13. Yapılandırma, KB2.14, KB2.15. ...": kod listede var, adı yok
                    out.append(_f(Severity.NEEDS_REVIEW, "DECLARATION_NAME_MISSING", "Tanımda kodun adı yazılmamış (kaynak PDF)", u, code_raw=d.code.raw, where=path))
                    continue
                if not d.standard_format:
                    out.append(
                        _f(
                            Severity.WARNING,
                            "CODE_FORMAT_ANOMALY",
                            "Tanımdaki kod standart biçimde değil (kaynak PDF)",
                            u,
                            code_raw=d.code.raw,
                            normalized=d.code.normalized,
                            where=path,
                            entry=d.entry.text,
                        )
                    )
    return out


# ---------------------------------------------------------------- metin sadakati ve kapsama


def _iter_fields(u: Unit):
    if u.context:
        yield u.context
    yield u.title
    if u.subtitle:
        yield u.subtitle
    for s in u.sections:
        for f in (s.label, s.content, *s.content_rows):
            if f is not None:
                yield f
    for lo in u.learning_outcomes:
        yield lo.title
        for c in lo.components:
            yield c.text
    for b in u.applications:
        for f in (b.header, b.body):
            if f is not None:
                yield f
    for ds in u.declarations.values():
        for d in ds:
            yield d.entry


def check_fidelity(units: list[Unit], doc: PdfDoc) -> list[Finding]:
    """Her çıkarılan metin, kaynak span'larının metninin (boşluklar hariç) bir parçası olmalı."""
    by_id = {s.id: s for s in doc.spans}
    out = []
    ws = re.compile(r"\s+")
    for u in units:
        for f in _iter_fields(u):
            if not f.source_spans:
                out.append(_f(Severity.FAIL, "NO_SOURCE_SPANS", "Metin kaynak span'a bağlı değil", u, text=f.text[:80]))
                continue
            src = ws.sub("", "".join(by_id[i].text for i in f.source_spans))
            if ws.sub("", f.text) not in src:
                out.append(_f(Severity.FAIL, "TEXT_NOT_IN_SOURCE", "Çıkarılan metin kaynak span'larda birebir yok", u, text=f.text[:80]))
    return out


def check_coverage(units: list[Unit], result_regions, doc: PdfDoc, schema: ProgramSchema) -> list[Finding]:
    """Gerçek veri bölgesindeki her span tam olarak bir yere atanmış olmalı."""
    assigned: Counter[str] = Counter()
    # Bağlam başlığı (ör. "5. SINIF") birden fazla birimde paylaşılabilir; bir kez sayılır.
    assigned.update({i for u in units if u.context for i in u.context.source_spans})
    for u in units:
        ids = set()
        ids.update(u.title.source_spans)
        if u.subtitle:
            ids.update(u.subtitle.source_spans)
        for s in u.sections:
            for f in (s.label, s.content):
                if f is not None:
                    ids.update(f.source_spans)
        assigned.update(ids)
    for r in result_regions:
        assigned.update(r.source_spans)
    out = []
    pool = [s for s in doc.spans if s.page >= schema.data_start_page and s.id not in doc.furniture and s.text.strip()]
    missing = [s.id for s in pool if assigned[s.id] == 0]
    double = [i for i, c in assigned.items() if c > 1]
    if missing:
        out.append(_f(Severity.NEEDS_REVIEW, "UNASSIGNED_SPANS", "Hiçbir bölüme atanmamış metin var", None, spans=missing[:50], count=len(missing)))
    if double:
        out.append(_f(Severity.FAIL, "DOUBLE_ASSIGNED_SPANS", "Aynı metin birden fazla bölüme atanmış", None, spans=double[:50], count=len(double)))
    return out


# ---------------------------------------------------------------- akış


def _worst(findings: list[Finding]) -> Status:
    if not findings:
        return Status.PASS
    w = max(findings, key=lambda f: SEVERITY_ORDER[f.severity]).severity
    return {Severity.INFO: Status.PASS, Severity.WARNING: Status.WARNING, Severity.NEEDS_REVIEW: Status.NEEDS_REVIEW, Severity.FAIL: Status.FAIL}[w]


def analyze_pdf(path: str) -> ExtractionResult:
    doc = extract_spans(path)
    schema = detect_schema(doc)
    tables = parse_expected_tables(doc, schema)
    units, regions, findings = extract_units(doc, schema, [t.title.text for t in tables if t.title])

    if not schema.structure_pages:
        findings.append(
            _f(
                Severity.NEEDS_REVIEW,
                "STRUCTURE_PAGE_NOT_FOUND",
                "Program yapısı/tanıtım sayfası bulunamadı; bölüm başlıkları ve kod deseni tema sayfalarından öğrenildi",
                None,
                labels=[l.text for l in schema.labels],
                lo_prefix=schema.lo_prefix,
            )
        )
    if doc.removed_controls:
        findings.append(
            _f(
                Severity.INFO,
                "CONTROL_CHARS_REMOVED",
                "PDF metin katmanındaki görünmez kontrol karakterleri (görünür metin değil) çıkarımda atıldı",
                None,
                pages=sorted(doc.removed_controls),
                count=sum(doc.removed_controls.values()),
            )
        )
    findings += check_tables(tables)
    if not tables:
        findings.append(_f(Severity.INFO, "EXPECTED_TABLE_NOT_FOUND", "Özet/süre tablosu bulunamadı; beklenen sayılar bilinmiyor"))
    merge_title_continuations(units, tables, doc, schema)
    scheme = learn_code_scheme(units, schema)
    matched, fs = match_expected(units, tables)
    findings += fs
    reports: list[UnitReport] = []
    alan_prefixes = field_skill_prefixes(units)
    min_segs = declared_min_segments(units)
    for u in units:
        exp = matched.get(u.id)
        uf: list[Finding] = []
        uf += check_sections(u, schema)
        uf += check_learning_outcomes(u, exp, schema, scheme)
        uf += check_applications(u)
        checks, not_declared, cf = check_codes(u, alan_prefixes, min_segs)
        uf += cf
        hours, hf = check_hours(u, exp)
        uf += hf
        findings += uf
        reports.append(
            UnitReport(
                unit_id=u.id,
                title=u.title.text,
                context=u.context.text if u.context else None,
                expected_lo=exp.lo_count if exp else None,
                extracted_lo=len(u.learning_outcomes),
                expected_hours=exp.hours if exp else None,
                extracted_hours=hours,
                code_checks=checks,
                used_not_declared=not_declared,
            )
        )
    findings += check_code_format(units, schema)
    findings += check_skill_order(units, schema)
    findings += check_fidelity(units, doc)
    findings += check_coverage(units, regions, doc, schema)

    findings += check_limited_tables(units, tables)
    summary_tables = [t for t in tables if t.role == TableRole.SUMMARY]
    expected_rows = [r for t in summary_tables for r in t.rows if r.order is not None]
    expected_total = sum(r.lo_count for r in expected_rows) if expected_rows and all(r.lo_count is not None for r in expected_rows) else None
    extracted_total = sum(len(u.learning_outcomes) for u in units)
    # Program toplamları yalnızca tüm özet tabloları birimlerle eşleştiyse karşılaştırılır; aksi halde
    # beklenen değer bilinmiyor sayılır (ders saati/süre tablosu analizi durdurmaz).
    tables_usable = bool(summary_tables) and not any(f.check == "EXPECTED_TABLE_UNMATCHED" for f in fs)
    if not tables_usable:
        expected_total = None
        if summary_tables:
            findings.append(_f(Severity.INFO, "EXPECTED_TOTAL_UNKNOWN", "Özet tabloları birimlerle tam eşleşmediği için program toplamı karşılaştırılmadı", None, extracted=extracted_total))
    else:
        if len(expected_rows) != len(units):
            findings.append(_f(Severity.FAIL, "UNIT_COUNT_MISMATCH", "Beklenen ve bulunan tema/ünite sayısı farklı", None, expected=len(expected_rows), found=len(units)))
        if expected_total is not None and expected_total != extracted_total:
            findings.append(_f(Severity.FAIL, "LO_TOTAL_MISMATCH", "Program toplamında beklenen ve çıkarılan öğrenme çıktısı sayısı farklı", None, expected=expected_total, extracted=extracted_total))

    for r in reports:
        r.status = _worst([f for f in findings if f.unit_id == r.unit_id])
    return ExtractionResult(
        source=str(path),
        page_count=doc.page_count,
        schema=schema,
        expected_tables=tables,
        units=units,
        excluded_regions=regions,
        findings=findings,
        unit_reports=reports,
        expected_unit_count=len(expected_rows),
        expected_lo_total=expected_total,
        extracted_lo_total=extracted_total,
        status=_worst(findings),
    )


def format_report(res: ExtractionResult) -> str:
    L = []
    s = res.schema_
    L.append(f"Kaynak: {res.source} ({res.page_count} sayfa)")
    L.append(f"Yapı sayfaları: {s.structure_pages or 'bulunamadı (tema sayfalarından öğrenildi)'} | {s.structure_heading.text if s.structure_heading else ''}")
    L.append(f"Gerçek veri başlangıcı: s.{s.data_start_page} | birim anahtar kelimesi: {s.unit_keyword} | ÖÇ kod öneki: {s.lo_prefix} ({".".join(s.lo_segment_types)})")
    L.append(f"Tema/ünite: beklenen {res.expected_unit_count}, bulunan {len(res.units)}")
    L.append(f"Öğrenme çıktısı toplamı: beklenen {res.expected_lo_total}, çıkarılan {res.extracted_lo_total}")
    L.append("")
    for r in res.unit_reports:
        L.append(f"[{r.status.value}] {r.unit_id} {r.context or ''} | {r.title}")
        L.append(f"    Öğrenme çıktısı: beklenen {r.expected_lo}, bulunan {r.extracted_lo} | Ders saati: beklenen {r.expected_hours}, bulunan {r.extracted_hours}")
        u = next(x for x in res.units if x.id == r.unit_id)
        for path, ds in u.declarations.items():
            if is_field_skills(path):
                L.append(f"    {path} (kod kontrolü dışı): {', '.join(d.code.normalized for d in ds)}")
        for c in r.code_checks:
            extra = f" | kullanılmayan: {', '.join(c.declared_not_used)}" if c.declared_not_used else ""
            extra += f" | TANIMSIZ KULLANILAN: {', '.join(c.used_not_declared)}" if c.used_not_declared else ""
            L.append(f"    {c.category}: tanımlanan {', '.join(c.declared)}{extra}")
        if r.used_not_declared:
            L.append(f"    KULLANILMIŞ AMA TANIMLANMAMIŞ: {', '.join(r.used_not_declared)}")
        for f in res.findings:
            if f.unit_id == r.unit_id and f.severity != Severity.WARNING:
                L.append(f"    {f.severity.value} {f.check}: {f.message} {json.dumps(f.details, ensure_ascii=False)[:200]}")
    L.append("")
    prog = [f for f in res.findings if f.unit_id is None or f.check == "CODE_FORMAT_ANOMALY"]
    if prog:
        L.append("Program düzeyi bulgular:")
        for f in prog:
            L.append(f"  {f.severity.value} {f.check} {f.unit_id or ''}: {f.message} {json.dumps(f.details, ensure_ascii=False)[:200]}")
    L.append("")
    L.append("Tema dışı bırakılan bölgeler: " + "; ".join(f"{(r.heading.text if r.heading else '-')} s.{r.pages}" for r in res.excluded_regions))
    L.append(f"GENEL DURUM: {res.status.value}")
    return "\n".join(L)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("kullanım: python validators.py <pdf> [çıktı.json]")
        return 2
    res = analyze_pdf(argv[1])
    out = Path(argv[2]) if len(argv) > 2 else Path("temp") / "extracted.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(res.model_dump_json(indent=1, by_alias=True), encoding="utf-8")
    print(format_report(res))
    print(f"\nJSON: {out}")
    return 0 if res.status in (Status.PASS, Status.WARNING) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
