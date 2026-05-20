from domain.entities.form import SemanticType
from domain.services.generator import generate


def test_gera_cnpj_formatado():
    valor = generate(SemanticType.CNPJ)
    assert "/" in valor and "-" in valor and "." in valor


def test_gera_cpf_formatado():
    valor = generate(SemanticType.CPF)
    assert "." in valor and "-" in valor


def test_gera_email_corporativo_com_dominio():
    valor = generate(SemanticType.EMAIL_CORPORATIVO)
    assert "@" in valor
    assert "gmail" not in valor
    assert "outlook" not in valor


def test_gera_telefone_formatado():
    valor = generate(SemanticType.TELEFONE)
    assert "(" in valor and ")" in valor


def test_gera_cep_formatado():
    valor = generate(SemanticType.CEP)
    assert "-" in valor


def test_gera_razao_social_nao_vazio():
    valor = generate(SemanticType.RAZAO_SOCIAL)
    assert len(valor) > 0


def test_gera_aceite_termos():
    valor = generate(SemanticType.ACEITE_TERMOS)
    assert valor == "true"


def test_fallback_unknown():
    valor = generate(SemanticType.UNKNOWN)
    assert len(valor) > 0