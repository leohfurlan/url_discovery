from domain.entities.form import FormField, FieldType, SemanticType
from domain.services.classifier import classify_by_heuristic, classify


def test_classifica_cnpj():
    field = FormField(
        tag="input", field_type=FieldType.TEXT,
        label="CNPJ", selector="#cnpj"
    )
    assert classify_by_heuristic(field) == SemanticType.CNPJ


def test_classifica_razao_social():
    field = FormField(
        tag="input", field_type=FieldType.TEXT,
        label="Razão Social", selector="#razao"
    )
    assert classify_by_heuristic(field) == SemanticType.RAZAO_SOCIAL


def test_classifica_email_corporativo_antes_de_generico():
    field = FormField(
        tag="input", field_type=FieldType.EMAIL,
        label="E-mail Corporativo", selector="#email"
    )
    assert classify_by_heuristic(field) == SemanticType.EMAIL_CORPORATIVO


def test_classifica_email_generico():
    field = FormField(
        tag="input", field_type=FieldType.EMAIL,
        label="E-mail", selector="#email"
    )
    assert classify_by_heuristic(field) == SemanticType.EMAIL_GENERICO


def test_retorna_unknown_para_campo_sem_hint():
    field = FormField(
        tag="input", field_type=FieldType.TEXT,
        selector="#campo_misterioso"
    )
    assert classify_by_heuristic(field) == SemanticType.UNKNOWN


def test_classifica_telefone():
    field = FormField(
        tag="input", field_type=FieldType.TEL,
        label="Telefone de contato", selector="#tel"
    )
    assert classify_by_heuristic(field) == SemanticType.TELEFONE


def test_classify_chama_llm_para_unknown():
    field = FormField(
        tag="input", field_type=FieldType.TEXT,
        label="Identificação fiscal da pessoa jurídica",
        selector="#campo_ambiguo"
    )
    result = classify(field)
    assert result != SemanticType.UNKNOWN