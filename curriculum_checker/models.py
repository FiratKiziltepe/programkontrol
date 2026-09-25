"""Veri modelleri.

Kural: Buradaki hiçbir alan PDF'de olmayan müfredat metni taşımaz. Metin alanları
(TextField) yalnızca PDF span'larından birleştirilir ve kaynak span kimliklerini saklar.
Rapor mesajları (Finding.message) araç çıktısıdır, müfredat metni değildir.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Span(BaseModel):
    id: str  # "P{sayfa}_S{sıra}"
    page: int  # 1 tabanlı
    text: str
    bbox: tuple[float, float, float, float]
    font: str
    size: float
    color: int
    flags: int
    block: int
    line: int

    @property
    def x0(self) -> float:
        return self.bbox[0]

    @property
    def y0(self) -> float:
        return self.bbox[1]

    @property
    def x1(self) -> float:
        return self.bbox[2]

    @property
    def y1(self) -> float:
        return self.bbox[3]

    @property
    def yc(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2


class TextField(BaseModel):
    """PDF'den birebir alınan metin.

    text: satırlar '\\n' ile birleştirilmiş ham metin (tireler korunur).
    compare_key: YALNIZCA eşleştirme için; satır sonu tire+kırılım, tireler ve
    çoklu boşluklar yok sayılır. Gösterimde kullanılmaz.
    """

    text: str
    pages: list[int]
    source_spans: list[str]
    compare_key: str


class Code(BaseModel):
    raw: str  # PDF'de geçtiği şekliyle, asla değiştirilmez
    normalized: str  # yalnızca eşleştirme/gösterim için
    prefix: str
    numbers: list[int]  # yalnızca sayısal segmentler
    segments: list[str] = Field(default_factory=list)  # tüm segmentler (ör. ["5", "1", "D"])

    @property
    def key(self) -> tuple[str, tuple[str, ...]]:
        return (self.prefix, tuple(self.segments))


class ProcessComponent(BaseModel):
    marker: str  # "a)", "b)", "ç)" ...
    letter: str
    text: TextField
    full: Optional[TextField] = None  # işaretiyle birlikte PDF'deki ham metin ("a) Temaya ...")


class LearningOutcome(BaseModel):
    code: Code
    title: TextField
    components: list[ProcessComponent] = Field(default_factory=list)
    header: Optional[TextField] = None  # kod + başlık, PDF'deki ham haliyle


class ApplicationBlock(BaseModel):
    code: Optional[Code]  # None: bir öğrenme çıktısı koduna bağlanamayan metin
    header: Optional[TextField]
    body: Optional[TextField]
    used_codes: list[Code] = Field(default_factory=list)
    malformed_codes: list[str] = Field(default_factory=list)  # ham metin, ör. "KB2,4", "SDB"


class DeclaredCode(BaseModel):
    code: Code
    entry: TextField
    parent: Optional[str] = None  # parantez içindeki alt tanımın üst kodu (normalize)
    standard_format: bool = True  # "E1.1. Ad" biçiminde mi (değilse CODE_FORMAT_ANOMALY)


class SectionKind(str, Enum):
    UNIT_DESCRIPTION = "unit_description"  # başlıksız giriş paragrafı
    GROUP = "group"  # içeriksiz üst başlık (ör. FARKLILAŞTIRMA)
    DECLARATION = "declaration"  # kod tanımlayan bölüm (Değerler, Eğilimler ...)
    LEARNING_OUTCOMES = "learning_outcomes"
    APPLICATIONS = "applications"
    OTHER = "other"


class Section(BaseModel):
    label: Optional[TextField]  # None yalnızca başlıksız giriş paragrafı için
    label_norm: Optional[str]
    group_label: Optional[TextField] = None
    path: str  # "ÜST > alt" (PDF metinleriyle); başlıksız bölüm için ""
    kind: SectionKind = SectionKind.OTHER
    rank: int = 0
    content: Optional[TextField] = None
    content_rows: list[TextField] = Field(default_factory=list)


class Unit(BaseModel):
    id: str
    context: Optional[TextField]  # ör. "1. SINIF"
    title: TextField  # ör. "1. TEMA: MÜZİK DİLİ"
    subtitle: Optional[TextField] = None  # başlık bloğundaki ek satır (ör. "Alt Temalar: ...")
    order: Optional[int]
    name: Optional[str]  # başlıkta ':' sonrasındaki PDF metni
    pages: list[int]
    sections: list[Section] = Field(default_factory=list)
    learning_outcomes: list[LearningOutcome] = Field(default_factory=list)
    applications: list[ApplicationBlock] = Field(default_factory=list)
    declarations: dict[str, list[DeclaredCode]] = Field(default_factory=dict)  # path -> kodlar


class LabelDef(BaseModel):
    text: str  # yapı sayfasındaki metin
    norm: str
    parts: list[str] = Field(default_factory=list)  # bileşik başlığın parçaları (norm), ör. ["ilkeler", "anahtarkavramlar"]
    rank: int
    color: int
    source_spans: list[str]


class ProgramSchema(BaseModel):
    structure_pages: list[int]
    structure_heading: TextField
    unit_keyword: str
    unit_title_color: int
    unit_title_colors: list[int] = Field(default_factory=list)  # başlık rengi + ona çok yakın tonlar
    body_color: int
    body_colors: list[int] = Field(default_factory=list)  # gövde rengi + ona çok yakın tonlar
    label_colors: list[int]
    labels: list[LabelDef]
    lo_prefix: str
    lo_segments: int
    lo_segment_types: list[str] = Field(default_factory=list)  # "n": sayı, "a": harf (ör. ARN.5.1.D)
    lo_example: TextField
    data_start_page: int


class ExpectedRow(BaseModel):
    table_index: int
    order: Optional[int]
    name: Optional[TextField]
    lo_count_raw: Optional[str]
    lo_count: Optional[int]
    hours: Optional[int]
    is_total: bool = False


class ExpectedLoListColumn(BaseModel):
    """Birim bazında öğrenme çıktısı kodu listesi (ör. Afet s.12 "sınırlı öğrenme çıktıları" tablosu)."""
    order: Optional[int]
    name: Optional[TextField]
    codes: list[TextField]
    unparsed: list[TextField] = Field(default_factory=list)  # kod olarak okunamayan satırlar (NEEDS_REVIEW)


class TableRole(str, Enum):
    SUMMARY = "SUMMARY"  # beklenen sayıların esas alındığı süre tablosu
    ALTERNATIVE = "ALTERNATIVE"  # aynı başlıklı, daha az ders saatli (sınırlı) süre tablosu
    LO_LIST = "LO_LIST"  # birim -> öğrenme çıktısı kodları listesi


class ExpectedTable(BaseModel):
    index: int
    page: int
    title: Optional[TextField]
    rows: list[ExpectedRow]
    role: TableRole = TableRole.SUMMARY
    lo_columns: list[ExpectedLoListColumn] = Field(default_factory=list)


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAIL = "FAIL"


SEVERITY_ORDER = {Severity.INFO: 0, Severity.WARNING: 1, Severity.NEEDS_REVIEW: 2, Severity.FAIL: 3}


class Finding(BaseModel):
    severity: Severity
    check: str  # ör. LO_COUNT_MISMATCH, SECTION_LEAKAGE, USED_NOT_DECLARED
    unit_id: Optional[str] = None
    message: str
    details: dict = Field(default_factory=dict)


class Status(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"  # geçer, uyarı var
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAIL = "FAIL"


class ExcludedRegion(BaseModel):
    heading: Optional[TextField]
    pages: list[int]
    span_count: int
    source_spans: list[str] = Field(default_factory=list)


class CodeCheck(BaseModel):
    category: str  # tanım bölümünün path'i
    declared: list[str]
    used: list[str]  # bu kategoriye eşleşen kullanılan kodlar (raw normalize)
    matched: list[str]
    declared_not_used: list[str]


class UnitReport(BaseModel):
    unit_id: str
    title: str
    context: Optional[str]
    expected_lo: Optional[int]
    extracted_lo: int
    expected_hours: Optional[int]
    extracted_hours: Optional[int]
    code_checks: list[CodeCheck] = Field(default_factory=list)
    used_not_declared: list[str] = Field(default_factory=list)
    status: Status = Status.PASS


class ExtractionResult(BaseModel):
    source: str
    page_count: int
    schema_: ProgramSchema = Field(alias="schema")
    expected_tables: list[ExpectedTable]
    units: list[Unit]
    excluded_regions: list[ExcludedRegion]
    findings: list[Finding] = Field(default_factory=list)
    unit_reports: list[UnitReport] = Field(default_factory=list)
    expected_unit_count: Optional[int] = None
    expected_lo_total: Optional[int] = None
    extracted_lo_total: int = 0
    status: Status = Status.NEEDS_REVIEW

    model_config = {"populate_by_name": True}
