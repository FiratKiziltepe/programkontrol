"""Karşılaştırma kapsamı: sistem Excel'i yalnızca bazı sınıfları içerdiğinde PDF'in hangi temalarının
karşılaştırılacağı.

- PDF temaları bağlamlarına (ör. "5. SINIF (A1.1)", "I. DÜZEY") göre gruplanır; bağlamı olmayan temalar tek
  grupta toplanır.
- Excel temaları PDF temalarıyla öğrenme çıktısı kodları üzerinden eşleşir (sınıf yazısına bakılmaz).
- Varsayılan kapsam: Excel'de en az bir teması eşleşen grupların bütün temaları. Hiç eşleşme yoksa kapsam
  bütün PDF'tir (hiçbir şey gizlenmez).
Kapsam dışı temalar fark sayılmaz; karşılaştırmada tek satırla "kapsam dışı" olarak bildirilir.
"""
from __future__ import annotations

from dataclasses import dataclass

from compare import Comparer
from excel_import import SystemExcel
from models import ExtractionResult

NO_CONTEXT = "(bağlamsız temalar)"


@dataclass
class UnitGroup:
    name: str
    unit_ids: list[str]
    first_page: int
    last_page: int


def unit_groups(res: ExtractionResult) -> list[UnitGroup]:
    groups: dict[str, UnitGroup] = {}
    for u in res.units:
        name = u.context.text.replace("\n", " ") if u.context else NO_CONTEXT
        g = groups.get(name)
        if g is None:
            groups[name] = UnitGroup(name, [u.id], u.pages[0], u.pages[-1])
        else:
            g.unit_ids.append(u.id)
            g.first_page, g.last_page = min(g.first_page, u.pages[0]), max(g.last_page, u.pages[-1])
    return list(groups.values())


def matched_unit_ids(res: ExtractionResult, xl: SystemExcel) -> set[str]:
    """Excel temalarıyla ÖÇ kodları üzerinden eşleşen PDF temaları."""
    return {u.id for u in Comparer(res, xl).match_units().values()}


def default_scope(res: ExtractionResult, xl: SystemExcel) -> set[str]:
    matched = matched_unit_ids(res, xl)
    if not matched:
        return {u.id for u in res.units}
    return {uid for g in unit_groups(res) if set(g.unit_ids) & matched for uid in g.unit_ids}
