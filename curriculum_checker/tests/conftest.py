import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SAMPLES = ROOT.parent / "samples"
MUZIK_PDF = SAMPLES / "müzik.pdf"


@pytest.fixture(scope="session")
def muzik():
    if not MUZIK_PDF.exists():
        pytest.skip("samples/müzik.pdf yok")
    from validators import analyze_pdf

    return analyze_pdf(str(MUZIK_PDF))


@pytest.fixture(scope="session")
def muzik_doc():
    if not MUZIK_PDF.exists():
        pytest.skip("samples/müzik.pdf yok")
    from pdf_extract import extract_spans

    return extract_spans(str(MUZIK_PDF))
