"""
Valida a extração de dados dos PDFs em docs/ via DocumentExtractor.

Uso:
    python app/validate_docs.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Garante que app/ está no sys.path (necessário para imports relativos)
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from domain.services.document_extractor import DocumentExtractor

_DOCS_DIR = Path(__file__).parents[1] / "docs"
_API_KEY   = os.getenv("GEMINI_API_KEY")

def main() -> None:
    if not _DOCS_DIR.is_dir():
        print(f"[ERRO] Pasta docs/ nao encontrada em: {_DOCS_DIR}")
        sys.exit(1)

    pdfs = list(_DOCS_DIR.glob("*.pdf"))
    if not pdfs:
        print("[AVISO] Nenhum PDF encontrado em docs/")
        sys.exit(0)

    print(f"PDFs encontrados: {[p.name for p in pdfs]}\n")

    extractor = DocumentExtractor(api_key=_API_KEY)
    profile = extractor.load_from_directory(_DOCS_DIR)

    print("\n" + "=" * 60)
    print("  COMPANY PROFILE EXTRAIDO")
    print("=" * 60)

    fields = {
        "CNPJ":                 profile.cnpj,
        "Razao Social":         profile.razao_social,
        "Nome Fantasia":        profile.nome_fantasia,
        "Atividade":            profile.atividade,
        "Endereco":             profile.endereco,
        "CEP":                  profile.cep,
        "Cidade":               profile.cidade,
        "Estado":               profile.estado,
        "Telefone":             profile.telefone,
        "Inscricao Estadual":   profile.inscricao_estadual,
        "Inscricao Municipal":  profile.inscricao_municipal,
        "Socio Principal":      profile.nome_socio_principal,
        "CPF Socio":            profile.cpf_socio_principal,
        "Objeto Social":        profile.objeto_social,
        "Banco":                profile.banco,
        "Agencia":              profile.agencia,
        "Conta":                profile.conta,
        "Favorecido":           profile.favorecido,
        "Faturamento Anual":    profile.faturamento_anual,
        "Periodo Referencia":   profile.periodo_referencia,
    }

    preenchidos = 0
    for label, value in fields.items():
        status = "[OK]  " if value else "[----]"
        display = value if value else "(nao extraido)"
        print(f"  {status} {label:<22} {display}")
        if value:
            preenchidos += 1

    print("=" * 60)
    print(f"  Campos preenchidos: {preenchidos}/{len(fields)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
