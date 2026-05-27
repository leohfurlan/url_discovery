"""
tests/test_navigator_fallback.py

Testes do fallback inteligente para campos sem classificação (Ajuste 1):
NavigationOrchestrator._resolve_value.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from domain.entities.form import FieldType, FormField, SemanticType
from domain.services.generator import DataGenerator
from infrastructure.browser.navigator import NavigationOrchestrator


def _orchestrator(classifier) -> NavigationOrchestrator:
    return NavigationOrchestrator(
        page=MagicMock(),
        classifier=classifier,
        generator=DataGenerator(profile=None),
    )


def _stub_classifier(choice):
    c = MagicMock()
    c.choose_option = AsyncMock(return_value=choice)
    return c


def _radio(options, semantic=SemanticType.UNKNOWN, label="Tipo de Fornecedor"):
    return FormField(
        tag="input", field_type=FieldType.RADIO, label=label,
        name="g", selector='input[type="radio"][name="g"]',
        options=options, semantic_type=semantic,
    )


class TestResolveValueFallback:
    async def test_unknown_multiopcao_usa_escolha_do_llm(self):
        classifier = _stub_classifier("Materiais e Serviços")
        orch = _orchestrator(classifier)
        field = _radio(["Materiais", "Serviços", "Materiais e Serviços"])

        value = await orch._resolve_value(field)

        assert value == "Materiais e Serviços"
        classifier.choose_option.assert_awaited_once()
        assert orch._review_queue == []

    async def test_unknown_multiopcao_sem_decisao_vai_para_revisao(self):
        classifier = _stub_classifier(None)
        orch = _orchestrator(classifier)
        field = _radio(["PJ", "PF", "MEI"])

        value = await orch._resolve_value(field)

        assert value is None  # não preenche — não chuta
        assert orch._review_queue == [field]

    async def test_radio_binario_unknown_mantem_nao(self):
        classifier = _stub_classifier("qualquer")
        orch = _orchestrator(classifier)
        field = _radio(["Sim", "Não"], label="A empresa já cometeu crime?")

        value = await orch._resolve_value(field)

        assert value == "Não"
        classifier.choose_option.assert_not_awaited()  # binário não vai ao LLM
        assert orch._review_queue == []

    async def test_campo_classificado_nao_chama_fallback(self):
        classifier = _stub_classifier("x")
        orch = _orchestrator(classifier)
        field = FormField(
            tag="input", field_type=FieldType.TEXT, label="CNPJ",
            selector="#cnpj", semantic_type=SemanticType.CNPJ,
        )

        value = await orch._resolve_value(field)

        assert value  # gerou um CNPJ fake
        classifier.choose_option.assert_not_awaited()

    async def test_unknown_radio_com_duas_opcoes_nao_binarias_nao_dispara(self):
        # <=2 opções: não há ambiguidade suficiente para gastar uma chamada de LLM;
        # cai no caminho normal (radio unknown → "Não").
        classifier = _stub_classifier("x")
        orch = _orchestrator(classifier)
        field = _radio(["Opção A", "Opção B"])

        value = await orch._resolve_value(field)

        classifier.choose_option.assert_not_awaited()
        assert value == "Não"
