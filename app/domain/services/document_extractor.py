from __future__ import annotations

import structlog
from pathlib import Path

from domain.entities.company_profile import CompanyProfile, DocumentType
from infrastructure.pdf.pdf_reader import extract_text, detect_document_type
from infrastructure.pdf.gemma_extractor import extract_fields

logger = structlog.get_logger(__name__)

# Ordem de prioridade: campos de documentos mais cedo na lista sobrescrevem os posteriores.
_PRIORITY_ORDER = [
    DocumentType.CARTAO_CNPJ,
    DocumentType.CONTRATO_SOCIAL,
    DocumentType.DEMONSTRACOES_FINANCEIRAS,
    DocumentType.DESCONHECIDO,
]

# Mapeamento campo-do-dict-extraído → atributo de CompanyProfile
_FIELD_MAP: dict[DocumentType, dict[str, str]] = {
    DocumentType.CARTAO_CNPJ: {
        "cnpj":                "cnpj",
        "razao_social":        "razao_social",
        "nome_fantasia":       "nome_fantasia",
        "atividade":           "atividade",
        "endereco":            "endereco",
        "cep":                 "cep",
        "cidade":              "cidade",
        "estado":              "estado",
        "telefone":            "telefone",
        "email":               "email",
        "inscricao_estadual":  "inscricao_estadual",
        "inscricao_municipal": "inscricao_municipal",
    },
    DocumentType.CONTRATO_SOCIAL: {
        "razao_social":        "razao_social",
        "cnpj":                "cnpj",
        "nome_socio_principal": "nome_socio_principal",
        "cpf_socio_principal":  "cpf_socio_principal",
        "objeto_social":        "objeto_social",
    },
    DocumentType.DEMONSTRACOES_FINANCEIRAS: {
        "banco":               "banco",
        "agencia":             "agencia",
        "conta":               "conta",
        "favorecido":          "favorecido",
        "faturamento_anual":   "faturamento_anual",
        "periodo_referencia":  "periodo_referencia",
    },
}


class DocumentExtractor:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemma-4-26b-a4b-it",
        ocr_model: str = "gemma-4-26b-a4b-it",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._ocr_model = ocr_model

    def load_from_directory(self, docs_dir: Path) -> CompanyProfile:
        """Processa todos os PDFs do diretório e mescla em um único CompanyProfile.

        Campos do Cartão CNPJ têm prioridade; seguidos pelo Contrato Social
        e pelas Demonstrações Financeiras.
        """
        pdfs = sorted(docs_dir.glob("*.pdf"))
        if not pdfs:
            logger.warning("nenhum_pdf_encontrado", diretorio=str(docs_dir))
            return CompanyProfile()

        # Agrupa PDFs por tipo detectado
        by_type: dict[DocumentType, list[dict]] = {t: [] for t in _PRIORITY_ORDER}
        for path in pdfs:
            logger.info("processando_pdf", arquivo=path.name)
            raw_data = self.load_single(path)
            if raw_data.get("_doc_type"):
                doc_type = raw_data.pop("_doc_type")
                by_type[doc_type].append(raw_data)

        # Constrói perfil mesclando por ordem de prioridade
        merged: dict[str, str | None] = {}
        for doc_type in _PRIORITY_ORDER:
            field_map = _FIELD_MAP.get(doc_type, {})
            for extracted in by_type[doc_type]:
                for src_key, dst_attr in field_map.items():
                    value = extracted.get(src_key)
                    if value and not merged.get(dst_attr):
                        merged[dst_attr] = str(value).strip()

        profile = CompanyProfile(**merged)
        logger.info(
            "perfil_carregado",
            cnpj=profile.cnpj,
            razao_social=profile.razao_social,
            banco=profile.banco,
            campos_preenchidos=sum(1 for v in merged.values() if v),
        )
        return profile

    def load_single(self, path: Path) -> dict:
        """Processa um único PDF. Retorna dict com campos extraídos + '_doc_type'."""
        text = extract_text(path, api_key=self._api_key, ocr_model=self._ocr_model)
        doc_type = detect_document_type(text, path.name)
        fields = extract_fields(text, doc_type, api_key=self._api_key, model=self._model)
        fields["_doc_type"] = doc_type
        return fields
