"""
tests/test_run_supplier.py

Coleta e normalização do contexto de fornecedor (run.py). O prompt interativo
não é exercido aqui (sem TTY no pytest); cobrimos a normalização e o fato de
que --headless / ausência de flags não trava nem inventa valores.
"""
from run import _collect_supplier_info, _normalize_supplier_kind


class TestNormalizeSupplierKind:
    def test_variantes_de_materiais(self):
        assert _normalize_supplier_kind("Materiais") == "materiais"
        assert _normalize_supplier_kind("produtos") == "materiais"

    def test_variantes_de_servicos(self):
        assert _normalize_supplier_kind("Serviços") == "serviços"
        assert _normalize_supplier_kind("servico") == "serviços"

    def test_ambos(self):
        assert _normalize_supplier_kind("ambos") == "ambos"
        assert _normalize_supplier_kind("materiais e serviços") == "ambos"

    def test_none(self):
        assert _normalize_supplier_kind(None) is None

    def test_valor_desconhecido_preserva_texto(self):
        assert _normalize_supplier_kind("  outra coisa  ") == "outra coisa"


class TestCollectSupplierInfo:
    def test_flags_fornecidas_sao_normalizadas(self):
        kind, desc = _collect_supplier_info("Materiais", "  Bombas e válvulas ")
        assert kind == "materiais"
        assert desc == "Bombas e válvulas"

    def test_sem_flags_retorna_none_sem_prompt(self):
        # Sem flags o agente segue sem contexto e sem perguntar nada.
        kind, desc = _collect_supplier_info(None, None)
        assert kind is None and desc is None

    def test_descricao_vazia_vira_none(self):
        kind, desc = _collect_supplier_info("servicos", "   ")
        assert kind == "serviços"
        assert desc is None
