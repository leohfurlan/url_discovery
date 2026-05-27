from __future__ import annotations
import os
import re
from faker import Faker
from domain.entities.form import FieldType, FormField, SemanticType
from domain.entities.company_profile import CompanyProfile
from infrastructure.formaters import (
    format_cnpj,
    format_cpf,
    format_phone_number,
    format_zip_code,
    company_email,
)

fake = Faker("pt_BR")


def generate(semantic_type: SemanticType) -> str:
    match semantic_type:
        case SemanticType.RAZAO_SOCIAL:
            return fake.company()

        case SemanticType.NOME_FANTASIA:
            return fake.company().split()[0] + " " + fake.company_suffix()

        case SemanticType.CNPJ:
            return format_cnpj(fake.cnpj())

        case SemanticType.CPF:
            return format_cpf(fake.cpf())

        case SemanticType.EMAIL_GENERICO:
            return fake.email()

        case SemanticType.EMAIL_CORPORATIVO:
            return company_email(fake.company())

        case SemanticType.TELEFONE:
            return format_phone_number(fake.msisdn()[3:])

        case SemanticType.CEP:
            return format_zip_code(fake.postcode())

        case SemanticType.ENDERECO:
            return fake.street_address()

        case SemanticType.LOGRADOURO:
            return fake.street_name()

        case SemanticType.NUMERO_ENDERECO:
            return fake.building_number()

        case SemanticType.COMPLEMENTO:
            return ""

        case SemanticType.BAIRRO:
            return fake.bairro()

        case SemanticType.CIDADE:
            return fake.city()

        case SemanticType.ESTADO:
            return fake.estado_sigla()

        case SemanticType.PAIS:
            return "Brasil"

        case SemanticType.INSCRICAO_EST:
            return "ISENTO"

        case SemanticType.INSCRICAO_MUN:
            return "ISENTO"

        case SemanticType.NOME_PESSOA:
            return fake.name()

        case SemanticType.ATIVIDADE:
            return "Comércio de materiais industriais"

        case SemanticType.BANCO:
            return "Bradesco"

        case SemanticType.AGENCIA:
            return "0001"

        case SemanticType.CONTA:
            return "12345-6"

        case SemanticType.ACEITE_TERMOS:
            return "true"

        case SemanticType.DOCUMENTO_PDF:
            return "true"

        case SemanticType.TEXTO_LIVRE:
            return fake.sentence(nb_words=6)

        case SemanticType.FAVORECIDO:
            return fake.name()

        case SemanticType.NOME_SOCIO:
            return fake.name()

        case SemanticType.CPF_SOCIO:
            return format_cpf(fake.cpf())

        case _:
            return fake.word()


class DataGenerator:
    """Gerador com memória de sessão para manter coerência entre campos relacionados.

    Se um CompanyProfile for fornecido, usa os dados reais como fonte prioritária.
    Campos ausentes no perfil (ou perfil não fornecido) caem no gerador fake.
    """

    def __init__(self, profile: CompanyProfile | None = None) -> None:
        self._profile = profile
        self._company_name: str | None = None
        self._company_email: str | None = os.getenv("COMPANY_EMAIL")
        if profile and profile.razao_social:
            self._company_name = profile.razao_social

        # Partes do endereço (parseadas do perfil ou geradas fake para manter coerência)
        self._addr_logradouro: str | None = None
        self._addr_numero: str | None = None
        self._addr_complemento: str | None = None
        self._addr_bairro: str | None = None
        self._addr_loaded = False

    def generate(self, semantic_type: SemanticType, field: FormField | None = None) -> str:
        # Corrige classificação errada em campo cujo label indica nome fantasia.
        # Cobre casos onde a heurística bateu em RAZAO_SOCIAL ou NOME_SOCIO antes
        # de checar "fantasia" / "comercial" (ex: "Nome da Empresa (Nome Fantasia)").
        if field is not None:
            label_lower = (field.label or "").lower()
            if semantic_type in (SemanticType.RAZAO_SOCIAL, SemanticType.NOME_SOCIO, SemanticType.NOME_PESSOA) and (
                "fantasia" in label_lower or "nome comercial" in label_lower
            ):
                semantic_type = SemanticType.NOME_FANTASIA

        # Documento PDF em checkbox: verifica disponibilidade real no perfil
        if (
            semantic_type == SemanticType.DOCUMENTO_PDF
            and field is not None
            and field.field_type == FieldType.CHECKBOX
        ):
            return self._document_available(field)

        # Radio sem classificação útil: padrão conservador "Não".
        # Cobre UNKNOWN e DESCONHECIDO — evita declarar afirmativas perigosas
        # em questionários de integridade (ex: "A empresa já teve problemas legais?").
        if (
            semantic_type in (SemanticType.UNKNOWN, SemanticType.DESCONHECIDO)
            and field is not None
            and field.field_type == FieldType.RADIO
        ):
            return "Não"

        # Checkbox sem classificação útil: deixa desmarcado em vez de gerar um
        # valor fake (palavra solta), que poluía o log e nunca marcava a caixa.
        # Grupos de checkbox são resolvidos antes, no orquestrador; aqui cobrimos
        # o checkbox isolado que não é aceite nem documento.
        if (
            semantic_type in (SemanticType.UNKNOWN, SemanticType.DESCONHECIDO)
            and field is not None
            and field.field_type == FieldType.CHECKBOX
        ):
            return "false"

        # Partes de endereço — usa parsing do perfil com coerência de sessão
        if semantic_type in (
            SemanticType.LOGRADOURO, SemanticType.NUMERO_ENDERECO,
            SemanticType.COMPLEMENTO, SemanticType.BAIRRO,
        ):
            return self._get_addr_part(semantic_type)

        # 1. Tenta dado real do perfil
        if self._profile:
            real = self._profile.get(semantic_type)
            if real:
                # Para nome fantasia: se igual à razão social (caso MEI / empresário individual),
                # gera um nome fantasia fictício para que os campos não sejam idênticos no form.
                if (
                    semantic_type == SemanticType.NOME_FANTASIA
                    and real == self._profile.razao_social
                ):
                    real = None  # força fallback fake
                else:
                    if semantic_type in (SemanticType.RAZAO_SOCIAL, SemanticType.NOME_FANTASIA):
                        if self._company_name is None:
                            self._company_name = real
                    return real

        # 2. Email real via COMPANY_EMAIL env var
        if semantic_type in (SemanticType.EMAIL_GENERICO, SemanticType.EMAIL_CORPORATIVO):
            if self._company_email:
                return self._company_email

        # 3. Fallback: dado fake com memória de sessão
        value = self._produce_fake(semantic_type)
        if semantic_type in (SemanticType.RAZAO_SOCIAL, SemanticType.NOME_FANTASIA):
            if self._company_name is None:
                self._company_name = value
        return value

    def _get_addr_part(self, semantic_type: SemanticType) -> str:
        self._ensure_addr_parts()
        match semantic_type:
            case SemanticType.LOGRADOURO:
                return self._addr_logradouro or ""
            case SemanticType.NUMERO_ENDERECO:
                return self._addr_numero or ""
            case SemanticType.COMPLEMENTO:
                return self._addr_complemento or ""
            case SemanticType.BAIRRO:
                return self._addr_bairro or ""
            case _:
                return ""

    def _ensure_addr_parts(self) -> None:
        """Carrega/parseia as partes do endereço uma única vez por sessão.

        Carrega o que o perfil oferece e completa as partes faltantes com
        valores fake — assim, se a extração do cartão CNPJ não pegou o bairro,
        o campo não fica vazio no formulário.
        """
        if self._addr_loaded:
            return
        self._addr_loaded = True

        p = self._profile
        if p:
            if p.logradouro:
                self._addr_logradouro = p.logradouro
                self._addr_numero = p.numero_endereco or self._addr_numero
                self._addr_complemento = p.complemento or self._addr_complemento
            elif p.endereco:
                # Tenta parsear o endereço completo: "RUA DAS FLORES 350 SALA 4"
                m = re.match(
                    r'^(.+?)\s+(\d[\dA-Z/-]*|S/?N)\s*,?\s*(.*)$',
                    p.endereco.strip(),
                    re.I,
                )
                if m:
                    self._addr_logradouro = m.group(1).strip().rstrip(",").strip().title()
                    self._addr_numero = m.group(2).strip().rstrip(",").strip()
                    self._addr_complemento = m.group(3).strip().lstrip(",").strip()
                else:
                    # Sem número identificável → usa o endereço inteiro como logradouro
                    self._addr_logradouro = p.endereco.strip().title()
            # Bairro é independente — pode vir do perfil mesmo sem logradouro
            if p.bairro:
                self._addr_bairro = p.bairro

        # Completa partes faltantes com fakes (gerados uma vez por sessão)
        if not self._addr_logradouro:
            self._addr_logradouro = fake.street_name()
        if not self._addr_numero:
            self._addr_numero = fake.building_number()
        if not self._addr_bairro:
            self._addr_bairro = fake.bairro() if hasattr(fake, "bairro") else ""
        if self._addr_complemento is None:
            self._addr_complemento = ""

    def _document_available(self, field: FormField) -> str:
        """Retorna 'true' se o documento descrito no label do checkbox está no perfil."""
        if self._profile is None:
            return "true"
        label = (field.label or "").lower()
        if "cnpj" in label:
            return "true" if self._profile.cnpj else "false"
        if any(k in label for k in ["contrato social", "alteração contratual"]):
            return "true" if (self._profile.nome_socio_principal or self._profile.objeto_social) else "false"
        if any(k in label for k in ["demonstrações financeiras", "balanço", "dre"]):
            return "true" if (self._profile.banco or self._profile.faturamento_anual) else "false"
        # Documento não identificado no perfil → não declarar que temos
        return "false"

    def _produce_fake(self, semantic_type: SemanticType) -> str:
        if semantic_type == SemanticType.EMAIL_CORPORATIVO:
            company = self._company_name or fake.company()
            return company_email(company)
        return generate(semantic_type)