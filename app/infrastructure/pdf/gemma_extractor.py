"""
gemma_extractor.py — Extração estruturada de campos de documentos PDF via Gemma.

Usa o mesmo client/modelo já configurados no projeto (google-genai + gemma-4-26b-a4b-it).
Para cada tipo de documento há um prompt específico que instrui o modelo a retornar
somente JSON válido com os campos esperados.
"""
from __future__ import annotations

import json
import os
import structlog
from google import genai as google_genai
from domain.entities.company_profile import DocumentType

logger = structlog.get_logger(__name__)

_PROMPTS: dict[DocumentType, str] = {
    DocumentType.CARTAO_CNPJ: """Você está analisando um Cartão CNPJ emitido pela Receita Federal brasileira.
Extraia as informações abaixo do texto fornecido e retorne SOMENTE um JSON válido, sem markdown, sem explicação.
Se um campo não existir no documento, use null.

Campos:
- cnpj: string (formato XX.XXX.XXX/XXXX-XX)
- razao_social: string
- nome_fantasia: string (pode ser igual à razão social ou null)
- atividade: string (descrição da atividade econômica principal / CNAE)
- endereco: string (logradouro, número e complemento — sem bairro e sem CEP)
- bairro: string (campo "BAIRRO/DISTRITO" do cartão CNPJ)
- cep: string (formato XXXXX-XXX)
- cidade: string
- estado: string (sigla da UF, 2 letras maiúsculas)
- telefone: string
- email: string (campo "ENDEREÇO ELETRÔNICO" do cartão CNPJ)
- inscricao_estadual: string
- inscricao_municipal: string

Texto do documento:
{text}""",

    DocumentType.CONTRATO_SOCIAL: """Você está analisando um Contrato Social ou Alteração Contratual de empresa brasileira.
Extraia as informações abaixo e retorne SOMENTE um JSON válido, sem markdown, sem explicação.
Se um campo não existir no documento, use null.

Campos:
- razao_social: string
- cnpj: string (formato XX.XXX.XXX/XXXX-XX, se houver)
- nome_socio_principal: string (nome do primeiro sócio/administrador)
- cpf_socio_principal: string (CPF do primeiro sócio, formato XXX.XXX.XXX-XX)
- objeto_social: string (atividade/objeto principal da empresa, máximo 200 caracteres)

Texto do documento:
{text}""",

    DocumentType.DEMONSTRACOES_FINANCEIRAS: """Você está analisando um documento financeiro brasileiro (Extrato Bancário, DRE, Balanço Patrimonial ou similar).
Extraia as informações bancárias para recebimento e retorne SOMENTE um objeto JSON (não array), sem markdown, sem explicação.
Se um campo não existir no documento, use null.

Campos:
- banco: string (nome do banco, ex: "Nubank", "Bradesco", "Itaú", "Banco do Brasil", "Caixa")
- agencia: string (número da agência bancária, ex: "0001")
- conta: string (número completo da conta com dígito verificador, ex: "224776546-5")
- favorecido: string (nome completo do titular da conta)
- faturamento_anual: string (total de entradas no período ou faturamento anual em R$, ex: "R$ 24.218,40")
- periodo_referencia: string (período de referência do documento, ex: "27/03/2026 a 25/05/2026" ou "2024")

Texto do documento:
{text}""",
}


def extract_fields(
    text: str,
    doc_type: DocumentType,
    api_key: str | None = None,
    model: str = "gemma-4-26b-a4b-it",
) -> dict:
    """Envia o texto ao Gemma e retorna um dict com os campos extraídos.

    Retorna dict vazio se o tipo for DESCONHECIDO, se não houver API key ou
    se a resposta não puder ser interpretada como JSON.
    """
    if doc_type == DocumentType.DESCONHECIDO:
        logger.warning("extracao_pulada", motivo="tipo_desconhecido")
        return {}

    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        logger.error("extracao_falhou", motivo="GEMINI_API_KEY_nao_configurada")
        return {}

    if not text.strip():
        logger.warning("extracao_pulada", motivo="texto_vazio")
        return {}

    prompt = _PROMPTS[doc_type].format(text=text)

    try:
        client = google_genai.Client(api_key=key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        raw = (response.text or "").strip()
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("resposta não é um objeto JSON")
        logger.info("extracao_concluida", tipo=doc_type.value, campos_extraidos=len([v for v in result.values() if v]))
        return result
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("extracao_json_invalido", tipo=doc_type.value, erro=str(exc), raw=raw[:300])
        return {}
    except Exception as exc:
        logger.error("extracao_falhou", tipo=doc_type.value, erro=str(exc))
        return {}
