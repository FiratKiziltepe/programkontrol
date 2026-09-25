"""Gemini ile layout doğrulama arayüzü (bu aşamada devre dışı).

Gemini yalnızca span kimlikleri üzerinden karar verebilir (hangi span başlık, hangi
span hangi bölüme ait); hiçbir zaman metin üretmez/düzeltmez. Şu an çağrı yapılmaz:
belirsiz durumlar NEEDS_REVIEW olarak raporlanır.
"""
from __future__ import annotations

from models import Span

ENABLED = False


def verify_page_layout(page: int, spans: list[Span], candidate_labels: list[str]) -> dict | None:
    """Beklenen dönüş: {"label_span_ids": [...], "assignments": {span_id: label_span_id}}.

    Devre dışıyken None döner; çağıran taraf NEEDS_REVIEW üretmelidir.
    """
    if not ENABLED:
        return None
    raise NotImplementedError("Gemini entegrasyonu bu aşamada yok")
