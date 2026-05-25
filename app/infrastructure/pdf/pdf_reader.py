from __future__ import annotations
import concurrent.futures
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
    disponível, usa OCR via Gemma Vision (necessário para PDFs escaneados).
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
        dica="PDF parece escaneado — forneça api_key para habilitar OCR via Gemma Vision",
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


_OCR_DPI_SCALE  = 300 / 72   # 300 DPI — recomendado pelo Gemma para documentos
_OCR_MAX_PAGES  = 10          # limite por chamada
_OCR_TIMEOUT_S  = 300         # segundos — Gemma leva ~2 min por chamada com 6 páginas PNG 300 DPI

_OCR_SYSTEM = (
    "You are a high-precision Document OCR Engine specialized in Brazilian "
    "commercial and financial documents (Receita Federal, Junta Comercial, banks)."
)

_OCR_PROMPT = """\
[TASK]
Analyze the provided sequence of images. These images represent all pages of a single document.
1. Synthesize information across all pages (e.g., a name on page 1 may relate to a signature on page 6).
2. Extract ALL visible text from the document, preserving the original structure.
3. If a field is not found, skip it.
4. For dates, use DD/MM/YYYY format.

[CONSTRAINTS]
- DO NOT provide any conversational text, preamble, or markdown formatting (no ```).
- Return ONLY the raw extracted text, exactly as it appears in the document."""


def _extract_ocr(path: Path, api_key: str, ocr_model: str) -> str:
    """Wrapper com timeout para nunca ficar pendurado independentemente de falha de rede."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_do_ocr, path, api_key, ocr_model)
        try:
            return future.result(timeout=_OCR_TIMEOUT_S)
        except concurrent.futures.TimeoutError:
            logger.warning("ocr_timeout", arquivo=path.name, timeout_s=_OCR_TIMEOUT_S)
            return ""


def _do_ocr(path: Path, api_key: str, ocr_model: str) -> str:
    """Converte páginas em PNG via pymupdf e envia ao Gemma via google-genai SDK.

    Usa GenerateContentConfig com system_instruction, temperature=0.01 e top_p=0.1
    conforme recomendado pelo Gemma para extração determinística de documentos.
    DPI 300 garante legibilidade de selos, carimbos e texto pequeno em documentos oficiais.
    """
    import fitz
    from google import genai
    from google.genai import types

    try:
        doc = fitz.open(str(path))
        n_pages = min(len(doc), _OCR_MAX_PAGES)
        mat = fitz.Matrix(_OCR_DPI_SCALE, _OCR_DPI_SCALE)

        contents: list = []
        for i in range(n_pages):
            pix = doc[i].get_pixmap(matrix=mat)
            contents.append(types.Part.from_bytes(data=pix.tobytes("png"), mime_type="image/png"))
        doc.close()

        contents.append(_OCR_PROMPT)

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=ocr_model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=_OCR_SYSTEM,
                temperature=0.01,
                top_p=0.1,
            ),
        )
        text = (response.text or "").strip()
        logger.info("ocr_concluido", arquivo=path.name, chars=len(text), modelo=ocr_model, paginas=n_pages)
        return text[:_MAX_TEXT_CHARS]

    except Exception as exc:
        logger.error("ocr_falhou", arquivo=path.name, erro=str(exc))
        return ""
