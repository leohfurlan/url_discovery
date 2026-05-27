"""
Testes da classificação heurística local (infrastructure/llm/heuristic.py).

Cobrem especialmente as correções do Ajuste 2 (classificação com contexto):
- radio binário Sim/Não não deve capturar keywords estruturais do enunciado;
- declarações/aceites em campos de escolha têm prioridade sobre keywords;
- textarea (pergunta aberta) não deve virar dado estruturado.
"""
from domain.entities.form import FieldType, FormField, SemanticType
from infrastructure.llm.heuristic import (
    _TEXTAREA_BLOCKED,
    _is_binary_yes_no,
    heuristic_classify,
)


def _radio(label: str, options: list[str]) -> FormField:
    return FormField(
        tag="input", field_type=FieldType.RADIO,
        label=label, selector="#r", options=options,
    )


def _textarea(label: str) -> FormField:
    return FormField(
        tag="textarea", field_type=FieldType.TEXTAREA,
        label=label, selector="#t",
    )


class TestBinarioSimNao:
    def test_radio_binario_com_keyword_estrutural_vira_unknown(self):
        # Pergunta 15 do log: enunciado de compliance contendo "agência" não
        # pode ser classificado como agencia_bancaria.
        field = _radio(
            "Sua empresa esteve submetida à fiscalização de agência reguladora?",
            ["Sim", "Não"],
        )
        assert heuristic_classify(field) == SemanticType.UNKNOWN

    def test_radio_binario_com_nome_no_enunciado_vira_unknown(self):
        # Pergunta 16 do log: "Na prestação de serviço... em nome de..." não é nome_pessoa.
        field = _radio(
            "Na prestação de serviço você atua em nome de algum agente público?",
            ["Sim", "Não"],
        )
        assert heuristic_classify(field) == SemanticType.UNKNOWN

    def test_radio_binario_aceite_continua_aceite(self):
        field = _radio("Concordo com os termos e condições", ["Sim", "Não"])
        assert heuristic_classify(field) == SemanticType.ACEITE_TERMOS

    def test_pergunta_compliance_com_ciente_nao_vira_aceite(self):
        # Pergunta 9 do log: "Você está ciente de alguma questão de relacionamento
        # que possa gerar conflito?" NÃO é um aceite — marcar "Sim" seria perigoso.
        field = _radio(
            "Você está ciente de alguma questão de relacionamento que possa gerar conflito de interesses?",
            ["Sim", "Não"],
        )
        assert heuristic_classify(field) == SemanticType.UNKNOWN

    def test_is_binary_yes_no(self):
        assert _is_binary_yes_no(_radio("x", ["Sim", "Não"]))
        assert _is_binary_yes_no(_radio("x", ["yes", "no"]))
        assert not _is_binary_yes_no(_radio("x", ["PJ", "PF", "MEI"]))
        assert not _is_binary_yes_no(
            FormField(tag="input", field_type=FieldType.TEXT, label="x", selector="#x")
        )


class TestDeclaracaoEmEscolha:
    def test_declaracao_ciente_tem_prioridade_sobre_representante_legal(self):
        # Pergunta 4 do log: "Declaro estar ciente... na condição de representante
        # legal" virava NOME_SOCIO. Aceite deve vencer.
        field = _radio(
            "Declaro estar ciente, na condição de representante legal, das obrigações",
            ["Li e estou ciente"],
        )
        assert heuristic_classify(field) == SemanticType.ACEITE_TERMOS

    def test_checkbox_de_consentimento(self):
        field = FormField(
            tag="input", field_type=FieldType.CHECKBOX,
            label="Autorizo o tratamento dos meus dados pessoais",
            selector="#c",
        )
        assert heuristic_classify(field) == SemanticType.ACEITE_TERMOS


class TestTextareaPerguntaAberta:
    def test_textarea_com_palavra_endereco_nao_vira_endereco(self):
        # Pergunta 20 do log: textarea "Descreva..." capturava "endereço".
        field = _textarea(
            "Descreva o endereço eletrônico onde está publicado seu programa de integridade"
        )
        result = heuristic_classify(field)
        assert result != SemanticType.ENDERECO
        assert result is None or result not in _TEXTAREA_BLOCKED

    def test_endereco_em_textarea_esta_bloqueado(self):
        assert SemanticType.ENDERECO in _TEXTAREA_BLOCKED


class TestCamposEstruturaisAindaClassificam:
    def test_cnpj_text(self):
        field = FormField(tag="input", field_type=FieldType.TEXT, label="CNPJ", selector="#c")
        assert heuristic_classify(field) == SemanticType.CNPJ

    def test_numero_agencia_separado_classifica_agencia(self):
        # Após a correção do crawler o label vem com espaço ("Agência Texto..."),
        # então o word-boundary de AGENCIA volta a funcionar.
        field = FormField(
            tag="input", field_type=FieldType.TEXT,
            label="Número Agência Texto de linha única", selector="#a",
        )
        assert heuristic_classify(field) == SemanticType.AGENCIA

    def test_conta_corrente_classifica_conta(self):
        field = FormField(
            tag="input", field_type=FieldType.TEXT,
            label="Número Conta Corrente Texto de linha única", selector="#cc",
        )
        assert heuristic_classify(field) == SemanticType.CONTA
