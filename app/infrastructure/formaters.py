import re
import unicodedata

def format_cnpj(cnpj: str) -> str:
    """Formata o número do CNPJ para o formato padrão: 00.000.000/0000-00"""
    cnpj = re.sub(r'\D', '', cnpj)  # Remove all non-digit characters
    if len(cnpj) != 14:
        raise ValueError("CNPJ must have 14 digits")
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:14]}"

def format_cpf(cpf: str) -> str:
    """Formata o número do CPF para o formato padrão: 000.000.000-00"""
    cpf = re.sub(r'\D', '', cpf)  # Remove all non-digit characters
    if len(cpf) != 11:
        raise ValueError("CPF must have 11 digits")
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:11]}"

def format_phone_number(phone: str) -> str:
    """Formata o número de telefone para o formato padrão: (00) 00000-0000"""
    phone = re.sub(r'\D', '', phone)  # Remove all non-digit characters
    if len(phone) == 10:
        return f"({phone[:2]}) {phone[2:6]}-{phone[6:10]}"
    elif len(phone) == 11:  # Formato com DDD
        return f"({phone[:2]}) {phone[2:7]}-{phone[7:]}"
    else:
        raise ValueError("Phone number must have 10 or 11 digits")

def format_zip_code(zip_code: str) -> str:
    """Formata o CEP para o formato padrão: 00000-000"""
    zip_code = re.sub(r'\D', '', zip_code)  # Remove all non-digit characters
    if len(zip_code) != 8:
        raise ValueError("Zip code must have 8 digits")
    return f"{zip_code[:5]}-{zip_code[5:]}"

def remover_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFD", texto.lower())
    return normalizado.encode("ascii", "ignore").decode("ascii")

def company_email(company_name: str, person_name: str | None = None) -> str:
    """Gera um email genérico para a empresa com base no domínio"""
    domain = remover_acentos(company_name).lower()
    domain = re.sub(r'\s+', '-', domain)
    domain = re.sub(r'[^a-z0-9-]', '', domain)
    for sufixo in ['-ltda', '-sa', '-eireli', '-me', '-epp']:
        domain = domain.removesuffix(sufixo)
    if person_name:
        name_part = remover_acentos(person_name).replace(" ", ".").lower()
        return f"{name_part}@{domain}.com.br"
    return f"contact@{domain}.com.br"