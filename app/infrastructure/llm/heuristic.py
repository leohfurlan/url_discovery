"""
infrastructure/llm/heuristic.py

Classificação local por padrões de texto — zero chamadas de API.
Cobre os campos mais comuns em formulários brasileiros B2B.
Retorna None quando não há match suficientemente confiável.
"""
from __future__ import annotations

import re
from domain.entities.form import FieldType, FormField, SemanticType

# Classificações que nunca fazem sentido em campos de texto longo (textarea).
# Um textarea ("Descreva...", "Justifique...") é uma resposta aberta — qualquer
# match com dado estruturado curto é ruído de keyword, não a intenção do campo.
# Sem isso, a pergunta 20 ("Descreva seu programa de integridade") era classificada
# como `endereco` só porque o enunciado continha a palavra "endereço".
_TEXTAREA_BLOCKED: set[SemanticType] = {
    SemanticType.EMAIL_CORPORATIVO,
    SemanticType.EMAIL_GENERICO,
    SemanticType.CNPJ,
    SemanticType.CPF,
    SemanticType.CEP,
    SemanticType.TELEFONE,
    SemanticType.ENDERECO,
    SemanticType.LOGRADOURO,
    SemanticType.NUMERO_ENDERECO,
    SemanticType.COMPLEMENTO,
    SemanticType.BAIRRO,
    SemanticType.CIDADE,
    SemanticType.ESTADO,
    SemanticType.PAIS,
    SemanticType.AGENCIA,
    SemanticType.CONTA,
    SemanticType.BANCO,
    SemanticType.FAVORECIDO,
    SemanticType.INSCRICAO_EST,
    SemanticType.INSCRICAO_MUN,
    SemanticType.CPF_SOCIO,
}

# Tuplas (padrão compilado, SemanticType).
# Ordem importa: regras mais específicas primeiro para evitar que "nome"
# capture "nome da empresa" ou "nome do sócio".
_RULES: list[tuple[re.Pattern, SemanticType]] = [
    # ── Documentos fiscais ────────────────────────────────────────────────
    (re.compile(r'\bcnpj\b', re.I),                          SemanticType.CNPJ),
    (re.compile(r'\bcpf\b', re.I),                           SemanticType.CPF),
    (re.compile(r'\binscri[cç][aã]o\s+estadual\b', re.I),   SemanticType.INSCRICAO_EST),
    (re.compile(r'\binscri[cç][aã]o\s+municipal\b', re.I),  SemanticType.INSCRICAO_MUN),

    # ── Identificação da empresa ──────────────────────────────────────────
    # NOME_FANTASIA antes de RAZAO_SOCIAL: labels como "Nome da Empresa (Nome Fantasia)"
    # contêm "nome da empresa" (regex de RAZAO_SOCIAL) e "fantasia" ao mesmo tempo —
    # a ordem garante que o mais específico vence.
    (re.compile(r'\b(nome\s+fantasia|nome\s+de\s+fantasia|nome\s+comercial|trade\s+name|fantasia)\b', re.I), SemanticType.NOME_FANTASIA),
    (re.compile(r'\b(raz[aã]o\s+social|nome\s+da\s+empresa|company\s+name|denomina[cç][aã]o)\b', re.I),     SemanticType.RAZAO_SOCIAL),
    (re.compile(r'\b(atividade|cnae|ramo\s+de\s+atividade|segmento|setor)\b', re.I),                         SemanticType.ATIVIDADE),

    # ── Contato ───────────────────────────────────────────────────────────
    (re.compile(r'\be-?mail\b', re.I),                        SemanticType.EMAIL_CORPORATIVO),
    (re.compile(r'\b(telefone|celular|whatsapp|fone|phone)\b', re.I), SemanticType.TELEFONE),

    # ── Endereço (partes específicas antes do tipo genérico) ─────────────────
    (re.compile(r'\blogradouro\b', re.I),                                       SemanticType.LOGRADOURO),
    (re.compile(r'\b(complemento|apto\.?|apartamento|sala)\b', re.I),           SemanticType.COMPLEMENTO),
    (re.compile(r'\bbairro\b', re.I),                                            SemanticType.BAIRRO),
    (re.compile(r'\b(endere[cç]o|logradouro|address)\b', re.I),                 SemanticType.ENDERECO),
    (re.compile(r'\bcep\b', re.I),                                               SemanticType.CEP),
    (re.compile(r'\b(cidade|city|munic[íi]pio)\b', re.I),                       SemanticType.CIDADE),
    (re.compile(r'\b(estado|state|\buf\b)\b', re.I),                             SemanticType.ESTADO),
    (re.compile(r'\b(pa[íi]s|country)\b', re.I),                                SemanticType.PAIS),

    # ── Dados bancários ───────────────────────────────────────────────────
    (re.compile(r'\bbanco\b', re.I),                            SemanticType.BANCO),
    (re.compile(r'\bag[eê]ncia\b', re.I),                       SemanticType.AGENCIA),
    (re.compile(r'\b(conta\s+(banc[aá]ria|corrente|poupan[cç]a)|n[uú]mero\s+da\s+conta)\b', re.I), SemanticType.CONTA),
    (re.compile(r'\b(favorecido|titular\s+da\s+conta|benefici[aá]rio)\b', re.I), SemanticType.FAVORECIDO),

    # "Número" isolado após bancárias: é número do imóvel, não de conta/agência
    (re.compile(r'\bn[uú]mero\b', re.I),                                         SemanticType.NUMERO_ENDERECO),

    # ── Sócios / responsáveis ─────────────────────────────────────────────
    (re.compile(r'\b(cpf\s+do\s+s[oó]cio|cpf\s+do\s+respons)\b', re.I), SemanticType.CPF_SOCIO),
    (re.compile(r'\b(s[oó]cio|respons[aá]vel\s+legal|representante\s+legal)\b', re.I), SemanticType.NOME_SOCIO),

    # ── Aceite / declaração ───────────────────────────────────────────────
    (re.compile(r'\b(concordo|aceito|declaro|termos\s+e\s+condi[cç][oõ]es)\b', re.I), SemanticType.ACEITE_TERMOS),

    # ── Upload ────────────────────────────────────────────────────────────
    (re.compile(r'\b(upload|anexar|arquivo|attachment)\b', re.I), SemanticType.DOCUMENTO_PDF),

    # ── Nome genérico (deve ficar por último) ─────────────────────────────
    (re.compile(r'\bnome\b', re.I), SemanticType.NOME_PESSOA),
]


# Conjuntos de opções que indicam um radio binário Sim/Não — resolvidos
# localmente para evitar ida ao LLM. Sem isso, cada par "Sim/Não" do
# questionário de integridade vira uma chamada de ~30s.
_BINARY_YES_NO_OPTION_SETS: tuple[frozenset[str], ...] = (
    frozenset({"sim", "não"}),
    frozenset({"sim", "nao"}),
    frozenset({"yes", "no"}),
    frozenset({"true", "false"}),
)

# Enunciados de aceite/declaração/consentimento. Em campos de escolha
# (radio/checkbox) a intenção é confirmar, não coletar dado estrutural —
# por isso tem prioridade sobre keywords como "agência" ou "representante
# legal" que aparecem no meio da pergunta (ex.: "Declaro estar ciente, na
# condição de representante legal, que...").
_ACEITE_PATTERN = re.compile(
    r'\b(concord[oa]|aceit[oa]|declaro|declara[cç][aã]o|ciente|consinto|'
    r'consentimento|autorizo|termos\s+e\s+condi[cç][oõ]es)\b',
    re.I,
)


def _is_binary_yes_no(field: FormField) -> bool:
    """True se o campo é um radio cujas opções são exatamente Sim/Não (ou equivalentes)."""
    if field.field_type != FieldType.RADIO or not field.options:
        return False
    options_norm = frozenset(o.strip().lower() for o in field.options)
    return options_norm in _BINARY_YES_NO_OPTION_SETS


def heuristic_classify(field: FormField) -> SemanticType | None:
    """Tenta classificar o campo por heurística de texto. Retorna None se incerto."""
    text = " ".join(filter(None, [
        field.label or "",
        field.name or "",
        field.placeholder or "",
        " ".join(field.options),
    ]))
    is_textarea = field.field_type == FieldType.TEXTAREA
    is_choice = field.field_type in (FieldType.RADIO, FieldType.CHECKBOX)

    # Campo de escolha cujo enunciado é uma declaração/aceite: confirma intenção,
    # não coleta dado. Tem prioridade sobre as regras estruturais abaixo para
    # evitar matches espúrios (ex.: pergunta 4 "Declaro estar ciente... na condição
    # de representante legal" virava NOME_SOCIO por causa de "representante legal").
    if is_choice and _ACEITE_PATTERN.search(text):
        return SemanticType.ACEITE_TERMOS

    # Radio binário Sim/Não sem aceite detectado → UNKNOWN. Bloqueia que uma
    # keyword estrutural no texto da pergunta de compliance (ex.: "agência
    # reguladora", "prestação de serviço") seja classificada como agencia_bancaria
    # ou nome_pessoa. O DataGenerator trata RADIO + UNKNOWN com o padrão "Não".
    if _is_binary_yes_no(field):
        return SemanticType.UNKNOWN

    for pattern, semantic in _RULES:
        if is_textarea and semantic in _TEXTAREA_BLOCKED:
            continue
        if pattern.search(text):
            return semantic

    return None
