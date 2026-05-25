from domain.entities.company_profile import CompanyProfile
from domain.entities.form import SemanticType


def _perfil_completo() -> CompanyProfile:
    return CompanyProfile(
        cnpj="12.345.678/0001-99",
        razao_social="Vulcaflex Indústria S.A.",
        nome_fantasia="Vulcaflex",
        atividade="Fabricação de artefatos de borracha",
        endereco="Rua das Indústrias, 100",
        cep="95012-000",
        cidade="Caxias do Sul",
        estado="RS",
        telefone="(54) 3210-0000",
        inscricao_estadual="123/4567890",
        inscricao_municipal="987654",
        nome_socio_principal="João da Silva",
        cpf_socio_principal="123.456.789-09",
        objeto_social="Fabricação e comércio de mangueiras",
        banco="Bradesco",
        agencia="1234",
        conta="56789-0",
        favorecido="Vulcaflex Indústria S.A.",
    )


class TestGet:
    def test_retorna_cnpj(self):
        p = _perfil_completo()
        assert p.get(SemanticType.CNPJ) == "12.345.678/0001-99"

    def test_retorna_razao_social(self):
        p = _perfil_completo()
        assert p.get(SemanticType.RAZAO_SOCIAL) == "Vulcaflex Indústria S.A."

    def test_retorna_nome_fantasia(self):
        p = _perfil_completo()
        assert p.get(SemanticType.NOME_FANTASIA) == "Vulcaflex"

    def test_retorna_banco(self):
        p = _perfil_completo()
        assert p.get(SemanticType.BANCO) == "Bradesco"

    def test_retorna_agencia(self):
        p = _perfil_completo()
        assert p.get(SemanticType.AGENCIA) == "1234"

    def test_retorna_conta(self):
        p = _perfil_completo()
        assert p.get(SemanticType.CONTA) == "56789-0"

    def test_retorna_favorecido(self):
        p = _perfil_completo()
        assert p.get(SemanticType.FAVORECIDO) == "Vulcaflex Indústria S.A."

    def test_retorna_nome_socio(self):
        p = _perfil_completo()
        assert p.get(SemanticType.NOME_SOCIO) == "João da Silva"

    def test_retorna_cpf_socio(self):
        p = _perfil_completo()
        assert p.get(SemanticType.CPF_SOCIO) == "123.456.789-09"

    def test_retorna_none_para_campo_ausente(self):
        p = CompanyProfile(cnpj="12.345.678/0001-99")
        assert p.get(SemanticType.BANCO) is None

    def test_retorna_none_para_tipo_sem_mapeamento(self):
        p = _perfil_completo()
        assert p.get(SemanticType.ACEITE_TERMOS) is None

    def test_retorna_none_em_perfil_vazio(self):
        p = CompanyProfile()
        assert p.get(SemanticType.CNPJ) is None

    def test_atividade_direto(self):
        p = CompanyProfile(atividade="Comércio de borracha")
        assert p.get(SemanticType.ATIVIDADE) == "Comércio de borracha"

    def test_atividade_fallback_objeto_social(self):
        p = CompanyProfile(objeto_social="Fabricação e venda de mangueiras")
        assert p.get(SemanticType.ATIVIDADE) == "Fabricação e venda de mangueiras"

    def test_atividade_prefere_campo_proprio_ao_objeto_social(self):
        p = CompanyProfile(atividade="Fabricação", objeto_social="Outro")
        assert p.get(SemanticType.ATIVIDADE) == "Fabricação"

    def test_cpf_mapeia_para_socio_principal(self):
        p = CompanyProfile(cpf_socio_principal="111.222.333-44")
        assert p.get(SemanticType.CPF) == "111.222.333-44"

    def test_nome_pessoa_mapeia_para_socio_principal(self):
        p = CompanyProfile(nome_socio_principal="Maria Oliveira")
        assert p.get(SemanticType.NOME_PESSOA) == "Maria Oliveira"


class TestMerge:
    def test_self_tem_prioridade_sobre_other(self):
        a = CompanyProfile(cnpj="11.111.111/0001-11", razao_social="Empresa A")
        b = CompanyProfile(cnpj="22.222.222/0001-22", razao_social="Empresa B")
        merged = a.merge(b)
        assert merged.cnpj == "11.111.111/0001-11"
        assert merged.razao_social == "Empresa A"

    def test_preenche_campos_ausentes_do_other(self):
        a = CompanyProfile(cnpj="11.111.111/0001-11")
        b = CompanyProfile(banco="Itaú", agencia="0001")
        merged = a.merge(b)
        assert merged.cnpj == "11.111.111/0001-11"
        assert merged.banco == "Itaú"
        assert merged.agencia == "0001"

    def test_nao_sobrescreve_campo_preenchido_com_none(self):
        a = CompanyProfile(banco="Bradesco")
        b = CompanyProfile(banco=None)
        merged = a.merge(b)
        assert merged.banco == "Bradesco"

    def test_outros_campos_vazios_permanecem_none(self):
        a = CompanyProfile(cnpj="11.111.111/0001-11")
        b = CompanyProfile()
        merged = a.merge(b)
        assert merged.banco is None
        assert merged.conta is None


class TestIsEmpty:
    def test_perfil_vazio_retorna_true(self):
        assert CompanyProfile().is_empty() is True

    def test_perfil_com_dados_retorna_false(self):
        assert CompanyProfile(cnpj="12.345.678/0001-99").is_empty() is False

    def test_perfil_completo_retorna_false(self):
        assert _perfil_completo().is_empty() is False
