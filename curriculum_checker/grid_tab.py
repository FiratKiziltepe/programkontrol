"""'6. Tablo Karşılaştırma' sekmesi: sistem Excel'i ↔ PDF Excel'i yan yana, Gemini ile doğrulanmış tamamlama,
inceleme raporu. Diğer sekmelerden bağımsızdır (kendi Excel yüklemesi ve oturum anahtarları vardır)."""
from __future__ import annotations

import json
import os

import streamlit as st

import gemini_verify
import grid_compare as gc
import review_report as rr
import scope_panel
from gemini_tasks_component import gemini_tasks
from grid_table_component import grid_table
from pdf_extract import extract_spans

K = "gt_"  # oturum anahtarı öneki


@st.cache_resource(show_spinner=False, max_entries=4)
def _doc(path: str):
    return extract_spans(path)


def _b64_page(pdf_path: str, page: int) -> str:
    import base64

    return base64.b64encode(gemini_verify.render_page(pdf_path, page)).decode("ascii")


def _bump():
    st.session_state[K + "ver"] = st.session_state.get(K + "ver", 0) + 1


def render(res, pdf_name: str, pdf_digest: str) -> None:
    st.caption(
        "Sistemden indirilen Excel ile PDF'den dönüştürülen Excel **hücre hücre, yan yana** karşılaştırılır. "
        "Farklar deterministik olarak belirlenir. PDF tarafında boş kalan hücreler önce PDF'nin metin katmanında "
        "aranır; isteğe bağlı olarak Gemini, farklı/eksik hücrelerin sayfalarını inceleyip metni gösterir ve bu metin "
        "PDF metin katmanında **birebir doğrulanırsa** PDF'deki ham metin tabloya alınır."
    )
    # oturum PDF değişince sıfırla
    if st.session_state.get(K + "pdf") != pdf_digest:
        for k in [k for k in st.session_state if k.startswith(K)]:
            del st.session_state[k]
        st.session_state[K + "pdf"] = pdf_digest

    # Birden çok Excel (sınıf sınıf) yüklenebilir; karşılaştırma kapsamı panelde belirlenir (4. sekmeyle ortak)
    xl, xl_names, xl_key = scope_panel.upload_system_excels(K + "upload")
    grid_scope = scope_panel.scope_panel(res, xl, pdf_digest, xl_key, "tab6") if xl is not None else None
    if st.button("Karşılaştırma tablosunu oluştur", type="primary", disabled=xl is None, key=K + "build"):
        with st.spinner("Tablo oluşturuluyor, eksik hücreler PDF metin katmanında aranıyor…"):
            grid = gc.build_grid(res, xl, grid_scope)
            n = gc.complete_from_text_layer(grid, _doc(res.source), res.schema_.label_colors)
        keep = (K + "pdf", K + "upload", K + "build")
        for k in [k for k in st.session_state if k.startswith(K) and k not in keep]:
            del st.session_state[k]
        st.session_state.update({K + "grid": grid, K + "xl_name": xl_names, K + "text_layer": n})
        _bump()

    grid = st.session_state.get(K + "grid")
    if grid is None:
        st.info("Sistem Excel'ini yükleyip **Karşılaştırma tablosunu oluştur** düğmesine basın.")
        return

    counts = gc.grid_counts(grid)
    m = st.columns(6)
    m[0].metric("Farklı", counts[gc.FARKLI])
    m[1].metric("Yalnızca sistemde", counts[gc.SADECE_SISTEM])
    m[2].metric("Yalnızca PDF'de", counts[gc.SADECE_PDF])
    m[3].metric("Biçim farkı", counts[gc.BICIM])
    m[4].metric("Aynı", counts[gc.AYNI])
    m[5].metric(
        "Tamamlanan",
        counts["tamamlanan_metin_katmani"] + counts["tamamlanan_gemini"],
        help=f"PDF metin katmanından: {counts['tamamlanan_metin_katmani']} · Gemini + metin katmanı: {counts['tamamlanan_gemini']}"
        f" · Gemini önerisi doğrulanamayan: {counts['gemini_dogrulanamayan']}",
    )
    for n in grid.notes:
        st.warning(n)
    if grid.out_of_scope:
        st.caption(f"Kapsam dışı bırakılan {len(grid.out_of_scope)} PDF teması tabloda yok ve fark sayılmadı (raporda listelenir).")

    ver = st.session_state.get(K + "ver", 0)
    if st.session_state.get(K + "payload_ver") != ver:
        st.session_state[K + "payload"] = gc.grid_payload(grid)
        st.session_state[K + "payload_ver"] = ver
    grid_table(st.session_state[K + "payload"], key=K + "table")

    base = os.path.splitext(pdf_name)[0]
    st.download_button(
        "Nihai karşılaştırma tablosunu indir (Excel)",
        data=rr.build_grid_xlsx(grid),
        file_name=f"{base}_nihai_karsilastirma.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=K + "dl_xlsx",
    )

    # ------------------------------------------------------------ Gemini ile doğrulanmış tamamlama
    st.subheader("Gemini ile PDF'den kontrol")
    targets = gc.gemini_targets(grid)
    st.caption(
        f"Farklı veya PDF'de eksik {len(targets)} hücre var. Gemini bu hücrelerin sayfalarında alanın metnini "
        "gösterir; metin PDF metin katmanında birebir bulunursa PDF'deki ham metin tabloya girer, bulunamazsa "
        "tabloya girmez ve **Gemini?** olarak işaretlenir."
    )
    if st.button("Gemini isteklerini hazırla", disabled=not targets, key=K + "prep"):
        with st.spinner("Sayfa görüntüleri hazırlanıyor…"):
            tasks = gc.gemini_tasks(grid, res.source, targets, _b64_page)
        for t in tasks:
            t["label"] = f"Sayfa {t['page']}"
        st.session_state[K + "gpayload"] = {
            "run_id": os.urandom(6).hex(),
            "model": gemini_verify.DEFAULT_MODEL,
            "button": "Gemini ile sayfaları kontrol et",
            "ready": f"{len(tasks)} sayfa ({len(targets)} hücre) hazır.",
            "tasks": tasks,
        }
    gp = st.session_state.get(K + "gpayload")
    if gp:
        out = gemini_tasks(gp, key=K + "gemini").result
        if out and out.get("run_id") == gp["run_id"] and st.session_state.get(K + "gdone") != gp["run_id"]:
            stats = gc.apply_gemini(grid, _doc(res.source), res.schema_.label_colors, out.get("results") or {}, json.loads)
            st.session_state[K + "gdone"] = gp["run_id"]
            st.session_state[K + "gstats"] = stats
            _bump()
            st.rerun()
    stats = st.session_state.get(K + "gstats")
    if stats:
        st.success(
            f"Gemini sonucu: {stats['verified']} hücre PDF metin katmanında doğrulanarak güncellendi, "
            f"{stats['unverified']} öneri doğrulanamadı (tabloya alınmadı), {stats['errors']} sayfada hata."
        )

    # ------------------------------------------------------------ inceleme raporu
    st.subheader("İnceleme raporu")
    xl_name = st.session_state.get(K + "xl_name", "")
    md = rr.python_report(grid, pdf_name, xl_name)
    with st.expander("Python raporu (deterministik)", expanded=False):
        st.markdown(md)
    c1, c2 = st.columns(2)
    c1.download_button(
        "Raporu indir (Word)",
        data=rr.build_docx(grid, md, pdf_name, xl_name),
        file_name=f"{base}_inceleme_raporu.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key=K + "dl_docx",
    )
    if c2.button("Gemini ile raporlaştır", key=K + "rep_prep"):
        st.session_state[K + "rpayload"] = {
            "run_id": os.urandom(6).hex(),
            "model": gemini_verify.DEFAULT_MODEL,
            "button": "Raporu Gemini ile yaz",
            "ready": "Python raporu Gemini'ye gönderilmeye hazır (yalnızca rapor metni gönderilir).",
            "tasks": [{"id": "report", "label": "Rapor", "text": rr.gemini_report_prompt(md), "system": rr.GEMINI_REPORT_SYSTEM}],
        }
    rp = st.session_state.get(K + "rpayload")
    if rp:
        out = gemini_tasks(rp, key=K + "gemini_report").result
        if out and out.get("run_id") == rp["run_id"]:
            r = (out.get("results") or {}).get("report", {})
            if "error" in r:
                st.error(f"Gemini raporu yazamadı: {r['error']}")
            elif r.get("ok"):
                st.session_state[K + "gemini_md"] = r["ok"]
    gmd = st.session_state.get(K + "gemini_md")
    if gmd:
        st.info("Aşağıdaki anlatım Gemini ile düzenlenmiştir; kesin değerler Word dosyasındaki ek fark tablosundadır.")
        with st.container(border=True):
            st.markdown(gmd)
        st.download_button(
            "Gemini raporunu indir (Word)",
            data=rr.build_docx(grid, gmd, pdf_name, xl_name, gemini_edited=True),
            file_name=f"{base}_inceleme_raporu_gemini.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary",
            key=K + "dl_gdocx",
        )
