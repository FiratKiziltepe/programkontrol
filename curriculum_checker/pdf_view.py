"""Tüm sekmelerde ortak "PDF'de göster": tablo hücresine tıklayınca PDF sayfası, ilgili yer sarı işaretli açılır.

Konumlar pdf_locate.Locator ile deterministik bulunur; bu modül yalnızca sayfayı çizer ve diyaloğu gösterir.
"""
from __future__ import annotations

import base64
from typing import Callable

import fitz
import streamlit as st

from pdf_extract import extract_spans
from pdf_locate import Loc, Locator

# İşaret rengi: tüm ekranlarda ve indirilen HTML'de aynı
FILL = (1.0, 0.88, 0.1)
STROKE = (0.9, 0.62, 0.0)
FILL_OPACITY = 0.42
HINT = "Hücreye tıklayınca PDF'nin ilgili sayfası, yer **sarı** işaretli açılır."

_PENDING = "_pdfloc_pending"


@st.cache_resource(show_spinner=False, max_entries=4)
def _locator(path: str, digest: str, _res) -> Locator:
    return Locator(_res, extract_spans(path))


def locator(res) -> Locator:
    return _locator(res.source, st.session_state.get("pdf_digest", res.source), res)


def _pad(r) -> fitz.Rect:
    return fitz.Rect(r) + (-1.5, -1.0, 1.5, 1.0)


@st.cache_data(show_spinner=False, max_entries=256)
def render(path: str, page: int, rects: tuple = (), zoom: float = 1.6, fmt: str = "png", quality: int = 80, clip: tuple | None = None) -> bytes:
    """Sayfa görüntüsü; rects sarı yarı saydam kutu olarak çizilir (belge kaydedilmez). clip: yalnızca bu bölge."""
    with fitz.open(path) as d:
        pg = d[page - 1]
        for r in rects:
            pg.draw_rect(_pad(r), color=STROKE, fill=FILL, fill_opacity=FILL_OPACITY, width=0.8, overlay=True)
        pix = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=fitz.Rect(clip) if clip else None)
        return pix.tobytes("jpg", jpg_quality=quality) if fmt == "jpg" else pix.tobytes("png")


def page_image_b64(path: str, page: int, zoom: float = 1.3, quality: int = 65) -> str:
    return base64.b64encode(render(path, page, (), zoom, "jpg", quality)).decode("ascii")


def _show_loc(path: str, loc: Loc) -> None:
    if loc.note:
        st.warning(loc.note)
    pages = loc.all_pages()
    if not pages:
        return
    if len(pages) > 1:
        st.caption("Sayfalar: " + ", ".join(f"{p}" + (f" ({len(loc.rects.get(p, []))} işaret)" if loc.rects.get(p) else "") for p in pages))
    marked = [p for p in pages if loc.rects.get(p)]
    unmarked = [p for p in pages if not loc.rects.get(p)]
    if marked and unmarked:  # işaretli sayfalar önde; işaretsizler (ör. bloğun başladığı önceki sayfa) kapalı
        with st.expander("İşaret olmayan sayfalar: " + ", ".join(map(str, unmarked))):
            for p in unmarked:
                st.markdown(f"**Sayfa {p}** · işaret yok")
                st.image(render(path, p), width="stretch")
        pages = marked
    for p in pages:
        rs = tuple(tuple(r) for r in loc.rects.get(p, []))
        st.markdown(f"**Sayfa {p}**" + (f" · {len(rs)} işaret" if rs else " · işaret yok"))
        clip = _focus(path, p, rs)
        if clip is None:
            st.image(render(path, p, rs), width="stretch")
            continue
        st.image(render(path, p, rs, 2.2, clip=clip), width="stretch", caption="İşaretli bölgenin yakın görünümü")
        with st.expander(f"Sayfa {p} tamamı"):
            st.image(render(path, p, rs), width="stretch")


def _focus(path: str, page: int, rects: tuple) -> tuple | None:
    """İşaretlerin bulunduğu yatay şerit (sayfa genişliğinde); işaret yoksa ya da sayfanın çoğunu kaplıyorsa None."""
    if not rects:
        return None
    with fitz.open(path) as d:
        w, h = d[page - 1].rect.width, d[page - 1].rect.height
    y0, y1 = min(r[1] for r in rects) - 45, max(r[3] for r in rects) + 45
    if y1 - y0 > h * 0.6:
        return None
    return (0.0, max(0.0, y0), w, min(h, y1))


@st.dialog("PDF'de göster", width="large")
def _dialog(path: str, items: list[tuple[str, Loc]]) -> None:
    if len(items) > 1:
        labels = [lbl for lbl, _ in items]
        i = st.selectbox("Gösterilecek öğe", range(len(items)), format_func=lambda k: labels[k])
    else:
        i = 0
    label, loc = items[i]
    st.markdown(f"**{label}**" if label else f"**{loc.title}**")
    if label and loc.title and loc.title != label:
        st.caption(loc.title)
    _show_loc(path, loc)


def show(res, items: Loc | list[tuple[str, Loc]] | None) -> None:
    if items is None:
        return
    if isinstance(items, Loc):
        items = [(items.title, items)]
    if items:
        _dialog(res.source, items)


def _on_select(key: str) -> Callable[[], None]:
    def cb() -> None:
        cells = st.session_state[key].selection.get("cells") or []
        if cells:
            st.session_state[_PENDING] = (key, tuple(cells[0]))

    return cb


def clickable_dataframe(data, key: str, resolve: Callable[[int, str], Loc | list[tuple[str, Loc]] | None], res, **kwargs):
    """st.dataframe + tek hücre seçimi: seçilen hücre resolve(satır konumu, sütun adı) ile PDF konumuna çevrilip
    diyalogda gösterilir. Satır konumu, verilen tablodaki konumdur (kullanıcı sıralaması etkilemez)."""
    st.dataframe(data, key=key, on_select=_on_select(key), selection_mode="single-cell", **kwargs)
    pending = st.session_state.get(_PENDING)
    if pending and pending[0] == key:
        del st.session_state[_PENDING]
        row, col = pending[1]
        show(res, resolve(int(row), str(col)))
