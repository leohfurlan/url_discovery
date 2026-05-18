from infrastructure.formaters import (
    company_email,
    format_cnpj,
    format_cpf,
    format_phone_number,
    format_zip_code,
)
import pytest


def test_format_cnpj():
    cnpj = "12345678000195"
    formatted = format_cnpj(cnpj)
    assert formatted == "12.345.678/0001-95"


def test_format_cnpj_com_caracteres():
    cnpj = "12.345.678/0001-95"
    formatted = format_cnpj(cnpj)
    assert formatted == "12.345.678/0001-95"


def test_format_cnpj_invalido():
    cnpj = "12345678"
    with pytest.raises(ValueError, match="CNPJ must have 14 digits"):
        format_cnpj(cnpj)


def test_format_cpf():
    cpf = "12345678909"
    formatted = format_cpf(cpf)
    assert formatted == "123.456.789-09"


def test_format_cpf_com_caracteres():
    cpf = "123.456.789-09"
    formatted = format_cpf(cpf)
    assert formatted == "123.456.789-09"


def test_format_cpf_invalido():
    cpf = "123456789"
    with pytest.raises(ValueError, match="CPF must have 11 digits"):
        format_cpf(cpf)


def test_format_phone_number_com_10_digitos():
    phone = "1134567890"
    formatted = format_phone_number(phone)
    assert formatted == "(11) 3456-7890"


def test_format_phone_number_com_11_digitos():
    phone = "11934567890"
    formatted = format_phone_number(phone)
    assert formatted == "(11) 93456-7890"


def test_format_phone_number_com_caracteres():
    phone = "(11) 93456-7890"
    formatted = format_phone_number(phone)
    assert formatted == "(11) 93456-7890"


def test_format_phone_number_invalido():
    phone = "123456789"
    with pytest.raises(ValueError, match="Phone number must have 10 or 11 digits"):
        format_phone_number(phone)


def test_format_zip_code():
    zip_code = "30140071"
    formatted = format_zip_code(zip_code)
    assert formatted == "30140-071"


def test_format_zip_code_com_caracteres():
    zip_code = "30140-071"
    formatted = format_zip_code(zip_code)
    assert formatted == "30140-071"


def test_format_zip_code_invalido():
    zip_code = "3014007"
    with pytest.raises(ValueError, match="Zip code must have 8 digits"):
        format_zip_code(zip_code)


def test_company_email_generico():
    email = company_email("Empresa Teste")
    assert email == "contact@empresa-teste.com.br"


def test_company_email_remove_acentos_e_sufixo_societario():
    email = company_email("São João LTDA")
    assert email == "contact@sao-joao.com.br"


def test_company_email_remove_caracteres_especiais_do_dominio():
    email = company_email("A&B Comércio ME")
    assert email == "contact@ab-comercio.com.br"


def test_company_email_com_nome_pessoa():
    email = company_email("Empresa Teste SA", "João Silva")
    assert email == "joao.silva@empresa-teste.com.br"
