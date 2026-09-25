"""Öğretim Programı PDF → Excel doğrulama ve karşılaştırma arayüzü.

Çalıştırma:  streamlit run app.py

Akış:
1. PDF Analizi       – PDF yüklenir, içerik çıkarılır, tablolar gösterilir, Excel indirilir.
2. PDF Kontrolleri   – sayı, kod ve bölüm kontrollerinin bulguları.
3. Excel Karşılaştırma – sistemden indirilen Excel yüklenir, iki yönlü karşılaştırılır.
4. Rapor             – özet ve indirilebilir rapor.
"""
from __future__ import annotations

import hashlib
import os
import tempfile

import pandas as pd
import streamlit as st

from compare import AYNI, BICIM, STATUSES, compare, summary
from excel_export import (
    RED,
    STATUS_COLORS,
    build_comparison_excel,
    build_pdf_excel,
    code_checks_df,
    findings_df,
    los_df,
    sections_df,
    units_df,
)
from excel_import import read_system_excel
from schema_detect import SchemaError
from validators import analyze_pdf

st.set_page_config(page_title="Öğretim Programı Kontrol", page_icon="📘", layout="wide")

SEVERITY_ORDER = ["FAIL", "NEEDS_REVIEW", "WARNING", "INFO"]
SEVERITY_TR = {"FAIL": "Hata", "NEEDS_REVIEW": "İnceleme gerekli", "WARNING": "Uyarı", "INFO": "Bilgi"}
STATUS_TR = {"PASS": "Geçti", "WARNING": "Uyarılarla geçti", "NEEDS_REVIEW": "İnceleme gerekli", "FAIL": "Hata"}
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
}
TEXT_COLS = {"Metin", "ÖÇ başlığı", "Bileşen metni", "PDF değeri", "Excel değeri", "Açıklama", "Ayrıntı"}


def col_config(df: pd.DataFrame) -> dict:
    """Uzun metin sütunlarını geniş, diğerlerini dar gösterir."""
    return {c: st.column_config.TextColumn(c, width="large" if c in TEXT_COLS else "small") for c in df.columns}


def _color(value: str) -> str:
    return "#" + STATUS_COLORS.get(str(value), RED)


def style_by(df: pd.DataFrame, col: str):
    """Satırı durum/önem sütununa göre renklendirir (PRD renkleri)."""
    if df.empty or col not in df.columns:
        return df

    def row_style(r):
        return [f"background-color: {_color(r[col])}; color: #1f1f1f"] * len(r)

    return df.style.apply(row_style, axis=1)


def _save_upload(upload, suffix: str) -> str:
    data = upload.getvalue()
    digest = hashlib.sha1(data).hexdigest()[:12]
    path = os.path.join(tempfile.gettempdir(), f"curriculum_{digest}{suffix}")
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)
    return path


@st.cache_data(show_spinner=False, max_entries=8)
def _analyze_cached(path: str, digest: str):
    return analyze_pdf(path)


@st.cache_data(show_spinner=False, max_entries=8)
def _pdf_excel_cached(digest: str, _res) -> bytes:
    return build_pdf_excel(_res)


# ---------------------------------------------------------------- kenar çubuğu

with st.sidebar:
    st.header("Öğretim Programı Kontrol")
    st.caption(
        "1) PDF'yi yükleyin ve analiz edin. İçerik ve sorunlar tablolar halinde gösterilir; "
        "PDF'den üretilen Excel indirilebilir.\n\n"
        "2) Ardından müfredat sisteminden indirilen Excel'i yükleyip karşılaştırın."
    )
    res = st.session_state.get("res")
    if res is not None:
        st.success(f"Analiz edilen PDF: **{st.session_state['pdf_name']}**")
        st.metric("PDF genel durum", STATUS_TR.get(res.status.value, res.status.value))
    if st.session_state.get("cmp") is not None:
        st.info(f"Karşılaştırılan Excel: **{st.session_state['xl_name']}**")

tab_pdf, tab_checks, tab_cmp, tab_report = st.tabs(
    # "1." Markdown'da numaralı liste sayılmasın diye kaçışlanır
    ["1\\. PDF Analizi", "2\\. PDF Kontrolleri", "3\\. Excel Karşılaştırma", "4\\. Rapor"]
)

# ---------------------------------------------------------------- 1. PDF Analizi

with tab_pdf:
    upload = st.file_uploader("Öğretim programı PDF'si", type=["pdf"], key="pdf_upload")
    if st.button("PDF'yi Analiz Et", type="primary", disabled=upload is None):
        path = _save_upload(upload, ".pdf")
        digest = os.path.basename(path)
        with st.status("PDF analiz ediliyor…", expanded=True) as status:
            st.write("Metin ve yerleşim bilgisi çıkarılıyor, program yapısı keşfediliyor…")
            try:
                result = _analyze_cached(path, digest)
            except SchemaError as e:
                status.update(label="Analiz tamamlanamadı", state="error")
                st.error(f"Program yapısı bulunamadı: {e}")
                result = None
            else:
                status.update(label="Analiz tamamlandı", state="complete", expanded=False)
        if result is not None:
            st.session_state.update(res=result, pdf_name=upload.name, pdf_digest=digest, cmp=None, xl_name=None)
            st.rerun()

    res = st.session_state.get("res")
    if res is None:
        st.info("Başlamak için bir PDF yükleyip **PDF'yi Analiz Et** düğmesine basın.")
    else:
        fdf = findings_df(res)
        sev = fdf["Önem"].value_counts() if not fdf.empty else {}
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Genel durum", STATUS_TR.get(res.status.value, res.status.value))
        c2.metric("Tema / ünite", f"{len(res.units)}/{res.expected_unit_count}", help="Bulunan / özet tablosunda beklenen")
        c3.metric("Öğrenme çıktısı", f"{res.extracted_lo_total}/{res.expected_lo_total}", help="Çıkarılan / özet tablosunda beklenen")
        c4.metric("Hata", int(sev.get("FAIL", 0)))
        c5.metric("İnceleme gerekli", int(sev.get("NEEDS_REVIEW", 0)))

        st.subheader("Temalar / üniteler")
        st.dataframe(style_by(units_df(res), "Durum"), hide_index=True, width="stretch")

        units = {u.id: f"{u.id} — {(u.context.text + ' | ') if u.context else ''}{u.title.text}".replace("\n", " ") for u in res.units}
        choice = st.selectbox("İçeriğini görmek istediğiniz tema", ["Tümü", *units], format_func=lambda k: units.get(k, "Tüm temalar"))
        uid = None if choice == "Tümü" else choice
        view = st.radio("Görünüm", ["Bölümler", "Öğrenme çıktıları"], horizontal=True)
        table = los_df(res, uid) if view == "Öğrenme çıktıları" else sections_df(res, uid)
        if uid is not None:
            table = table.drop(columns=["Birim", "Tema"])  # tek tema seçiliyken tekrar eden sütunlar
        st.dataframe(table, hide_index=True, width="stretch", height=520, column_config=col_config(table))

        st.download_button(
            "PDF'den üretilen Excel'i indir",
            data=_pdf_excel_cached(st.session_state["pdf_digest"], res),
            file_name=f"{os.path.splitext(st.session_state['pdf_name'])[0]}_pdf_cikarim.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help="1. sayfa sistem Excel'iyle aynı düzendedir; diğer sayfalarda tüm bölümler, öğrenme çıktıları ve bulgular vardır.",
        )

# ---------------------------------------------------------------- 2. PDF Kontrolleri

with tab_checks:
    res = st.session_state.get("res")
    if res is None:
        st.info("Önce **1. PDF Analizi** sekmesinde bir PDF analiz edin.")
    else:
        fdf = findings_df(res)
        st.subheader("Sayı kontrolleri")
        st.dataframe(style_by(units_df(res), "Durum"), hide_index=True, width="stretch")

        st.subheader("Bulgular")
        if fdf.empty:
            st.success("Bulgu yok.")
        else:
            f1, f2, f3 = st.columns([1, 2, 1])
            sev_sel = f1.multiselect(
                "Önem", SEVERITY_ORDER, default=["FAIL", "NEEDS_REVIEW"], format_func=lambda s: SEVERITY_TR.get(s, s)
            )
            chk_sel = f2.multiselect("Kontrol", sorted(fdf["Kontrol"].unique()))
            unit_sel = f3.multiselect("Birim", sorted(u for u in fdf["Birim"].unique() if u))
            view = fdf[fdf["Önem"].isin(sev_sel)] if sev_sel else fdf
            if chk_sel:
                view = view[view["Kontrol"].isin(chk_sel)]
            if unit_sel:
                view = view[view["Birim"].isin(unit_sel)]
            st.caption(f"{len(view)} / {len(fdf)} bulgu gösteriliyor")
            st.dataframe(style_by(view, "Önem"), hide_index=True, width="stretch", height=420)

        st.subheader("Kod kontrolleri (tanımlanan ↔ uygulamalarda kullanılan)")
        st.caption("Alan becerileri kod kontrolü dışındadır.")
        st.dataframe(code_checks_df(res), hide_index=True, width="stretch", height=360)

        if res.excluded_regions:
            with st.expander("Tema dışı bırakılan bölgeler"):
                st.dataframe(
                    pd.DataFrame(
                        [
                            {"Başlık": r.heading.text if r.heading else "(başlıksız / sayfa notu)", "Sayfalar": ", ".join(map(str, r.pages)), "Span sayısı": r.span_count}
                            for r in res.excluded_regions
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )

# ---------------------------------------------------------------- 3. Excel Karşılaştırma

with tab_cmp:
    res = st.session_state.get("res")
    if res is None:
        st.info("Önce **1. PDF Analizi** sekmesinde bir PDF analiz edin.")
    else:
        xl_upload = st.file_uploader("Müfredat sisteminden indirilen Excel", type=["xlsx"], key="xl_upload")
        if st.button("Karşılaştır", type="primary", disabled=xl_upload is None):
            path = _save_upload(xl_upload, ".xlsx")
            try:
                with st.spinner("Karşılaştırılıyor…"):
                    xl = read_system_excel(path)
                    cmp_df = compare(res, xl)
            except ValueError as e:
                st.error(f"Excel okunamadı: {e}")
            else:
                st.session_state.update(cmp=cmp_df, xl_name=xl_upload.name)
                st.rerun()

        cmp_df = st.session_state.get("cmp")
        if cmp_df is not None:
            summ = summary(cmp_df)
            counts = dict(zip(summ["Durum"], summ["Adet"]))
            for chunk in (STATUSES[:5], STATUSES[5:]):
                for c, s in zip(st.columns(5), chunk):
                    c.metric(CMP_TR[s], int(counts.get(s, 0)))

            default = [s for s in STATUSES if s not in (AYNI, BICIM)]
            durum_sel = st.multiselect("Durum", STATUSES, default=default, format_func=CMP_TR.get)
            g2, g3 = st.columns(2)
            alan_sel = g2.multiselect("Alan / sütun", sorted(cmp_df["Alan / sütun"].unique()))
            tema_sel = g3.multiselect("Tema", sorted(t for t in cmp_df["Tema (PDF)"].unique() if t))
            q = st.text_input("Ara (öğrenme çıktısı kodu, öğe veya metin)")
            view = cmp_df
            if durum_sel:
                view = view[view["Durum"].isin(durum_sel)]
            if alan_sel:
                view = view[view["Alan / sütun"].isin(alan_sel)]
            if tema_sel:
                view = view[view["Tema (PDF)"].isin(tema_sel)]
            if q:
                mask = view.apply(lambda r: q.lower() in " ".join(map(str, r.values)).lower(), axis=1)
                view = view[mask]
            st.caption(f"{len(view)} / {len(cmp_df)} satır gösteriliyor")
            st.dataframe(style_by(view, "Durum"), hide_index=True, width="stretch", height=560, column_config=col_config(view))

# ---------------------------------------------------------------- 4. Rapor

with tab_report:
    res = st.session_state.get("res")
    if res is None:
        st.info("Önce **1. PDF Analizi** sekmesinde bir PDF analiz edin.")
    else:
        st.subheader("PDF")
        fdf = findings_df(res)
        st.write(
            f"**{st.session_state['pdf_name']}** — genel durum: **{STATUS_TR.get(res.status.value)}**, "
            f"tema/ünite {len(res.units)} / {res.expected_unit_count}, "
            f"öğrenme çıktısı {res.extracted_lo_total} / {res.expected_lo_total}."
        )
        if not fdf.empty:
            st.dataframe(
                fdf.groupby(["Önem", "Kontrol"]).size().reset_index(name="Adet").sort_values(["Önem", "Adet"], ascending=[True, False]),
                hide_index=True,
                width="stretch",
            )
        cmp_df = st.session_state.get("cmp")
        if cmp_df is None:
            st.info("Karşılaştırma raporu için **3. Excel Karşılaştırma** sekmesinde sistem Excel'ini karşılaştırın.")
        else:
            st.subheader("Excel karşılaştırması")
            summ = summary(cmp_df)
            st.dataframe(style_by(summ, "Durum"), hide_index=True, width="content")
            st.dataframe(
                cmp_df.groupby(["Alan / sütun", "Durum"]).size().reset_index(name="Adet"),
                hide_index=True,
                width="stretch",
            )
            st.download_button(
                "Karşılaştırma raporunu indir (Excel)",
                data=build_comparison_excel(res, cmp_df, summ),
                file_name=f"{os.path.splitext(st.session_state['pdf_name'])[0]}_karsilastirma.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )
