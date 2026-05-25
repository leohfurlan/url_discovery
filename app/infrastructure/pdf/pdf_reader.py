from __future__ import annotations
import base64
import structlog
from pathlib import Path
from domain.entities.company_profile import DocumentType

logger = structlog.get_logger(__name__)

_MIN_TEXT_CHARS = 80
_MAX_TEXT_CHARS = 10_000

_CARTAO_CNPJ_KEYWORDS = [
    "receita federal", "cartão cnpj", "comprovante cnpj",
    "situação cadastral", "data de abertura", "capital social",
]
_CONTRATO_SOCIAL_KEYWORDS = [
    "contrato social", "alteração contratual", "ato constitutivo",
    "estatuto social", "instrumento particular",
]
_DEMONSTRACOES_KEYWORDS = [
    # Demonstrações financeiras formais
    "demonstrações financeiras", "balanço patrimonial", "demonstração do resultado",
    "dre", "balancete", "ativo circulante", "passivo circulante",
    # Extratos bancários
    "saldo inicial", "saldo final", "total de entradas", "total de saídas",
    "movimentações", "extrato",
]

# Keywords de nome de arquivo que indicam extrato ou documento bancário
_EXTRATO_FILENAME_KEYWORDS = [
    "extrato", "nubank", "itau", "itaú", "bradesco", "santander",
    "bb", "caixa", "sicoob", "sicredi", "inter", "c6bank",
]


def extract_text(
    path: Path,
    api_key: str | None = None,
    ocr_model: str = "gemma-4-26b-a4b-it",
) -> str:
    """Extrai texto de um PDF.

    Tenta pdfplumber primeiro. Se o resultado for muito curto e api_key estiver
    disponível, usa OCR via Gemini Vision (necessário para PDFs escaneados).
    """
    text = _extract_pdfplumber(path)
    if len(text) >= _MIN_TEXT_CHARS:
        return text

    if api_key:
        logger.info("pdf_escaneado_tentando_ocr", arquivo=path.name, chars_pdfplumber=len(text))
        return _extract_ocr(path, api_key, ocr_model)

    logger.warning(
        "pdf_texto_insuficiente",
        arquivo=path.name,
        chars=len(text),
        dica="PDF parece escaneado — forneça api_key para habilitar OCR via Gemini Vision",
    )
    return text


def detect_document_type(text: str, filename: str) -> DocumentType:
    """Detecta o tipo de documento por palavras-chave no texto e no nome do arquivo.

    Prioridade: texto > nome do arquivo. Retorna DESCONHECIDO se não identificar.
    """
    text_lower = text.lower()
    name_lower = filename.lower()

    def _match(keywords: list[str], source: str) -> bool:
        return any(kw in source for kw in keywords)

    if _match(_CARTAO_CNPJ_KEYWORDS, text_lower) or _match(["cnpj", "cartao_cnpj", "cartão_cnpj"], name_lower):
        return DocumentType.CARTAO_CNPJ

    if _match(_CONTRATO_SOCIAL_KEYWORDS, text_lower) or _match(["contrato", "alteracao", "alteração"], name_lower):
        return DocumentType.CONTRATO_SOCIAL

    if (
        _match(_DEMONSTRACOES_KEYWORDS, text_lower)
        or _match(["dre", "balanco", "balanço", "demonstracao", "financ"], name_lower)
        or _match(_EXTRATO_FILENAME_KEYWORDS, name_lower)
    ):
        return DocumentType.DEMONSTRACOES_FINANCEIRAS

    logger.warning("documento_tipo_desconhecido", arquivo=filename)
    return DocumentType.DESCONHECIDO


# ── Implementações internas ───────────────────────────────────────────────────

def _extract_pdfplumber(path: Path) -> str:
    import pdfplumber

    pages_text: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            pages_text.append(page.extract_text() or "")
    return "\n".join(pages_text).strip()[:_MAX_TEXT_CHARS]


_OCR_DPI_SCALE = 150 / 72   # 150 DPI — boa qualidade para documentos impressos
_OCR_MAX_PAGES = 10          # evita enviar PDFs muito longos ao modelo


def _extract_ocr(path: Path, api_key: str, ocr_model: str) -> str:
    """Converte cada página do PDF em PNG via pymupdf e envia ao Gemma Vision para OCR.

    Usar imagens (image/png) em vez do PDF bruto (application/pdf) é mais
    confiável porque todos os modelos de visão aceitam imagens, independente
    de suportarem ou não PDF como tipo de entrada direto.
    """
    import fitz  # pymupdf
    from google import genai as google_genai

    try:
        doc = fitz.open(str(path))
        n_pages = min(len(doc), _OCR_MAX_PAGES)
        mat = fitz.Matrix(_OCR_DPI_SCALE, _OCR_DPI_SCALE)

        contents: list = []
        for i in range(n_pages):
            pix = doc[i].get_pixmap(matrix=mat)
            img_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
            contents.append({
                "inline_data": {"mime_type": "image/png", "data": img_b64}
            })
        doc.close()

        contents.append(
            "Extraia todo o texto deste documento. Retorne apenas o texto puro, sem formatação adicional."
        )

        client = google_genai.Client(api_key=api_key)
        response = client.models.generate_content(model=ocr_model, contents=contents)
        text = (response.text or "").strip()
        logger.info("ocr_concluido", arquivo=path.name, chars=len(text), modelo=ocr_model, paginas=n_pages)
        return text[:_MAX_TEXT_CHARS]

    except Exception as exc:
        logger.error("ocr_falhou", arquivo=path.name, erro=str(exc))
        return ""
