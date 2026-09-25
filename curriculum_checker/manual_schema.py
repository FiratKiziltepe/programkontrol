"""Program yapısını elle verme formu (otomatik algılama yetmediğinde ya da sonuç yanlış göründüğünde).

Kullanıcı PDF'de yazdığı gibi bir örnek tema/ünite başlığı ve bir örnek öğrenme çıktısı kodu verir; araç bunları
PDF'de arayarak başlık biçimini (anahtar kelime, renk) ve kod desenini (önek, segmentler) öğrenir. Boş bırakılan
alanlar otomatik algılanır. Her program için kod değiştirmeye gerek kalmaz.
"""
from __future__ import annotations

import re

import streamlit as st

from models import SchemaOverrides

STRUCT_AUTO, STRUCT_NONE, STRUCT_PAGES = "Otomatik bul", "Yapı/tanıtım sayfası yok", "Sayfa numaralarını gir"


def _parse_pages(text: str) -> list[int] | None:
    """"12-13, 15" -> [12, 13, 15]; geçersizse None."""
    pages: list[int] = []
    for part in re.split(r"[,\s]+", text.strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            return None
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if a < 1 or b < a:
            return None
        pages += list(range(a, b + 1))
    return pages or None


def overrides_form(key: str, defaults: SchemaOverrides | None = None, submit_label: str = "Bu bilgilerle analiz et") -> SchemaOverrides | None:
    """Formu gösterir; gönderilirse SchemaOverrides döner (boş alanlar None = otomatik)."""
    d = defaults or SchemaOverrides()
    with st.form(key):
        c1, c2 = st.columns(2)
        title = c1.text_input(
            "Örnek tema / ünite / öğrenme alanı başlığı",
            value=d.unit_title_example or "",
            placeholder="1. ÜNİTE: DİN HİZMETLERİ VE İLETİŞİM",
            help="Herhangi bir tema sayfasındaki başlığı PDF'de yazdığı gibi girin (\"1. TEMA: …\", \"2. ÖĞRENME ALANI: …\" "
            "ya da \"ÜNİTE 1: …\"). Araç bu başlığı PDF'de bulup diğer başlıkları aynı biçimden tanır. Boş: otomatik.",
        )
        code = c2.text_input(
            "Örnek öğrenme çıktısı kodu",
            value=d.lo_code_example or "",
            placeholder="HMU.11.1.1.",
            help="Bir öğrenme çıktısının kodunu PDF'de yazdığı gibi girin (ör. \"MAT.1.1.1.\", \"ARN.5.1.D.\"). "
            "Önek ve kod yapısı buradan öğrenilir. Boş: otomatik.",
        )
        c3, c4, c5 = st.columns([1.2, 1, 1])
        mode_default = STRUCT_AUTO if d.structure_pages is None else (STRUCT_NONE if d.structure_pages == [] else STRUCT_PAGES)
        modes = [STRUCT_AUTO, STRUCT_PAGES, STRUCT_NONE]
        mode = c3.radio("Program yapısı (tanıtım) sayfası", modes, index=modes.index(mode_default), help=(
            "Tema sayfasının küçültülmüş örneğinin bulunduğu \"… Öğretim Programının Yapısı\" sayfası. "
            "\"Yok\" seçilirse bölüm başlıkları tema sayfalarından öğrenilir; PDF'de böyle bir sayfa varsa tema sanılabilir."
        ))
        pages_txt = c4.text_input(
            "Yapı sayfaları",
            value=", ".join(map(str, d.structure_pages)) if d.structure_pages else "",
            placeholder="12-13",
            help="PDF görüntüleyicideki sayfa numarası (1'den başlar); ör. \"12-13\". Yalnızca \"Sayfa numaralarını gir\" seçiliyse kullanılır.",
        )
        start = c5.number_input(
            "İlk tema/ünite sayfası (0 = otomatik)",
            min_value=0,
            value=int(d.data_start_page or 0),
            step=1,
            help="Gerçek tema sayfalarının başladığı PDF sayfa numarası. Öncesindeki sayfalar (tanıtım, tablolar) tema sayılmaz.",
        )
        sent = st.form_submit_button(submit_label, type="primary")
    if not sent:
        return None
    structure: list[int] | None = None
    if mode == STRUCT_NONE:
        structure = []
    elif mode == STRUCT_PAGES:
        structure = _parse_pages(pages_txt)
        if structure is None:
            st.error("Yapı sayfalarını \"12-13\" ya da \"12, 13\" biçiminde girin.")
            return None
    return SchemaOverrides(
        unit_title_example=title.strip() or None,
        lo_code_example=code.strip() or None,
        structure_pages=structure,
        data_start_page=int(start) or None,
    )


def detected_defaults(res) -> SchemaOverrides:
    """Başarılı analizden forma ön değerler: otomatik algılananlar (kullanıcı yalnızca yanlışı düzeltir)."""
    s = res.schema_
    title = res.units[0].title.text.replace("\n", " ") if res.units else None
    code = next((lo.code.raw for u in res.units for lo in u.learning_outcomes), None)
    return SchemaOverrides(unit_title_example=title, lo_code_example=code, structure_pages=list(s.structure_pages), data_start_page=s.data_start_page)
