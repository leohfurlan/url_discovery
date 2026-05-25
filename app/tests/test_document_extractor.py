from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from domain.entities.company_profile import CompanyProfile, DocumentType
from domain.services.document_extractor import DocumentExtractor


def _extractor() -> DocumentExtractor:
    return DocumentExtractor(api_key="fake-key", model="gemma-test")


# ── load_from_directory ───────────────────────────────────────────────────────

class TestLoadFromDirectory:
    def test_retorna_perfil_vazio_sem_pdfs(self, tmp_path):
        profile = _extractor().load_from_directory(tmp_path)
        assert profile.is_empty()

    def test_carrega_campos_do_cartao_cnpj(self, tmp_path):
        (tmp_path / "cnpj.pdf").write_bytes(b"fake")

        campos_cnpj = {
            "cnpj": "12.345.678/0001-99",
            "razao_social": "Vulcaflex S.A.",
            "cidade": "Caxias do Sul",
            "estado": "RS",
        }

        with patch.object(DocumentExtractor, "load_single", return_value={**campos_cnpj, "_doc_type": DocumentType.CARTAO_CNPJ}):
            profile = _extractor().load_from_directory(tmp_path)

        assert profile.cnpj == "12.345.678/0001-99"
        assert profile.razao_social == "Vulcaflex S.A."
        assert profile.cidade == "Caxias do Sul"

    def test_carrega_campos_bancarios_das_demonstracoes(self, tmp_path):
        (tmp_path / "dre.pdf").write_bytes(b"fake")

        campos_dre = {
            "banco": "Bradesco",
            "agencia": "1234",
            "conta": "56789-0",
            "favorecido": "Vulcaflex S.A.",
        }

        with patch.object(DocumentExtractor, "load_single", return_value={**campos_dre, "_doc_type": DocumentType.DEMONSTRACOES_FINANCEIRAS}):
            profile = _extractor().load_from_directory(tmp_path)

        assert profile.banco == "Bradesco"
        assert profile.agencia == "1234"
        assert profile.conta == "56789-0"
        assert profile.favorecido == "Vulcaflex S.A."

    def test_cartao_cnpj_tem_prioridade_sobre_contrato_social(self, tmp_path):
        (tmp_path / "cnpj.pdf").write_bytes(b"fake")
        (tmp_path / "contrato.pdf").write_bytes(b"fake")

        resultados = [
            {**{"cnpj": "11.111.111/0001-11", "razao_social": "Empresa CNPJ"}, "_doc_type": DocumentType.CARTAO_CNPJ},
            {**{"razao_social": "Empresa Contrato"}, "_doc_type": DocumentType.CONTRATO_SOCIAL},
        ]

        with patch.object(DocumentExtractor, "load_single", side_effect=resultados):
            profile = _extractor().load_from_directory(tmp_path)

        assert profile.razao_social == "Empresa CNPJ"

    def test_contrato_preenche_campos_ausentes_no_cnpj(self, tmp_path):
        (tmp_path / "cnpj.pdf").write_bytes(b"fake")
        (tmp_path / "contrato.pdf").write_bytes(b"fake")

        resultados = [
            {**{"cnpj": "11.111.111/0001-11"}, "_doc_type": DocumentType.CARTAO_CNPJ},
            {**{"nome_socio_principal": "João da Silva", "cpf_socio_principal": "111.222.333-44"}, "_doc_type": DocumentType.CONTRATO_SOCIAL},
        ]

        with patch.object(DocumentExtractor, "load_single", side_effect=resultados):
            profile = _extractor().load_from_directory(tmp_path)

        assert profile.cnpj == "11.111.111/0001-11"
        assert profile.nome_socio_principal == "João da Silva"

    def test_ignora_pdfs_com_extracao_vazia(self, tmp_path):
        (tmp_path / "desconhecido.pdf").write_bytes(b"fake")

        with patch.object(DocumentExtractor, "load_single", return_value={"_doc_type": DocumentType.DESCONHECIDO}):
            profile = _extractor().load_from_directory(tmp_path)

        assert profile.is_empty()


# ── load_single ───────────────────────────────────────────────────────────────

class TestLoadSingle:
    def test_retorna_doc_type_no_resultado(self, tmp_path):
        pdf = tmp_path / "cnpj.pdf"
        pdf.write_bytes(b"fake")

        with patch("domain.services.document_extractor.extract_text", return_value="receita federal"):
            with patch("domain.services.document_extractor.extract_fields", return_value={"cnpj": "12.345.678/0001-99"}):
                result = _extractor().load_single(pdf)

        assert "_doc_type" in result
        assert result["_doc_type"] == DocumentType.CARTAO_CNPJ

    def test_repassa_campos_extraidos(self, tmp_path):
        pdf = tmp_path / "cnpj.pdf"
        pdf.write_bytes(b"fake")

        with patch("domain.services.document_extractor.extract_text", return_value="receita federal"):
            with patch("domain.services.document_extractor.extract_fields", return_value={"cnpj": "99.999.999/0001-99", "cidade": "Porto Alegre"}):
                result = _extractor().load_single(pdf)

        assert result["cnpj"] == "99.999.999/0001-99"
        assert result["cidade"] == "Porto Alegre"

    def test_retorna_desconhecido_quando_extracao_vazia(self, tmp_path):
        pdf = tmp_path / "misc.pdf"
        pdf.write_bytes(b"fake")

        with patch("domain.services.document_extractor.extract_text", return_value="texto sem keywords"):
            with patch("domain.services.document_extractor.extract_fields", return_value={}):
                result = _extractor().load_single(pdf)

        assert result["_doc_type"] == DocumentType.DESCONHECIDO
