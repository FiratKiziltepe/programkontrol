"""PDF çıkarım sonucu ile müfredat sisteminden indirilen Excel'in karşılaştırılması.

Satır numarasına göre değil, mantıksal eşleştirme yapılır:
1. öğrenme çıktısı kodu (tema, ÖÇ kodlarından bulunur), 2. tema, 3. bölüm/sütun, 4. içerik.
İki yön de raporlanır: PDF'de var Excel'de yok / Excel'de var PDF'de yok.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass

import pandas as pd

from excel_export import code_sort_key, section_for_header
from excel_import import Cell, ExcelLO, ExcelTheme, SystemExcel, code_items, list_items, strip_placeholder
from models import Code, ExtractionResult, SectionKind, TextField, Unit
from pdf_extract import compare_key, lo_code_regex, loose_lo_code_regex, norm_label, parse_code, tr_lower

AYNI = "AYNI"
BICIM = "SADECE_BİÇİM_FARKI"
PDF_VAR = "PDF_DE_VAR_EXCELDE_YOK"
EXCEL_VAR = "EXCELDE_VAR_PDF_DE_YOK"
YANLIS_BOLUM = "YANLIŞ_BÖLÜM"
KOD_FARKLI = "KOD_FARKLI"
METIN_FARKLI = "METİN_FARKLI"
SAYI_FARKLI = "SAYI_FARKLI"
INCELEME = "İNCELEME_GEREKLİ"
STATUSES = [AYNI, BICIM, PDF_VAR, EXCEL_VAR, YANLIS_BOLUM, KOD_FARKLI, METIN_FARKLI, SAYI_FARKLI, INCELEME]

# Sistem Excel'inde "yok" anlamında kullanılan hücre değerleri (kod listesinde öğe sayılmaz)
EMPTY_MARKERS = {"yok", "-"}


@dataclass
class Row:
    durum: str
    tema: str
    ogrenme_ciktisi: str
    alan: str
    oge: str
    pdf_degeri: str
    excel_degeri: str
    excel_hucresi: str
    pdf_sayfa: str
    aciklama: str = ""


COLUMNS = {
    "durum": "Durum",
    "tema": "Tema (PDF)",
    "ogrenme_ciktisi": "Öğrenme çıktısı",
    "alan": "Alan / sütun",
    "oge": "Öğe",
    "pdf_degeri": "PDF değeri",
    "excel_degeri": "Excel değeri",
    "excel_hucresi": "Excel hücresi",
    "pdf_sayfa": "PDF sayfa",
    "aciklama": "Açıklama",
}


def _ws(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def text_status(pdf: str, excel: str) -> str:
    """AYNI: yalnızca boşluk/satır sonu miktarı farklı. SADECE_BİÇİM_FARKI: satır sonu tiresi, tire,
    boşluk yeri, büyük/küçük harf farkı. METİN_FARKLI: harf/noktalama/içerik farkı
    (ör. "Okuryazarlığı" / "Okuryazarlıği" METİN_FARKLI'dır)."""
    p, e = _ws(pdf), _ws(strip_placeholder(excel))
    if p == e:
        return AYNI
    nows = lambda t: re.sub(r"\s+", "", compare_key(t))
    kp, ke = nows(pdf), nows(strip_placeholder(excel))
    if kp == ke or tr_lower(kp) == tr_lower(ke):
        return BICIM
    return METIN_FARKLI


def _pages(f: TextField | None) -> str:
    return ", ".join(map(str, f.pages)) if f else ""


def _unit_name(u: Unit) -> str:
    return f"{u.context.text + ' | ' if u.context else ''}{u.title.text}".replace("\n", " ")


class Comparer:
    def __init__(self, res: ExtractionResult, xl: SystemExcel):
        self.res, self.xl = res, xl
        s = res.schema_
        self.lo_re = lo_code_regex(s.lo_prefix, s.lo_segment_types)
        self.loose_re = loose_lo_code_regex(s.lo_prefix, s.lo_segments)
        self.rows: list[Row] = []
        # ÖÇ düzeyi kod sütunlarının önekleri Excel'den öğrenilir (ör. "Erdem-Değer-Eylem Çerçevesi" -> {D})
        self.col_prefixes: dict[str, set[str]] = {}
        for t in xl.themes:
            for lo in t.los:
                for h, c in lo.columns.items():
                    for _, code, _ in code_items(c):
                        if code:
                            self.col_prefixes.setdefault(h, set()).add(parse_code(code).prefix)

    # ------------------------------------------------------------ yardımcılar
    def add(self, durum, u: Unit | None, lo: str, alan: str, oge: str, pdf: str, excel: str, cell: Cell | None, pages: str, note: str = ""):
        self.rows.append(
            Row(durum, _unit_name(u) if u else "", lo, alan, oge, pdf or "", strip_placeholder(excel) if excel else "", cell.address if cell else "", pages, note)
        )

    def lo_code_of(self, text: str) -> Code | None:
        m = self.lo_re.match(text) or self.loose_re.match(text)
        return parse_code(m.group(1).strip()) if m else None

    def match_units(self) -> dict[int, Unit]:
        """Excel teması -> PDF birimi: temadaki ÖÇ kodlarının çoğunluğunun bulunduğu birim."""
        where = {lo.code.key: u for u in self.res.units for lo in u.learning_outcomes}
        out: dict[int, Unit] = {}
        for i, t in enumerate(self.xl.themes):
            votes = Counter()
            for lo in t.los:
                c = self.lo_code_of(lo.cell.text)
                if c is not None and c.key in where:
                    votes[where[c.key].id] += 1
            if votes:
                uid = votes.most_common(1)[0][0]
                out[i] = next(u for u in self.res.units if u.id == uid)
        return out

    # ------------------------------------------------------------ akış
    def run(self) -> pd.DataFrame:
        matched = self.match_units()
        used_units = set()
        for i, t in enumerate(self.xl.themes):
            u = matched.get(i)
            if u is None:
                self.add(EXCEL_VAR, None, "", "Tema", t.cell.text.split("\n")[0], "", t.cell.raw, t.cell, "", "Excel temasının öğrenme çıktısı kodları PDF'de bulunamadı")
                continue
            if u.id in used_units:
                self.add(INCELEME, u, "", "Tema", "", u.title.text, t.cell.raw, t.cell, _pages(u.title), "Aynı PDF birimine birden fazla Excel teması eşleşti")
            used_units.add(u.id)
            self.compare_theme(t, u)
        for u in self.res.units:
            if u.id not in used_units:
                self.add(PDF_VAR, u, "", "Tema", "", u.title.text, "", None, _pages(u.title), "PDF'deki tema Excel'de yok")
        df = pd.DataFrame([asdict(r) for r in self.rows]).rename(columns=COLUMNS)
        if df.empty:
            df = pd.DataFrame(columns=list(COLUMNS.values()))
        return df

    def compare_theme(self, t: ExcelTheme, u: Unit):
        self.add(text_status(u.title.text, t.cell.raw), u, "", "Tema", "Başlık", u.title.text, t.cell.raw, t.cell, _pages(u.title))
        for h, cell in t.columns.items():
            self.compare_theme_column(u, h, cell)
        for h, lvl in self.xl.column_level.items():
            if lvl == "theme" and h not in t.columns:
                sec = section_for_header(u, h)
                if sec is not None and sec.content is not None:
                    self.add(PDF_VAR, u, "", h, "", sec.content.text, "", None, _pages(sec.content), "Excel hücresi boş")
        # öğrenme çıktıları
        pdf_los = {lo.code.key: lo for lo in u.learning_outcomes}
        xl_los: dict = {}
        unkeyed: list[ExcelLO] = []
        for xlo in t.los:
            c = self.lo_code_of(xlo.cell.text)
            if c is None:
                unkeyed.append(xlo)
            elif c.key in xl_los:
                self.add(INCELEME, u, c.normalized, "Öğrenme Çıktısı", "", "", xlo.cell.raw, xlo.cell, "", "Excel'de aynı öğrenme çıktısı kodu tekrarlı")
            else:
                xl_los[c.key] = xlo
        if len(t.los) != len(u.learning_outcomes):
            self.add(SAYI_FARKLI, u, "", "Öğrenme çıktısı sayısı", "", str(len(u.learning_outcomes)), str(len(t.los)), t.cell, _pages(u.title))
        only_pdf = [k for k in pdf_los if k not in xl_los]
        only_xl = [k for k in xl_los if k not in pdf_los]
        # kodu farklı ama başlığı aynı olan çiftler: KOD_FARKLI
        for kx in list(only_xl):
            xlo = xl_los[kx]
            for kp in list(only_pdf):
                lo = pdf_los[kp]
                xtitle = compare_key(strip_placeholder(xlo.cell.raw)[len(self.lo_code_of(xlo.cell.text).raw):])
                if norm_label(xtitle) == norm_label(lo.title.compare_key):
                    self.add(KOD_FARKLI, u, lo.code.normalized, "Öğrenme Çıktısı", "Kod", lo.code.raw, self.lo_code_of(xlo.cell.text).raw, xlo.cell, _pages(lo.title), "Başlık aynı, kod farklı")
                    only_xl.remove(kx)
                    only_pdf.remove(kp)
                    self.compare_lo(u, lo, xlo)
                    break
        for k in only_pdf:
            lo = pdf_los[k]
            self.add(PDF_VAR, u, lo.code.normalized, "Öğrenme Çıktısı", "", lo.header.text if lo.header else lo.code.raw, "", None, _pages(lo.title))
        for k in only_xl:
            xlo = xl_los[k]
            self.add(EXCEL_VAR, u, self.lo_code_of(xlo.cell.text).normalized, "Öğrenme Çıktısı", "", "", xlo.cell.raw, xlo.cell, "")
        for xlo in unkeyed:
            self.add(INCELEME, u, "", "Öğrenme Çıktısı", "", "", xlo.cell.raw, xlo.cell, "", "Excel hücresinde öğrenme çıktısı kodu okunamadı")
        for k, xlo in xl_los.items():
            if k in pdf_los:
                self.compare_lo(u, pdf_los[k], xlo)

    # ------------------------------------------------------------ tema düzeyi sütunlar
    def compare_theme_column(self, u: Unit, header: str, cell: Cell):
        sec = section_for_header(u, header)
        if sec is None:
            self.add(INCELEME, u, "", header, "", "", cell.raw, cell, "", "Excel sütunu PDF'deki bir bölümle eşleşmedi")
            return
        if sec.kind == SectionKind.APPLICATIONS:
            self.compare_applications(u, header, cell)
        elif sec.kind == SectionKind.DECLARATION:
            pdf = [(d.code, d.entry) for d in u.declarations.get(sec.path, [])]
            self.compare_code_list(u, "", header, cell, pdf, names_from_pdf=True)
        elif sec.content is not None and self._is_item_list(cell, sec.content.text):
            self.compare_items(u, header, cell, sec.content)
        else:
            pdf_text = sec.content.text if sec.content else ""
            st = text_status(pdf_text, cell.raw)
            note = ""
            if st == METIN_FARKLI:
                other = self._found_elsewhere(u, cell.raw, exclude=sec)
                if other:
                    st, note = YANLIS_BOLUM, f"Excel metni PDF'de '{other}' bölümünde"
            self.add(st, u, "", header, "", pdf_text, cell.raw, cell, _pages(sec.content), note)

    @staticmethod
    def _is_item_list(cell: Cell, pdf_text: str) -> bool:
        items = list_items(cell)
        return len(items) > 1 and all(len(x) <= 60 and not x.endswith(".") for x in items) and "," in pdf_text

    def compare_items(self, u: Unit, header: str, cell: Cell, content: TextField):
        """Virgül/satır listesi (ör. Disiplinler Arası İlişkiler): öğe kümeleri iki yönlü."""
        pdf_items = [x.strip() for x in re.sub(r"-\s*\n\s*", "", content.text).replace("\n", " ").split(",") if x.strip()]
        xl_items = list_items(cell)
        pk = {norm_label(x): x for x in pdf_items}
        xk = {norm_label(x): x for x in xl_items}
        for k, x in pk.items():
            if k in xk:
                self.add(AYNI if _ws(x) == _ws(xk[k]) else BICIM, u, "", header, x, x, xk[k], cell, _pages(content))
            else:
                self.add(PDF_VAR, u, "", header, x, x, "", cell, _pages(content))
        for k, x in xk.items():
            if k not in pk:
                self.add(EXCEL_VAR, u, "", header, x, "", x, cell, "")

    def compare_applications(self, u: Unit, header: str, cell: Cell):
        """Tek hücredeki uygulamalar metni ÖÇ kod satırlarından bloklara ayrılır ve blok blok karşılaştırılır."""
        blocks: dict = {}
        cur, buf = None, []
        text = strip_placeholder(cell.raw)
        pre = []
        for line in text.split("\n"):
            c = self.lo_code_of(line)
            if c is not None and not line[len((self.lo_re.match(line) or self.loose_re.match(line)).group(0)):].strip():
                if cur is not None:
                    blocks[cur.key] = (cur, "\n".join(buf).strip())
                cur, buf = c, []
            elif cur is None:
                pre.append(line)
            else:
                buf.append(line)
        if cur is not None:
            blocks[cur.key] = (cur, "\n".join(buf).strip())
        if "".join(pre).strip():
            self.add(INCELEME, u, "", header, "(kodsuz metin)", "", "\n".join(pre), cell, "", "Excel uygulama metninin başında bir ÖÇ koduna bağlı olmayan metin var")
        pdf_blocks = {b.code.key: b for b in u.applications if b.code is not None}
        for k, b in pdf_blocks.items():
            code = b.code.normalized
            if k not in blocks:
                self.add(PDF_VAR, u, code, header, "Uygulama bloğu", b.body.text if b.body else "", "", cell, _pages(b.body))
                continue
            xc, xt = blocks[k]
            if xc.raw.strip() != b.header.text.strip():
                self.add(text_status(b.header.text, xc.raw), u, code, header, "Blok başlığı (kod)", b.header.text, xc.raw, cell, _pages(b.header))
            self.add(text_status(b.body.text if b.body else "", xt), u, code, header, "Uygulama metni", b.body.text if b.body else "", xt, cell, _pages(b.body))
        for k, (xc, xt) in blocks.items():
            if k not in pdf_blocks:
                self.add(EXCEL_VAR, u, xc.normalized, header, "Uygulama bloğu", "", xt, cell, "")

    # ------------------------------------------------------------ ÖÇ düzeyi
    def compare_lo(self, u: Unit, lo, xlo: ExcelLO):
        code = lo.code.normalized
        pdf_header = lo.header.text if lo.header else lo.code.raw
        self.add(text_status(pdf_header, xlo.cell.raw), u, code, "Öğrenme Çıktısı", "Kod ve başlık", pdf_header, xlo.cell.raw, xlo.cell, _pages(lo.title))
        # süreç bileşenleri: sıraya göre eşleşir
        pc, xc = lo.components, xlo.components
        if len(pc) != len(xc):
            self.add(SAYI_FARKLI, u, code, "Süreç Bileşeni", "Bileşen sayısı", str(len(pc)), str(len(xc)), xlo.cell, _pages(lo.title))
        for i in range(max(len(pc), len(xc))):
            p = pc[i] if i < len(pc) else None
            x = xc[i] if i < len(xc) else None
            ptxt = (p.full.text if p and p.full else (p.text.text if p else ""))
            oge = (p.marker if p and p.marker else f"{i + 1}. bileşen")
            if p and x:
                self.add(text_status(ptxt, x.raw), u, code, "Süreç Bileşeni", oge, ptxt, x.raw, x, _pages(p.text))
            elif p:
                self.add(PDF_VAR, u, code, "Süreç Bileşeni", oge, ptxt, "", None, _pages(p.text))
            else:
                self.add(EXCEL_VAR, u, code, "Süreç Bileşeni", oge, "", x.raw, x, "")
        # ÖÇ düzeyi kod sütunları
        block = next((b for b in u.applications if b.code is not None and b.code.key == lo.code.key), None)
        for h, lvl in self.xl.column_level.items():
            if lvl != "lo":
                continue
            prefixes = self.col_prefixes.get(h, set())
            used = []
            seen = set()
            for c in (block.used_codes if block else []):
                if c.prefix in prefixes and c.key not in seen:
                    seen.add(c.key)
                    used.append((c, self._decl_entry(u, c)))
            used.sort(key=lambda ce: code_sort_key(ce[0]))
            cell = xlo.columns.get(h)
            self.compare_code_list(u, code, h, cell, used, names_from_pdf=False)

    @staticmethod
    def _decl_entry(u: Unit, c: Code) -> TextField | None:
        for ds in u.declarations.values():
            for d in ds:
                if d.code.key == c.key:
                    return d.entry
        return None

    def compare_code_list(self, u: Unit, lo_code: str, header: str, cell: Cell | None, pdf: list[tuple[Code, TextField | None]], names_from_pdf: bool):
        """Kod + ad karşılaştırması. PDF tarafında ad, kodun PDF'deki tanım girdisidir; kod PDF'de
        tanımlı değilse (ör. D3.1 kullanılmış, yalnızca D3 tanımlı) ad karşılaştırılamaz."""
        xl_items = [it for it in (code_items(cell) if cell else []) if norm_label(it[0]) not in EMPTY_MARKERS]
        xl: dict = {}
        for line, code, name in xl_items:
            if not code:
                self.add(INCELEME, u, lo_code, header, line, "", line, cell, "", "Excel satırında kod okunamadı")
                continue
            k = parse_code(code).key
            if k in xl:
                self.add(INCELEME, u, lo_code, header, code, "", line, cell, "", "Excel'de aynı kod tekrarlı")
                continue
            xl[k] = (line, code, name)
        pk = {c.key: (c, e) for c, e in pdf}
        for k, (c, entry) in pk.items():
            pages = _pages(entry) if entry else ""
            if k not in xl:
                self.add(PDF_VAR, u, lo_code, header, c.normalized, entry.text if entry else c.raw, "", cell, pages)
                continue
            line, code, name = xl[k]
            if entry is None:
                self.add(AYNI, u, lo_code, header, c.normalized, c.raw, line, cell, pages, "Kod eşleşti; ad PDF'de tanımlı değil, karşılaştırılamadı")
                continue
            pdf_name = re.sub(rf"^\s*{re.escape(entry.text.split()[0])}\s*", "", entry.text) if entry.text.split() else ""
            st = text_status(pdf_name, name)
            self.add(st, u, lo_code, header, c.normalized, entry.text, line, cell, pages, "" if st == AYNI else "Kod aynı; ad farklı" if st == METIN_FARKLI else "")
        for k, (line, code, name) in xl.items():
            if k not in pk:
                self.add(EXCEL_VAR, u, lo_code, header, code, "", line, cell, "")

    def _found_elsewhere(self, u: Unit, excel_raw: str, exclude) -> str | None:
        key = norm_label(compare_key(strip_placeholder(excel_raw)))
        if len(key) < 20:
            return None
        for s in u.sections:
            if s is exclude or s.content is None:
                continue
            if norm_label(s.content.compare_key) == key:
                return s.path or s.kind.value
        return None


def compare(res: ExtractionResult, xl: SystemExcel) -> pd.DataFrame:
    return Comparer(res, xl).run()


def summary(df: pd.DataFrame) -> pd.DataFrame:
    counts = df["Durum"].value_counts() if not df.empty else pd.Series(dtype=int)
    return pd.DataFrame({"Durum": STATUSES, "Adet": [int(counts.get(s, 0)) for s in STATUSES]})
