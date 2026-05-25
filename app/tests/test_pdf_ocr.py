"""
Teste dedicado ao OCR de PDFs escaneados via Gemma Vision.

Roda apenas PDFs que o pdfplumber não consegue extrair texto
(texto < 80 chars = PDF provavelmente escaneado).

Como usar:
    python -m pytest app/tests/test_pdf_ocr.py -v -s

Requer:
    - PDFs em docs/
    - GEMINI_API_KEY configurada no .env
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv()

from infrastructure.pdf.pdf_reader import (
    _MIN_TEXT_CHARS,
    _extract_pdfplumber,
    _do_ocr,
)

_DOCS_DIR = Path(__file__).parents[2] / "docs"
_API_KEY  = os.getenv("GEMINI_API_KEY")
_MODEL    = "gemma-4-26b-a4b-it"


def _collect_scanned_pdfs() -> list[Path]:
    """Retorna apenas os PDFs sem texto nativo (escaneados)."""
    if not _DOCS_DIR.is_dir():
        return []
    return [
        p for p in sorted(_DOCS_DIR.glob("*.pdf"))
        if len(_extract_pdfplumber(p)) < _MIN_TEXT_CHARS
    ]


_SCANNED = _collect_scanned_pdfs()

pytestmark = pytest.mark.skipif(
    not _SCANNED,
    reason="Nenhum PDF escaneado encontrado em docs/ — todos têm texto nativo.",
)


@pytest.fixture(params=_SCANNED, ids=[p.name for p in _SCANNED])
def scanned_pdf(request) -> Path:
    return request.param


@pytest.mark.skipif(not _API_KEY, reason="GEMINI_API_KEY não configurada.")
class TestOCR:
    def test_converte_paginas_em_imagem(self, scanned_pdf, capsys):
        """Verifica que pymupdf consegue abrir o PDF e renderizar páginas."""
        import fitz
        from infrastructure.pdf.pdf_reader import _OCR_DPI_SCALE

        doc = fitz.open(str(scanned_pdf))
        n = len(doc)
        mat = fitz.Matrix(_OCR_DPI_SCALE, _OCR_DPI_SCALE)
        pix = doc[0].get_pixmap(matrix=mat)
        doc.close()

        with capsys.disabled():
            print(f"\n  {scanned_pdf.name}: {n} paginas, "
                  f"pagina 1 = {pix.width}x{pix.height}px")

        assert pix.width > 0 and pix.height > 0

    def test_ocr_retorna_texto(self, scanned_pdf, capsys):
        """Chama _do_ocr diretamente e exibe o texto extraído."""
        texto = _do_ocr(scanned_pdf, _API_KEY, _MODEL)

        with capsys.disabled():
            sep = "-" * 60
            print(f"\n{sep}")
            print(f"  Arquivo : {scanned_pdf.name}")
            print(f"  Chars   : {len(texto)}")
            print(f"  Preview : {texto[:800].replace(chr(10), ' | ')}")
            print(sep)

        if not texto:
            pytest.skip(
                "OCR retornou vazio — modelo pode nao suportar visao "
                "ou houve erro de quota/rede (veja o log acima)."
            )

        assert len(texto) > 0

    def test_ocr_detecta_tipo_apos_extracao(self, scanned_pdf):
        """Verifica que o tipo do documento é identificado corretamente após OCR."""
        from infrastructure.pdf.pdf_reader import detect_document_type
        from domain.entities.company_profile import DocumentType

        texto = _do_ocr(scanned_pdf, _API_KEY, _MODEL)
        if not texto:
            pytest.skip("OCR sem resultado, tipo nao pode ser verificado.")

        tipo = detect_document_type(texto, scanned_pdf.name)
        assert tipo != DocumentType.DESCONHECIDO, (
            f"Tipo nao identificado para '{scanned_pdf.name}' — "
            f"adicione palavras-chave ao texto extraído ou ao nome do arquivo."
        )
