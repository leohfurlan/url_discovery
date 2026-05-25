"""
classifier.py — Classificação semântica de campos de formulário em dois estágios.

Estágio 1 — Heurística (classify_by_heuristic):
    Correspondência de substrings contra HEURISTIC_RULES. Rápido, sem custo de API,
    cobre a maioria dos campos brasileiros comuns (CNPJ, CPF, e-mail, CEP...).

Estágio 2 — LLM via Gemini (classify_by_llm):
    Acionado apenas quando a heurística retorna UNKNOWN. Envia o semantic_hint do
    campo ao modelo Gemma e interpreta a resposta como um SemanticType.
    Requer GEMINI_API_KEY; retorna UNKNOWN se a chave não estiver configurada.

Ponto de entrada público: classify(field) — encadeia os dois estágios.

Relação com gemma_adapter.py:
    GemmaClassifier (infrastructure/llm/gemma_adapter.py) implementa ClassifierPort
    usando o mesmo modelo Gemini, mas recebe uma lista de campos por página e é
    usado pelo NavigationOrchestrator. Este módulo é funcional (sem estado) e pode
    ser importado diretamente em contextos mais simples ou em testes unitários.
"""

from __future__ import annotations
from domain.entities.form import FormField, SemanticType
import os
from google import genai as google_genai
from dotenv import load_dotenv

load_dotenv()

# ── Tabela de heurísticas ─────────────────────────────────────────────────────
# Ordem importa: mais específico primeiro.
# Cada entrada: (SemanticType, [keywords])
# O hint do campo é normalizado para lowercase antes da comparação.

HEURISTIC_RULES: list[tuple[SemanticType, list[str]]] = [
    (SemanticType.CNPJ, [
        "cnpj", "cadastro nacional", "número pj", "id empresa", "identificação pj", "pessoa jurídica",
    ]),
    (SemanticType.CPF, [
        "cpf", "cadastro de pessoa física", "número cpf",
    ]),
    (SemanticType.RAZAO_SOCIAL, [
        "razão social", "razao social", "nome social", "nome da empresa",
        "nome empresarial", "denominação social",
    ]),
    (SemanticType.NOME_FANTASIA, [
        "nome fantasia", "fantasia", "nome comercial",
    ]),
    (SemanticType.EMAIL_CORPORATIVO, [
        "e-mail corporativo", "email corporativo", "e-mail empresarial",
        "email empresarial", "e-mail da empresa", "email da empresa",
    ]),
    (SemanticType.EMAIL_GENERICO, [
        "e-mail", "email", "endereço de e-mail",
    ]),
    (SemanticType.TELEFONE, [
        "telefone", "celular", "whatsapp", "fone", "contato telefônico",
    ]),
    (SemanticType.CEP, [
        "cep", "código postal",
    ]),
    (SemanticType.ENDERECO, [
        "endereço", "logradouro", "rua", "avenida",
    ]),
    (SemanticType.CIDADE, [
        "cidade", "município", "municipio",
    ]),
    (SemanticType.ESTADO, [
        "estado", "uf", "unidade federativa",
    ]),
    (SemanticType.PAIS, [
        "país", "pais", "country",
    ]),
    (SemanticType.INSCRICAO_EST, [
        "inscrição estadual", "inscricao estadual", "ie ",
    ]),
    (SemanticType.INSCRICAO_MUN, [
        "inscrição municipal", "inscricao municipal", "im ", "iss",
    ]),
    (SemanticType.NOME_PESSOA, [
        "nome do responsável", "nome do contato", "nome completo",
        "responsável", "contato", "nome do representante",
    ]),
    (SemanticType.ATIVIDADE, [
        "atividade", "ramo", "segmento", "setor", "cnae",
    ]),
    (SemanticType.BANCO, [
        "banco", "instituição financeira",
    ]),
    (SemanticType.AGENCIA, [
        "agência", "agencia",
    ]),
    (SemanticType.CONTA, [
        "conta corrente", "conta bancária", "conta bancaria", "número da conta",
    ]),
    (SemanticType.ACEITE_TERMOS, [
        "termos", "aceito", "concordo", "política", "lgpd",
    ]),
    (SemanticType.FAVORECIDO, [
        "favorecido", "titular da conta", "beneficiário", "beneficiario",
    ]),
    (SemanticType.NOME_SOCIO, [
        "nome do sócio", "nome do socio", "sócio", "socio", "representante legal",
    ]),
    (SemanticType.CPF_SOCIO, [
        "cpf do sócio", "cpf do socio", "cpf do representante", "cpf do responsável",
    ]),
]


def _normalize(text: str) -> str:
    return text.lower().strip()


def classify_by_heuristic(field: FormField) -> SemanticType:
    """Classifica o campo por correspondência de substrings contra HEURISTIC_RULES.

    Retorna UNKNOWN quando nenhuma keyword bate — sinal para acionar o LLM.
    """
    hint = _normalize(field.semantic_hint)
    if not hint:
        return SemanticType.UNKNOWN

    for semantic_type, keywords in HEURISTIC_RULES:
        for kw in keywords:
            if kw in hint:
                return semantic_type

    return SemanticType.UNKNOWN


_SEMANTIC_TYPES = [t.value for t in SemanticType if t != SemanticType.UNKNOWN]


def classify_by_llm(field: FormField) -> SemanticType:
    """Classifica o campo via Gemini quando a heurística não foi suficiente.

    Envia o semantic_hint ao modelo e converte a resposta em SemanticType.
    Retorna UNKNOWN se a GEMINI_API_KEY não estiver definida ou se o modelo
    responder com um valor fora do enum.
    """
    hint = field.semantic_hint
    if not hint:
        return SemanticType.UNKNOWN

    prompt = f"""Você é um classificador de campos de formulários web brasileiros.

Dado o hint de um campo (combinação de label, name, id e placeholder), classifique em exatamente um dos tipos abaixo.
Responda SOMENTE com o valor do tipo, sem explicação, sem aspas, sem formatação.

Tipos disponíveis:
{chr(10).join(_SEMANTIC_TYPES)}

Hint do campo: {hint}"""

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return SemanticType.UNKNOWN

    client = google_genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemma-4-26b-a4b-it",
        contents=prompt,
    )
    raw = response.text.strip()

    try:
        return SemanticType(raw)
    except ValueError:
        return SemanticType.UNKNOWN


def classify(field: FormField) -> SemanticType:
    """Ponto de entrada principal: heurística primeiro, LLM como fallback."""
    result = classify_by_heuristic(field)
    if result != SemanticType.UNKNOWN:
        return result
    return classify_by_llm(field)