"""Öğretim Programı PDF → Excel doğrulama ve karşılaştırma arayüzü.

Çalıştırma:  streamlit run app.py

Akış:
1. PDF Analizi       – PDF yüklenir, içerik çıkarılır, tablolar gösterilir, Excel indirilir.
2. PDF Kontrolleri   – sayı, kod ve bölüm kontrollerinin bulguları.
3. Gemini Doğrulama  – isteğe bağlı: tema sayfalarının görüntüsü TARAYICIDAN Gemini'ye gönderilir (API anahtarı
                       sunucuya gelmez); yerleşim (başlıklar, ÖÇ/uygulama kodları) çıkarımla karşılaştırılır.
                       Gemini metni çıkarıma girmez.
4. Excel Karşılaştırma – sistemden indirilen Excel yüklenir, iki yönlü karşılaştırılır.
5. Rapor             – özet ve indirilebilir rapor.
6. Tablo Karşılaştırma – sistem Excel'i ↔ PDF Excel'i hücre hücre yan yana; eksikler PDF metin katmanından,
                       isteğe bağlı Gemini ile (PDF metin katmanında doğrulanarak) tamamlanır; inceleme raporu (Word).
"""
from __future__ import annotations

import hashlib
import io
import os
import tempfile
import traceback

import fitz
import pandas as pd
import streamlit as st

from compare import AYNI, BICIM, KAPSAM_DISI, STATUSES, compare, summary
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
import manual_schema
import scope_panel
from models import SchemaOverrides
import gemini_verify
from gemini_component import gemini_browser
import grid_tab
from schema_detect import SchemaError
from validators import analyze_pdf

st.set_page_config(page_title="Öğretim Programı Kontrol", page_icon="📘", layout="wide")

TESTED_PYMUPDF = "1.23.26"  # requirements.txt ile aynı tutulmalı
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
    "KAPSAM_DIŞI": "Kapsam dışı",
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


def _expected(v) -> str:
    return "?" if v is None else str(v)


def _save_upload(upload, suffix: str) -> str:
    data = upload.getvalue()
    digest = hashlib.sha1(data).hexdigest()[:12]
    path = os.path.join(tempfile.gettempdir(), f"curriculum_{digest}{suffix}")
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)
    return path


@st.cache_data(show_spinner=False, max_entries=8)
def _analyze_cached(path: str, digest: str, overrides_json: str = ""):
    ov = SchemaOverrides.model_validate_json(overrides_json) if overrides_json else None
    return analyze_pdf(path, ov)


def _run_analysis(path: str, name: str, digest: str, ov: SchemaOverrides | None = None) -> None:
    """Analizi çalıştırır. Yapı tanınamazsa elle yapı formu için durumu saklar; başarılıysa sonucu kaydeder."""
    with st.status("PDF analiz ediliyor…", expanded=True) as status:
        st.write("Metin ve yerleşim bilgisi çıkarılıyor, program yapısı keşfediliyor…")
        try:
            result = _analyze_cached(path, digest, ov.model_dump_json() if ov is not None and not ov.is_empty() else "")
        except SchemaError as e:
            status.update(label="Analiz tamamlanamadı", state="error")
            st.session_state["schema_fail"] = {"path": path, "name": name, "digest": digest, "error": str(e)}
            return
        except Exception as e:  # beklenmeyen hata: ayrıntı gösterilir, uygulama çökmez
            status.update(label="Analiz tamamlanamadı", state="error")
            st.error(f"Beklenmeyen bir hata oluştu: {type(e).__name__}: {e}")
            with st.expander("Hata ayrıntısı (geliştirici için)"):
                st.code(traceback.format_exc())
            return
        status.update(label="Analiz tamamlandı", state="complete", expanded=False)
    st.session_state.pop("schema_fail", None)
    st.session_state.update(
        res=result, pdf_name=name, pdf_digest=digest, pdf_path=path, overrides=ov, cmp=None, xl_name=None, gemini=None, gv_payload=None
    )
    st.rerun()


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
    if fitz.VersionBind != TESTED_PYMUPDF:
        st.warning(
            f"PyMuPDF {fitz.VersionBind} kullanılıyor; araç {TESTED_PYMUPDF} ile doğrulandı. Yeni sürümler bazı "
            "fontlarda noktalı İ harfini I okuyabilir. Streamlit Cloud'da Python 3.12 seçin (requirements.txt)."
        )
    res = st.session_state.get("res")
    if res is not None:
        st.success(f"Analiz edilen PDF: **{st.session_state['pdf_name']}**")
        st.metric("PDF genel durum", STATUS_TR.get(res.status.value, res.status.value))
    if st.session_state.get("cmp") is not None:
        st.info(f"Karşılaştırılan Excel: **{st.session_state['xl_name']}**")

tab_pdf, tab_checks, tab_gemini, tab_cmp, tab_report, tab_grid = st.tabs(
    # "1." Markdown'da numaralı liste sayılmasın diye kaçışlanır
    ["1\\. PDF Analizi", "2\\. PDF Kontrolleri", "3\\. Gemini Doğrulama", "4\\. Excel Karşılaştırma", "5\\. Rapor", "6\\. Tablo Karşılaştırma"]
)

# ---------------------------------------------------------------- 1. PDF Analizi

with tab_pdf:
    upload = st.file_uploader("Öğretim programı PDF'si", type=["pdf"], key="pdf_upload")
    if st.button("PDF'yi Analiz Et", type="primary", disabled=upload is None):
        path = _save_upload(upload, ".pdf")
        st.session_state.pop("schema_fail", None)
        _run_analysis(path, upload.name, os.path.basename(path))

    fail = st.session_state.get("schema_fail")
    if fail is not None:
        # Otomatik algılama yetmedi: yapı bilgileri elle verilir (her program için kod değiştirmeye gerek kalmaz)
        st.error(f"**{fail['name']}**: PDF'de öğretim programı yapısı otomatik tanınamadı — {fail['error']}")
        st.markdown(
            "Aşağıdaki bilgileri PDF'de **yazdığı gibi** girin; araç bunları PDF'de arayıp başlık ve kod biçimini öğrenir. "
            "Emin olmadığınız alanı boş bırakın (otomatik algılanır)."
        )
        ov = manual_schema.overrides_form("manual_schema_fail", st.session_state.get("fail_overrides"))
        if ov is not None:
            st.session_state["fail_overrides"] = ov
            _run_analysis(fail["path"], fail["name"], fail["digest"], ov)
            st.rerun()  # buraya yalnızca başarısız analizde gelinir: yeni hata mesajı gösterilir

    res = st.session_state.get("res")
    if res is None:
        st.info("Başlamak için bir PDF yükleyip **PDF'yi Analiz Et** düğmesine basın.")
    else:
        fdf = findings_df(res)
        sev = fdf["Önem"].value_counts() if not fdf.empty else {}
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Genel durum", STATUS_TR.get(res.status.value, res.status.value))
        exp_units = res.expected_unit_count if res.expected_lo_total is not None else None
        c2.metric("Tema / ünite", f"{len(res.units)}/{_expected(exp_units)}", help="Bulunan / süre tablosunda beklenen (? = tablo yok veya birimlerle eşleşmedi)")
        c3.metric("Öğrenme çıktısı", f"{res.extracted_lo_total}/{_expected(res.expected_lo_total)}", help="Çıkarılan / süre tablosunda beklenen (? = tablo yok veya birimlerle eşleşmedi)")
        c4.metric("Hata", int(sev.get("FAIL", 0)))
        c5.metric("İnceleme gerekli", int(sev.get("NEEDS_REVIEW", 0)))

        if not res.schema_.structure_pages:
            st.warning("Program yapısı/tanıtım sayfası bulunamadı; bölüm başlıkları ve kod deseni tema sayfalarından öğrenildi. Sonuçları inceleyin.")
        s = res.schema_
        with st.expander(
            f"Program yapısı: anahtar kelime **{s.unit_keyword}**, ÖÇ kodu **{s.lo_prefix}.{'.'.join('N' if t == 'n' else 'X' for t in s.lo_segment_types)}**, "
            f"yapı sayfaları **{', '.join(map(str, s.structure_pages)) or 'yok'}**, ilk tema sayfası **{s.data_start_page}**"
            + (" · elle verildi" if st.session_state.get("overrides") else "")
            + " — yanlışsa elle düzeltin"
        ):
            st.caption("Otomatik algılanan değerler aşağıda. Yanlış olanı düzeltip yeniden analiz edin; boş bıraktığınız alan otomatik algılanır.")
            ov = manual_schema.overrides_form(
                "manual_schema_fix", st.session_state.get("overrides") or manual_schema.detected_defaults(res), "Yeniden analiz et"
            )
            if ov is not None and st.session_state.get("pdf_path"):
                _run_analysis(st.session_state["pdf_path"], st.session_state["pdf_name"], st.session_state["pdf_digest"], ov)
                st.rerun()  # buraya yalnızca başarısız analizde gelinir: elle yapı formu üstte gösterilir

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

# ---------------------------------------------------------------- 3. Gemini Doğrulama

GEMINI_STATUS_TR = {
    "UYUMLU": "Uyumlu",
    "YALNIZCA_PDF_CIKARIMI": "Çıkarımda var, Gemini görmedi",
    "YALNIZCA_GEMINI": "Gemini gördü, çıkarımda yok",
    "HATA": "Gemini hatası",
}
GEMINI_COLORS = {"UYUMLU": "PASS", "YALNIZCA_PDF_CIKARIMI": "NEEDS_REVIEW", "YALNIZCA_GEMINI": "NEEDS_REVIEW", "HATA": "INFO"}


def _gemini_df(report) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Sayfa": c.page,
                "Birim": c.unit_id or "",
                "Tür": gemini_verify.KIND_TR.get(c.kind, c.kind),
                "Durum": GEMINI_STATUS_TR.get(c.status, c.status),
                "PDF çıkarımı": c.extracted or "",
                "Gemini'nin gördüğü (yalnızca inceleme için)": c.gemini or "",
                "_renk": GEMINI_COLORS.get(c.status, "INFO"),
            }
            for c in report.checks
        ],
        columns=["Sayfa", "Birim", "Tür", "Durum", "PDF çıkarımı", "Gemini'nin gördüğü (yalnızca inceleme için)", "_renk"],
    )


with tab_gemini:
    res = st.session_state.get("res")
    if res is None:
        st.info("Önce **1. PDF Analizi** sekmesinde bir PDF analiz edin.")
    else:
        st.caption(
            "İsteğe bağlıdır. Seçilen temaların sayfa görüntüleri **tarayıcınızdan doğrudan** Google Gemini API'sine "
            "gönderilir; API anahtarınız yalnızca tarayıcınızda kalır, sunucuya gönderilmez ve kaydedilmez. Gemini'den "
            "sayfadaki tema başlıklarını, bölüm başlıklarını, öğrenme çıktısı ve uygulama bloğu kodlarını listelemesi "
            "istenir; bu liste PDF'den çıkarılan yapıyla karşılaştırılır, uyuşmayan yerler **İnceleme gerekli** olur. "
            "Gemini'nin yazdığı metin çıkarıma, Excel'e veya karşılaştırmaya **girmez**."
        )
        units = {u.id: f"{u.id} — {(u.context.text + ' | ') if u.context else ''}{u.title.text}".replace("\n", " ") for u in res.units}
        chosen = st.multiselect("Doğrulanacak temalar", list(units), default=list(units)[:1], format_func=units.get)
        n_pages = len(gemini_verify.unit_pages(res, chosen))
        st.caption(f"{n_pages} sayfa (her sayfa ayrı bir Gemini isteği).")
        if st.button("Sayfaları hazırla", disabled=not chosen):
            with st.spinner("Sayfa görüntüleri hazırlanıyor…"):
                pages = gemini_verify.unit_pages(res, chosen)
                st.session_state["gv_payload"] = {
                    "run_id": hashlib.sha1(f"{st.session_state['pdf_digest']}|{sorted(pages)}|{os.urandom(4).hex()}".encode()).hexdigest()[:12],
                    "units": chosen,
                    "pages": gemini_verify.page_images(res.source, pages),
                    "prompt": gemini_verify.PROMPT,
                    "schema": gemini_verify.RESPONSE_SCHEMA,
                    "model": gemini_verify.DEFAULT_MODEL,
                }
        payload = st.session_state.get("gv_payload")
        browser = gemini_browser(payload)
        out = browser.result if browser is not None else None
        if payload and out and out.get("run_id") == payload["run_id"] and st.session_state.get("gv_done") != payload["run_id"]:
            results = {int(k): v for k, v in (out.get("results") or {}).items()}
            st.session_state["gemini"] = gemini_verify.build_report(res, out.get("model") or "", payload["units"], results)
            st.session_state["gv_done"] = payload["run_id"]

        report = st.session_state.get("gemini")
        if report is not None:
            gdf = _gemini_df(report)
            counts = gdf["Durum"].value_counts() if not gdf.empty else {}
            for col, code in zip(st.columns(4), GEMINI_STATUS_TR):
                col.metric(GEMINI_STATUS_TR[code], int(counts.get(GEMINI_STATUS_TR[code], 0)))
            only_diff = st.checkbox("Yalnızca uyuşmayanları göster", value=True)
            view = gdf[gdf["Durum"] != GEMINI_STATUS_TR["UYUMLU"]] if only_diff else gdf
            st.caption(f"Model: {report.model} — {len(report.pages)} sayfa, {len(view)} satır gösteriliyor")
            st.dataframe(
                style_by(view, "_renk"),
                hide_index=True,
                width="stretch",
                height=460,
                column_config={
                    "_renk": None,
                    "PDF çıkarımı": st.column_config.TextColumn("PDF çıkarımı", width="large"),
                    "Gemini'nin gördüğü (yalnızca inceleme için)": st.column_config.TextColumn("Gemini'nin gördüğü (yalnızca inceleme için)", width="large"),
                },
            )
            buf = io.BytesIO()
            gdf.drop(columns=["_renk"]).to_excel(buf, index=False, sheet_name="Gemini Doğrulama")
            st.download_button(
                "Gemini doğrulama raporunu indir (Excel)",
                data=buf.getvalue(),
                file_name=f"{os.path.splitext(st.session_state['pdf_name'])[0]}_gemini_dogrulama.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

# ---------------------------------------------------------------- 4. Excel Karşılaştırma

with tab_cmp:
    res = st.session_state.get("res")
    if res is None:
        st.info("Önce **1. PDF Analizi** sekmesinde bir PDF analiz edin.")
    else:
        # Birden çok Excel (sınıf sınıf) yüklenebilir; karşılaştırma kapsamı panelde belirlenir (6. sekmeyle ortak)
        xl, xl_names, xl_key = scope_panel.upload_system_excels("xl_upload")
        cmp_scope = scope_panel.scope_panel(res, xl, st.session_state["pdf_digest"], xl_key, "tab4") if xl is not None else None
        if st.button("Karşılaştır", type="primary", disabled=xl is None):
            with st.spinner("Karşılaştırılıyor…"):
                cmp_df = compare(res, xl, cmp_scope)
            st.session_state.update(cmp=cmp_df, xl_name=xl_names)
            st.rerun()

        cmp_df = st.session_state.get("cmp")
        if cmp_df is not None:
            summ = summary(cmp_df)
            counts = dict(zip(summ["Durum"], summ["Adet"]))
            for chunk in (STATUSES[:5], STATUSES[5:]):
                for c, s in zip(st.columns(5), chunk):
                    c.metric(CMP_TR[s], int(counts.get(s, 0)))

            default = [s for s in STATUSES if s not in (AYNI, BICIM, KAPSAM_DISI)]
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

# ---------------------------------------------------------------- 5. Rapor

with tab_report:
    res = st.session_state.get("res")
    if res is None:
        st.info("Önce **1. PDF Analizi** sekmesinde bir PDF analiz edin.")
    else:
        st.subheader("PDF")
        fdf = findings_df(res)
        st.write(
            f"**{st.session_state['pdf_name']}** — genel durum: **{STATUS_TR.get(res.status.value)}**, "
            f"tema/ünite {len(res.units)}, "
            f"öğrenme çıktısı {res.extracted_lo_total} (süre tablosunda beklenen: {_expected(res.expected_lo_total)})."
        )
        if not fdf.empty:
            st.dataframe(
                fdf.groupby(["Önem", "Kontrol"]).size().reset_index(name="Adet").sort_values(["Önem", "Adet"], ascending=[True, False]),
                hide_index=True,
                width="stretch",
            )
        cmp_df = st.session_state.get("cmp")
        if cmp_df is None:
            st.info("Karşılaştırma raporu için **4. Excel Karşılaştırma** sekmesinde sistem Excel'ini karşılaştırın.")
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

# ---------------------------------------------------------------- 6. Tablo Karşılaştırma

with tab_grid:
    res = st.session_state.get("res")
    if res is None:
        st.info("Önce **1. PDF Analizi** sekmesinde bir PDF analiz edin.")
    else:
        grid_tab.render(res, st.session_state["pdf_name"], st.session_state["pdf_digest"])
