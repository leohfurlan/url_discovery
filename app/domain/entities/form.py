from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field

class FieldType(str, Enum):
    TEXT     = "text"
    EMAIL    = "email"
    TEL      = "tel"
    NUMBER   = "number"
    RADIO    = "radio"
    CHECKBOX = "checkbox"
    SELECT   = "select"
    TEXTAREA = "textarea"
    FILE     = "file"
    UNKNOWN  = "unknown"

class SemanticType(str, Enum):
    RAZAO_SOCIAL      = "razao_social"
    NOME_FANTASIA     = "nome_fantasia"
    CNPJ              = "cnpj"
    CPF               = "cpf"
    INSCRICAO_EST     = "inscricao_estadual"
    INSCRICAO_MUN     = "inscricao_municipal"
    EMAIL_CORPORATIVO = "email_corporativo"
    EMAIL_GENERICO    = "email_generico"
    TELEFONE          = "telefone"
    NOME_PESSOA       = "nome_pessoa"
    ENDERECO          = "endereco"
    CEP               = "cep"
    CIDADE            = "cidade"
    ESTADO            = "estado"
    PAIS              = "pais"
    ATIVIDADE         = "atividade_empresa"
    BANCO             = "banco"
    AGENCIA           = "agencia_bancaria"
    CONTA             = "conta_bancaria"
    TEXTO_LIVRE       = "texto_livre"
    ACEITE_TERMOS     = "aceite_termos"
    UNKNOWN           = "unknown"

class FormField(BaseModel):
    # --- vem do DOM ---
    tag: str
    field_type: FieldType
    label: str | None = None
    name: str | None = None
    id: str | None = None
    placeholder: str | None = None
    required: bool = False
    selector: str
    options: list[str] = Field(default_factory=list)
    page_number: int = 1

    # --- vem do classificador ---
    semantic_type: SemanticType | None = None
    generated_value: str | None = None

    @property
    def semantic_hint(self) -> str:
        parts = [p for p in [self.label, self.name, self.id, self.placeholder] if p]
        return " | ".join(parts)
    
class FormPage(BaseModel):
    number: int
    fields: list[FormField] = Field(default_factory=list)
    is_complete: bool = False

class FormSession(BaseModel):
    portal: str
    url: str
    pages: list[FormPage] = Field(default_factory=list)
    current_page: int = 1
    screenshots: list[str] = Field(default_factory=list)

    def current(self) -> FormPage | None:
        for page in self.pages:
            if page.number == self.current_page:
                return page
        return None

    def all_fields(self) -> list[FormField]:
        return [field for page in self.pages for field in page.fields]

    def pending_fields(self) -> list[FormField]:
        return [f for f in self.all_fields() if f.generated_value is None]

class ExecutionResult(BaseModel):
    portal: str
    success: bool = False
    error: str | None = None
    filled_fields: list[FormField] = Field(default_factory=list)
    screenshots: list[str] = Field(default_factory=list)

    def summary(self) -> str:
        total = len(self.filled_fields)
        filled = sum(1 for f in self.filled_fields if f.generated_value is not None)
        status = "✓" if self.success else "✗"
        return f"[{status}] {self.portal} — {filled}/{total} campos preenchidos"