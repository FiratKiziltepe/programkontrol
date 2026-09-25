"""Sistem Excel'i yükleme (birden çok dosya) ve karşılaştırma kapsamı paneli.

"4. Excel Karşılaştırma" ve "6. Tablo Karşılaştırma" sekmelerinde ortak kullanılır. Kapsam seçimi aynı PDF ve
aynı Excel dosyaları için iki sekmede ortaktır.
"""
from __future__ import annotations

import hashlib
import os
import tempfile

import pandas as pd
import streamlit as st

from excel_import import SystemExcel, merge_system_excels, read_system_excel
from scope import default_scope, matched_unit_ids, unit_groups


@st.cache_data(show_spinner=False, max_entries=16)
def _read(path: str) -> SystemExcel:
    return read_system_excel(path)


def upload_system_excels(key: str) -> tuple[SystemExcel | None, str, str]:
    """Bir ya da birden çok sistem Excel'i yükletir ve birleştirir. Dönüş: (birleşik Excel, adlar, anahtar)."""
    ups = st.file_uploader(
        "Müfredat sisteminden indirilen Excel (sınıf sınıf indirdiyseniz hepsini birlikte seçebilirsiniz)",
        type=["xlsx"],
        accept_multiple_files=True,
        key=key,
    )
    if not ups:
        return None, "", ""
    parts, digests = [], []
    for up in ups:
        data = up.getvalue()
        digest = hashlib.sha1(data).hexdigest()[:12]
        path = os.path.join(tempfile.gettempdir(), f"curriculum_sys_{digest}.xlsx")
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(data)
        try:
            parts.append((up.name, _read(path)))
        except ValueError as e:
            st.error(f"{up.name} okunamadı: {e}")
            return None, "", ""
        digests.append(digest)
    names = ", ".join(n for n, _ in parts)
    import copy

    # birleştirme hücre adreslerine dosya adı ekler; önbellekteki nesneler değişmesin
    merged = merge_system_excels([(n, copy.deepcopy(x)) for n, x in parts]) if len(parts) > 1 else parts[0][1]
    return merged, names, "+".join(sorted(digests))


def scope_panel(res, xl: SystemExcel, pdf_digest: str, xl_key: str, tab: str) -> set[str]:
    """Kapsam panelini gösterir ve seçili PDF tema kimliklerini döndürür.

    Seçim (gruplar + tema bazında çıkarılanlar) aynı PDF ve aynı Excel dosyaları için sekmeler arasında ortaktır;
    bileşen anahtarları sekmeye özeldir (tab)."""
    groups = unit_groups(res)
    matched = matched_unit_ids(res, xl)
    auto = default_scope(res, xl)
    sk = f"scope::{pdf_digest}::{xl_key}"
    shared_groups, shared_excl = sk + "::groups", sk + "::excluded"
    units = {u.id: u for u in res.units}
    if shared_groups not in st.session_state:
        st.session_state[shared_groups] = [g.name for g in groups if set(g.unit_ids) & auto]
    if shared_excl not in st.session_state:
        st.session_state[shared_excl] = []
    gkey = f"{sk}::{tab}::groups"

    def sync_groups():
        st.session_state[shared_groups] = list(st.session_state[gkey])
        for k in [k for k in st.session_state if k.startswith(sk + "::") and k.endswith("::groups") and k not in (gkey, shared_groups)]:
            del st.session_state[k]  # diğer sekmenin bileşeni ortak değerden yeniden kurulur

    with st.container(border=True):
        st.markdown("**Karşılaştırma kapsamı**")
        st.caption(
            "Excel'deki temalar PDF temalarıyla öğrenme çıktısı kodları üzerinden eşleştirildi. Varsayılan olarak Excel'de "
            "teması bulunan sınıf/düzey grupları karşılaştırılır; kapsam dışı temalar fark sayılmaz, raporda "
            "\"kapsam dışı\" diye tek satırla belirtilir. Gerekirse değiştirin (seçim 4. ve 6. sekmede ortaktır)."
        )
        overview = pd.DataFrame(
            [
                {
                    "Grup": g.name,
                    "PDF teması": len(g.unit_ids),
                    "Excel'de eşleşen": sum(1 for uid in g.unit_ids if uid in matched),
                    "PDF sayfaları": f"{g.first_page}-{g.last_page}",
                }
                for g in groups
            ]
        )
        st.dataframe(overview, hide_index=True, width="stretch")
        if gkey not in st.session_state:
            st.session_state[gkey] = list(st.session_state[shared_groups])
        chosen = st.multiselect("Karşılaştırılacak gruplar", [g.name for g in groups], key=gkey, on_change=sync_groups)
        in_groups = [uid for g in groups if g.name in chosen for uid in g.unit_ids]
        excluded = set(st.session_state[shared_excl])
        with st.expander("Tema bazında düzelt", expanded=bool(excluded)):
            df = pd.DataFrame(
                [
                    {
                        "Karşılaştır": uid not in excluded,
                        "Tema": units[uid].title.text.replace("\n", " "),
                        "Grup": units[uid].context.text.replace("\n", " ") if units[uid].context else "",
                        "Excel'de": "var" if uid in matched else "yok",
                        "Sayfalar": f"{units[uid].pages[0]}-{units[uid].pages[-1]}",
                    }
                    for uid in in_groups
                ]
            )
            state = hashlib.sha1(("|".join(chosen) + "#" + "|".join(sorted(excluded))).encode()).hexdigest()[:10]
            ekey = f"{sk}::{tab}::units::{state}"

            def sync_units(ids=tuple(in_groups), key=ekey):
                ex = set(st.session_state[shared_excl])
                for idx, change in st.session_state[key].get("edited_rows", {}).items():
                    if "Karşılaştır" in change:
                        uid = ids[int(idx)]
                        (ex.discard if change["Karşılaştır"] else ex.add)(uid)
                st.session_state[shared_excl] = sorted(ex)

            if not df.empty:
                st.data_editor(
                    df,
                    hide_index=True,
                    width="stretch",
                    disabled=["Tema", "Grup", "Excel'de", "Sayfalar"],
                    key=ekey,
                    on_change=sync_units,
                )
        selected = {uid for uid in in_groups if uid not in set(st.session_state[shared_excl])}
        n_out = len(units) - len(selected)
        not_matched_in = [uid for uid in selected if uid not in matched]
        msg = f"Kapsam: **{len(selected)}** tema karşılaştırılacak, **{n_out}** tema kapsam dışı."
        if not_matched_in:
            msg += f" Kapsamdaki {len(not_matched_in)} tema Excel'de yok (fark olarak raporlanır)."
        st.markdown(msg)
    return selected
