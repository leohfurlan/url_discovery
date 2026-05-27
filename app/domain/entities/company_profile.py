from __future__ import annotations
from enum import Enum
from pydantic import BaseModel


class DocumentType(str, Enum):
    CARTAO_CNPJ              = "cartao_cnpj"
    CONTRATO_SOCIAL          = "contrato_social"
    DEMONSTRACOES_FINANCEIRAS = "demonstracoes_financeiras"
    DESCONHECIDO             = "desconhecido"


# Mapeamento SemanticType.value → atributo de CompanyProfile
_SEMANTIC_TO_FIELD: dict[str, str] = {
    "razao_social":        "razao_social",
    "nome_fantasia":       "nome_fantasia",
    "cnpj":                "cnpj",
    "cpf":                 "cpf_socio_principal",
    "inscricao_estadual":  "inscricao_estadual",
    "inscricao_municipal": "inscricao_municipal",
    "telefone":            "telefone",
    "nome_pessoa":         "nome_socio_principal",
    "endereco":            "endereco",
    "logradouro":          "logradouro",
    "numero_endereco":     "numero_endereco",
    "complemento":         "complemento",
    "bairro":              "bairro",
    "cep":                 "cep",
    "cidade":              "cidade",
    "estado":              "estado",
    "atividade_empresa":   "atividade",
    "banco":               "banco",
    "agencia_bancaria":    "agencia",
    "conta_bancaria":      "conta",
    "favorecido":          "favorecido",
    "nome_socio":          "nome_socio_principal",
    "cpf_socio":           "cpf_socio_principal",
    "email_generico":      "email",
    "email_corporativo":   "email",
}


class CompanyProfile(BaseModel):
    # ── Cartão CNPJ ──────────────────────────────────────────────────────────
    cnpj:                str | None = None
    razao_social:        str | None = None
    nome_fantasia:       str | None = None
    atividade:           str | None = None   # descrição da CNAE principal
    endereco:            str | None = None   # logradouro + número + complemento (endereço completo)
    logradouro:          str | None = None   # nome da rua/avenida
    numero_endereco:     str | None = None   # número do imóvel
    complemento:         str | None = None   # complemento (sala, apto, etc.)
    bairro:              str | None = None
    cep:                 str | None = None
    cidade:              str | None = None
    estado:              str | None = None   # UF (2 letras)
    telefone:            str | None = None
    email:               str | None = None   # email de contato da empresa
    inscricao_estadual:  str | None = None
    inscricao_municipal: str | None = None

    # ── Contrato Social ───────────────────────────────────────────────────────
    nome_socio_principal: str | None = None
    cpf_socio_principal:  str | None = None
    objeto_social:        str | None = None   # fallback para atividade

    # ── Demonstrações Financeiras ─────────────────────────────────────────────
    banco:              str | None = None
    agencia:            str | None = None
    conta:              str | None = None
    favorecido:         str | None = None    # titular da conta para recebimento
    faturamento_anual:  str | None = None
    periodo_referencia: str | None = None

    def get(self, semantic_type: object) -> str | None:
        """Retorna o valor real para um SemanticType, ou None se não disponível."""
        key = semantic_type.value if hasattr(semantic_type, "value") else str(semantic_type)

        # Casos especiais com fallback
        if key == "atividade_empresa":
            return self.atividade or self.objeto_social

        field_name = _SEMANTIC_TO_FIELD.get(key)
        if field_name is None:
            return None
        return getattr(self, field_name, None) or None

    def merge(self, other: "CompanyProfile") -> "CompanyProfile":
        """Retorna novo perfil: campos de self têm prioridade sobre other."""
        self_data = self.model_dump()
        other_data = other.model_dump()
        merged = {k: (self_data[k] if self_data[k] is not None else other_data[k]) for k in self_data}
        return CompanyProfile(**merged)

    def summary(self) -> str:
        """Resumo compacto dos campos preenchidos, para dar contexto ao LLM
        em decisões de fallback (ex.: escolher 'Porte de Empresa' coerente com
        o faturamento, ou 'Tipo de Fornecedor' coerente com a atividade)."""
        data = self.model_dump()
        return "; ".join(f"{k}: {v}" for k, v in data.items() if v)

    def is_empty(self) -> bool:
        return all(v is None for v in self.model_dump().values())
