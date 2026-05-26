"""
infrastructure/llm/heuristic.py

Classificação local por padrões de texto — zero chamadas de API.
Cobre os campos mais comuns em formulários brasileiros B2B.
Retorna None quando não há match suficientemente confiável.
"""
from __future__ import annotations

import re
from domain.entities.form import FormField, SemanticType

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
    (re.compile(r'\b(raz[aã]o\s+social|nome\s+da\s+empresa|company\s+name|denomina[cç][aã]o)\b', re.I), SemanticType.RAZAO_SOCIAL),
    (re.compile(r'\b(nome\s+fantasia|nome\s+comercial|trade\s+name)\b', re.I),                           SemanticType.NOME_FANTASIA),
    (re.compile(r'\b(atividade|cnae|ramo\s+de\s+atividade|segmento|setor)\b', re.I),                     SemanticType.ATIVIDADE),

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


def heuristic_classify(field: FormField) -> SemanticType | None:
    """Tenta classificar o campo por heurística de texto. Retorna None se incerto."""
    text = " ".join(filter(None, [
        field.label or "",
        field.name or "",
        field.placeholder or "",
        " ".join(field.options),
    ]))
    for pattern, semantic in _RULES:
        if pattern.search(text):
            return semantic
    return None
