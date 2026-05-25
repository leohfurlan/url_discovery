from domain.entities.company_profile import DocumentType
from infrastructure.pdf.pdf_reader import detect_document_type


class TestDetectDocumentType:
    # ── Cartão CNPJ ──────────────────────────────────────────────────────────

    def test_detecta_cartao_cnpj_por_texto_receita_federal(self):
        texto = "MINISTÉRIO DA FAZENDA\nReceita Federal do Brasil\nCartão CNPJ"
        assert detect_document_type(texto, "doc.pdf") == DocumentType.CARTAO_CNPJ

    def test_detecta_cartao_cnpj_por_situacao_cadastral(self):
        texto = "Situação cadastral: ATIVA\nData de abertura: 01/01/2000"
        assert detect_document_type(texto, "doc.pdf") == DocumentType.CARTAO_CNPJ

    def test_detecta_cartao_cnpj_por_nome_arquivo(self):
        assert detect_document_type("", "cartao_cnpj_empresa.pdf") == DocumentType.CARTAO_CNPJ

    def test_detecta_cartao_cnpj_nome_arquivo_so_cnpj(self):
        assert detect_document_type("", "cnpj.pdf") == DocumentType.CARTAO_CNPJ

    # ── Contrato Social ───────────────────────────────────────────────────────

    def test_detecta_contrato_social_por_texto(self):
        texto = "CONTRATO SOCIAL da empresa XYZ Ltda"
        assert detect_document_type(texto, "doc.pdf") == DocumentType.CONTRATO_SOCIAL

    def test_detecta_alteracao_contratual_por_texto(self):
        texto = "Décima Segunda Alteração Contratual\nSócios presentes:"
        assert detect_document_type(texto, "doc.pdf") == DocumentType.CONTRATO_SOCIAL

    def test_detecta_contrato_social_por_nome_arquivo(self):
        assert detect_document_type("", "contrato_social_2024.pdf") == DocumentType.CONTRATO_SOCIAL

    def test_detecta_alteracao_por_nome_arquivo(self):
        assert detect_document_type("", "alteracao_contratual.pdf") == DocumentType.CONTRATO_SOCIAL

    # ── Demonstrações Financeiras ─────────────────────────────────────────────

    def test_detecta_demonstracoes_por_balanco(self):
        texto = "Balanço Patrimonial em 31/12/2024\nAtivo Circulante"
        assert detect_document_type(texto, "doc.pdf") == DocumentType.DEMONSTRACOES_FINANCEIRAS

    def test_detecta_demonstracoes_por_dre(self):
        texto = "Demonstração do Resultado do Exercício\nReceita Bruta"
        assert detect_document_type(texto, "doc.pdf") == DocumentType.DEMONSTRACOES_FINANCEIRAS

    def test_detecta_demonstracoes_por_passivo_circulante(self):
        texto = "Passivo Circulante\nPassivo Não Circulante\nPatrimônio Líquido"
        assert detect_document_type(texto, "doc.pdf") == DocumentType.DEMONSTRACOES_FINANCEIRAS

    def test_detecta_demonstracoes_por_nome_arquivo_dre(self):
        assert detect_document_type("", "dre_2024.pdf") == DocumentType.DEMONSTRACOES_FINANCEIRAS

    def test_detecta_demonstracoes_por_nome_arquivo_balanco(self):
        assert detect_document_type("", "balanco_2024.pdf") == DocumentType.DEMONSTRACOES_FINANCEIRAS

    # ── Prioridade texto > nome do arquivo ────────────────────────────────────

    def test_texto_tem_prioridade_sobre_nome_arquivo(self):
        # Nome diz "contrato" mas texto claramente é Cartão CNPJ
        texto = "Receita Federal do Brasil\nSituação cadastral: ATIVA"
        assert detect_document_type(texto, "contrato.pdf") == DocumentType.CARTAO_CNPJ

    # ── Desconhecido ──────────────────────────────────────────────────────────

    def test_retorna_desconhecido_sem_keywords(self):
        assert detect_document_type("Documento qualquer sem palavras reconhecidas.", "arquivo.pdf") == DocumentType.DESCONHECIDO

    def test_retorna_desconhecido_com_texto_e_nome_vazios(self):
        assert detect_document_type("", "") == DocumentType.DESCONHECIDO
