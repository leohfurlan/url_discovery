import asyncio
import os

import pytest
from dotenv import load_dotenv

load_dotenv()

from domain.entities.form import FieldType, FormField, SemanticType
from infrastructure.llm.gemma_adapter import GemmaClassifier


def make_classifier() -> GemmaClassifier:
    return GemmaClassifier.__new__(GemmaClassifier)


class TestExtractHints:
    def test_extract_hints(self):
        classifier = make_classifier()
        fields = [
            FormField(
                tag="input",
                field_type=FieldType.TEXT,
                label="CNPJ",
                name="document",
                id="cnpj",
                placeholder="00.000.000/0000-00",
                selector="#cnpj",
            ),
            FormField(
                tag="input",
                field_type=FieldType.EMAIL,
                label="E-mail",
                selector="#email",
            ),
        ]

        assert classifier._extract_hints(fields) == [
            {
                "index": 0,
                "field_type": "text",
                "label": "CNPJ",
                "name": "document",
                "id": "cnpj",
                "placeholder": "00.000.000/0000-00",
            },
            {"index": 1, "field_type": "email", "label": "E-mail"},
        ]


class TestReconstruct:
    def test_reconstruct_preenche_semantic_type(self):
        classifier = make_classifier()
        fields = [
            FormField(
                tag="input",
                field_type=FieldType.TEXT,
                label="CNPJ",
                selector="#cnpj",
            )
        ]

        result = classifier._reconstruct(
            fields,
            [{"index": 0, "semantic_type": "cnpj"}],
        )

        assert result[0].semantic_type == SemanticType.CNPJ
        assert fields[0].semantic_type is None

    def test_reconstruct_usa_unknown_quando_tipo_for_invalido(self):
        classifier = make_classifier()
        fields = [
            FormField(
                tag="input",
                field_type=FieldType.TEXT,
                label="Campo estranho",
                selector="#campo",
            )
        ]

        result = classifier._reconstruct(
            fields,
            [{"index": 0, "semantic_type": "tipo_invalido"}],
        )

        assert result[0].semantic_type == SemanticType.UNKNOWN


class TestCallLlmSemChave:
    @pytest.mark.asyncio
    async def test_retorna_unknown_sem_gemini_api_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        classifier = make_classifier()

        result = await classifier._call_llm([{"index": 0, "label": "CNPJ"}])

        assert result == [{"index": 0, "semantic_type": "unknown"}]


class TestChooseOption:
    @pytest.mark.asyncio
    async def test_sem_api_key_retorna_none(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        classifier = make_classifier()
        field = FormField(
            tag="input", field_type=FieldType.RADIO, label="Porte",
            selector="#p", options=["ME", "EPP", "Grande"],
        )

        assert await classifier.choose_option(field, "razao_social: ACME") is None

    @pytest.mark.asyncio
    async def test_menos_de_duas_opcoes_retorna_none(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        classifier = make_classifier()
        field = FormField(
            tag="input", field_type=FieldType.RADIO, label="x",
            selector="#x", options=["única"],
        )

        assert await classifier.choose_option(field) is None


class TestChooseOptions:
    @pytest.mark.asyncio
    async def test_sem_api_key_retorna_lista_vazia(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        classifier = make_classifier()

        result = await classifier.choose_options(
            "Categoria", ["A", "B", "C"], "atividade: mineração",
        )

        assert result == []


@pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="Precisa de GEMINI_API_KEY para chamar o LLM real.",
)
class TestClassificarComLLM:
    @pytest.mark.asyncio
    async def test_classifica_cnpj(self):
        classifier = GemmaClassifier()
        fields = [
            FormField(
                tag="input",
                field_type=FieldType.TEXT,
                label="CNPJ",
                selector="#cnpj",
            )
        ]

        result = await classifier.classify(fields)
        

        assert result[0].semantic_type == SemanticType.CNPJ
