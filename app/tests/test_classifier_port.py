"""
tests/test_classifier_port.py

Garante que o contrato do ClassifierPort permite preencher semantic_type e a
instrumentação de confiança (Ajuste 4), mas ainda barra alterações indevidas
de outros atributos do campo.
"""
from __future__ import annotations

from collections.abc import Sequence

import pytest

from domain.entities.form import FieldType, FormField, SemanticType
from domain.services.classifier_port import ClassifierContractError, ClassifierPort


class _ConfidenceClassifier(ClassifierPort):
    async def _classify(self, fields: Sequence[FormField]) -> list[FormField]:
        return [
            f.model_copy(update={
                "semantic_type": SemanticType.CNPJ,
                "confidence": "high",
                "classification_source": "classified",
            })
            for f in fields
        ]


class _TamperingClassifier(ClassifierPort):
    async def _classify(self, fields: Sequence[FormField]) -> list[FormField]:
        # Altera o label — proibido pelo contrato.
        return [
            f.model_copy(update={"semantic_type": SemanticType.CNPJ, "label": "outro"})
            for f in fields
        ]


def _field() -> FormField:
    return FormField(tag="input", field_type=FieldType.TEXT, label="CNPJ", selector="#c")


class TestContrato:
    async def test_permite_semantic_e_confianca(self):
        result = await _ConfidenceClassifier().classify([_field()])
        assert result[0].semantic_type == SemanticType.CNPJ
        assert result[0].confidence == "high"
        assert result[0].classification_source == "classified"

    async def test_barra_alteracao_de_outros_campos(self):
        with pytest.raises(ClassifierContractError):
            await _TamperingClassifier().classify([_field()])
