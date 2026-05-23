from __future__ import annotations
from faker import Faker
from domain.entities.form import SemanticType
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

        case SemanticType.TEXTO_LIVRE:
            return fake.sentence(nb_words=6)

        case _:
            return fake.word()


class DataGenerator:
    """Gerador com memória de sessão para manter coerência entre campos relacionados."""

    def __init__(self) -> None:
        self._company_name: str | None = None

    def generate(self, semantic_type: SemanticType) -> str:
        value = self._produce(semantic_type)
        if semantic_type in (SemanticType.RAZAO_SOCIAL, SemanticType.NOME_FANTASIA):
            if self._company_name is None:
                self._company_name = value
        return value

    def _produce(self, semantic_type: SemanticType) -> str:
        if semantic_type == SemanticType.EMAIL_CORPORATIVO:
            company = self._company_name or fake.company()
            return company_email(company)
        return generate(semantic_type)