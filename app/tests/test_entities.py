from domain.entities.form import (
    FieldType,
    SemanticType,
    FormField,
    FormPage,
    FormSession,
    ExecutionResult,
)

def test_form_field_criacao_minima():
    field = FormField(
        tag="input",
        field_type=FieldType.TEXT,
        selector="#razao_social",
    )
    assert field.semantic_type is None
    assert field.generated_value is None
    assert field.options == []
    assert field.required is False

def test_semantic_hint_combina_campos_disponiveis():
    field = FormField(
        tag="input",
        field_type=FieldType.TEXT,
        selector="#campo",
        label="Razão Social",
        name="company_name",
    )
    assert field.semantic_hint == "Razão Social | company_name"


def test_semantic_hint_ignora_nulos():
    field = FormField(
        tag="input",
        field_type=FieldType.TEXT,
        selector="#campo",
        label="CNPJ",
    )
    assert field.semantic_hint == "CNPJ"


def test_form_session_pending_fields():
    field_preenchido = FormField(
        tag="input", field_type=FieldType.TEXT,
        selector="#a", generated_value="Empresa X"
    )
    field_vazio = FormField(
        tag="input", field_type=FieldType.TEXT,
        selector="#b"
    )
    session = FormSession(
        portal="teste",
        url="https://exemplo.com",
        pages=[FormPage(number=1, fields=[field_preenchido, field_vazio])]
    )
    assert len(session.pending_fields()) == 1
    assert session.pending_fields()[0].selector == "#b"