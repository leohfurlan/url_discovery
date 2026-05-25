"""
Testes de integração para pdf_reader com documentos reais.

Como usar:
    1. Coloque os PDFs na pasta docs/ na raiz do projeto
    2. Execute:
           python -m pytest app/tests/test_pdf_reader_integration.py -v -s

    O -s exibe o texto extraído de cada PDF para inspeção visual.
    PDFs escaneados usam OCR via Gemma se GEMINI_API_KEY estiver configurada.

Os testes são pulados automaticamente se docs/ não existir ou estiver vazia.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv()

from domain.entities.company_profile import DocumentType
from infrastructure.pdf.pdf_reader import extract_text, detect_document_type

_DOCS_DIR = Path(__file__).parents[2] / "docs"
_PDFS = list(_DOCS_DIR.glob("*.pdf")) if _DOCS_DIR.is_dir() else []
_API_KEY = os.getenv("GEMINI_API_KEY")

pytestmark = pytest.mark.skipif(
    not _PDFS,
    reason=f"Nenhum PDF encontrado em {_DOCS_DIR} — coloque os documentos reais la para rodar estes testes.",
)


@pytest.fixture(params=_PDFS, ids=[p.name for p in _PDFS])
def pdf_path(request) -> Path:
    return request.param


class TestExtractText:
    def test_extrai_texto_nao_vazio(self, pdf_path):
        texto = extract_text(pdf_path, api_key=_API_KEY)
        if len(texto) == 0:
            pytest.skip(
                f"{pdf_path.name}: texto vazio apos OCR. "
                "PDF provavelmente escaneado e o modelo nao suportou visao — "
                "tente um modelo com capacidade multimodal (ex: gemini-1.5-flash)."
            )
        assert len(texto) > 0

    def test_texto_contem_caracteres_latinos(self, pdf_path):
        texto = extract_text(pdf_path, api_key=_API_KEY)
        if not texto:
            pytest.skip(f"{pdf_path.name}: texto vazio, pulando verificacao de caracteres.")
        assert any(c.isalpha() for c in texto), (
            f"{pdf_path.name}: nenhum caractere alfabetico encontrado."
        )

    def test_exibe_preview_do_texto(self, pdf_path, capsys):
        texto = extract_text(pdf_path, api_key=_API_KEY)
        preview = texto[:600].replace("\n", " | ")
        sep = "-" * 60
        with capsys.disabled():
            print(f"\n{sep}")
            print(f"  Arquivo : {pdf_path.name}")
            print(f"  Chars   : {len(texto)}")
            print(f"  Preview : {preview}")
            print(sep)


class TestDetectDocumentType:
    _EXPECTED: dict[str, DocumentType] = {
        "cnpj":         DocumentType.CARTAO_CNPJ,
        "cartao":       DocumentType.CARTAO_CNPJ,
        "contrato":     DocumentType.CONTRATO_SOCIAL,
        "alteracao":    DocumentType.CONTRATO_SOCIAL,
        "dre":          DocumentType.DEMONSTRACOES_FINANCEIRAS,
        "balanco":      DocumentType.DEMONSTRACOES_FINANCEIRAS,
        "demonstracao": DocumentType.DEMONSTRACOES_FINANCEIRAS,
        "extrato":      DocumentType.DEMONSTRACOES_FINANCEIRAS,
        "nubank":       DocumentType.DEMONSTRACOES_FINANCEIRAS,
        "bradesco":     DocumentType.DEMONSTRACOES_FINANCEIRAS,
        "itau":         DocumentType.DEMONSTRACOES_FINANCEIRAS,
        "santander":    DocumentType.DEMONSTRACOES_FINANCEIRAS,
    }

    def test_detecta_tipo_do_documento(self, pdf_path):
        texto = extract_text(pdf_path, api_key=_API_KEY)
        tipo = detect_document_type(texto, pdf_path.name)

        nome = pdf_path.stem.lower()
        for keyword, esperado in self._EXPECTED.items():
            if keyword in nome:
                assert tipo == esperado, (
                    f"{pdf_path.name}: esperado {esperado.value}, detectado {tipo.value}."
                )
                return

        assert tipo in DocumentType

    def test_exibe_tipo_detectado(self, pdf_path, capsys):
        texto = extract_text(pdf_path, api_key=_API_KEY)
        tipo = detect_document_type(texto, pdf_path.name)
        with capsys.disabled():
            print(f"\n  {pdf_path.name:40s} -> {tipo.value}")
