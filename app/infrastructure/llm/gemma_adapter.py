from __future__ import annotations

import asyncio
import json
import os
import structlog
from google import genai as google_genai
from dotenv import load_dotenv

from domain.entities.form import FieldType, FormField, SemanticType
from domain.services.classifier_port import ClassifierPort
from infrastructure.llm.heuristic import _TEXTAREA_BLOCKED, _is_binary_yes_no, heuristic_classify
from infrastructure.llm import cls_cache as cache

logger = structlog.get_logger(__name__)

# Semantics plausíveis para um radio binário Sim/Não. Qualquer outro tipo
# (agencia_bancaria, nome_pessoa, endereco...) é match espúrio de keyword num
# enunciado de compliance — rejeitado em favor de UNKNOWN.
_BINARY_RADIO_ALLOWED: set[SemanticType] = {
    SemanticType.ACEITE_TERMOS,
    SemanticType.UNKNOWN,
    SemanticType.DESCONHECIDO,
}


def _sanitize(field: FormField) -> FormField:
    """Corrige classificações impossíveis dado o tipo do campo.

    - textarea não pode ser e-mail, CNPJ, endereço e demais dados estruturados;
    - radio binário Sim/Não só pode ser aceite/declaração ou unknown.
    Vale para qualquer fonte (heurística, cache ou LLM).
    """
    if field.field_type == FieldType.TEXTAREA and field.semantic_type in _TEXTAREA_BLOCKED:
        return field.model_copy(update={"semantic_type": SemanticType.TEXTO_LIVRE})
    if _is_binary_yes_no(field) and field.semantic_type not in _BINARY_RADIO_ALLOWED:
        return field.model_copy(update={"semantic_type": SemanticType.UNKNOWN})
    return field


class GemmaClassifier(ClassifierPort):

    def __init__(self, model: str = "gemma-4-26b-a4b-it", api_key: str | None = None):
        load_dotenv()
        self._client = google_genai.Client(api_key=api_key or os.getenv("GEMINI_API_KEY"))
        self._model = model

    async def _classify(self, fields: list[FormField]) -> list[FormField]:
        result: list[FormField | None] = [None] * len(fields)
        llm_indices: list[int] = []

        for i, field in enumerate(fields):
            # 1. Heurística local (sem API)
            semantic = heuristic_classify(field)
            if semantic is not None:
                result[i] = field.model_copy(update={"semantic_type": semantic})
                continue

            # 2. Cache persistente (LLM já respondeu antes)
            fp = cache.fingerprint(field)
            cached = cache.get(fp)
            if cached is not None:
                result[i] = field.model_copy(update={"semantic_type": cached})
                continue

            llm_indices.append(i)

        n_llm = len(llm_indices)
        n_resolved = len(fields) - n_llm
        logger.debug(
            "classificacao",
            total=len(fields),
            resolvidos_localmente=n_resolved,
            para_llm=n_llm,
        )

        # 3. LLM só para os campos sem resposta
        if llm_indices:
            llm_fields = [fields[i] for i in llm_indices]
            hints = self._extract_hints(llm_fields)
            raw = await self._call_llm(hints)
            classified_llm = self._reconstruct(llm_fields, raw)

            to_cache: list[tuple[str, SemanticType]] = []
            for orig_i, classified_field in zip(llm_indices, classified_llm):
                result[orig_i] = classified_field
                if classified_field.semantic_type not in (SemanticType.UNKNOWN, None):
                    to_cache.append((cache.fingerprint(fields[orig_i]), classified_field.semantic_type))

            if to_cache:
                cache.put_batch(to_cache)

        return [
            _sanitize(r if r is not None else field.model_copy(update={"semantic_type": SemanticType.UNKNOWN}))
            for r, field in zip(result, fields)
        ]

    def _extract_hints(self, fields: list[FormField]) -> list[dict]:
        hints = []
        for index, field in enumerate(fields):
            hint = {"index": index}
            hint["field_type"] = field.field_type.value
            if field.label:       hint["label"] = field.label
            if field.name:        hint["name"] = field.name
            if field.id:          hint["id"] = field.id
            if field.placeholder: hint["placeholder"] = field.placeholder
            if field.options:     hint["options"] = list(field.options)
            hints.append(hint)
        return hints

    async def _call_llm(self, hints: list[dict]) -> list[dict]:
        if not hints or not os.getenv("GEMINI_API_KEY"):
            return [
                {"index": hint["index"], "semantic_type": SemanticType.UNKNOWN.value}
                for hint in hints
            ]

        semantic_types = [semantic_type.value for semantic_type in SemanticType]
        campos_formatados = "\n".join(
            f"{hint['index']} | "
            + " | ".join(
                f"{key}: {value}" for key, value in hint.items() if key != "index"
            )
            for hint in hints
        )

        prompt = f"""
Você é um classificador de campos de formulários web brasileiros.

Cada campo traz: field_type (tipo do input), label (enunciado completo da pergunta),
name, id, placeholder e options. Classifique pela INTENÇÃO da pergunta inteira — nunca
por uma palavra solta no meio de um enunciado longo de compliance.

Tipos disponíveis (escolha exatamente um por campo):
{json.dumps(semantic_types, ensure_ascii=False)}

Regras:
- field_type "radio" com opções Sim/Não: use "aceite_termos" apenas se for um aceite,
  declaração ou consentimento; em qualquer pergunta de compliance/integridade use "unknown".
- field_type "textarea" ou pergunta aberta ("descreva", "justifique", "explique"): use "texto_livre".
- Dados estruturados (cnpj, cpf, agencia_bancaria, conta_bancaria, endereco, cep...) só se o
  campo realmente coletar aquele dado — não se a palavra apenas aparece no texto da pergunta.
- Na dúvida, responda "unknown". É preferível "unknown" honesto a um tipo plausível errado.

Retorne somente JSON válido, sem markdown, neste formato:
[{{"index": 0, "semantic_type": "cnpj"}}]

Campos:
{campos_formatados}
""".strip()

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config={"response_mime_type": "application/json"},
                )
                break
            except Exception as exc:
                last_exc = exc
                if attempt < 2 and "500" in str(exc):
                    delay = 2 ** attempt
                    logger.warning("llm_retry", attempt=attempt + 1, delay=delay, error=str(exc))
                    await asyncio.sleep(delay)
                    continue
                raise
        else:
            raise last_exc  # type: ignore[misc]

        try:
            raw = json.loads(response.text or "[]")
        except json.JSONDecodeError:
            raw = []

        by_index = {
            item.get("index"): item.get("semantic_type")
            for item in raw
            if isinstance(item, dict)
        }

        return [
            {
                "index": hint["index"],
                "semantic_type": (
                    by_index.get(hint["index"])
                    if by_index.get(hint["index"]) in semantic_types
                    else SemanticType.UNKNOWN.value
                ),
            }
            for hint in hints
        ]

    async def choose_option(self, field: FormField, profile_summary: str = "") -> str | None:
        """Escolhe a opção mais coerente com o perfil para um campo não classificado.

        Faz UMA chamada ao LLM passando o enunciado, as opções e o perfil da empresa.
        Retorna o texto de uma das opções, ou None se nada se aplica claramente
        (sinaliza ao orquestrador que o campo precisa de revisão humana).
        """
        options = list(field.options)
        if len(options) < 2 or not os.getenv("GEMINI_API_KEY"):
            return None

        numbered = "\n".join(f"{i}: {opt}" for i, opt in enumerate(options))
        prompt = f"""
Você ajuda a preencher o cadastro de uma empresa fornecedora num portal.

Perfil da empresa:
{profile_summary or "(sem dados — escolha pela coerência geral)"}

Pergunta do formulário:
{field.label or field.semantic_hint}

Opções (índice: texto):
{numbered}

Escolha o ÍNDICE da opção que melhor corresponde ao perfil da empresa.
Se nenhuma opção se aplica de forma clara, responda index null.
Responda somente JSON válido, sem markdown: {{"index": 0}} ou {{"index": null}}
""".strip()

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            data = json.loads(response.text or "{}")
        except Exception as exc:
            logger.warning("choose_option_failed", selector=field.selector, error=str(exc))
            return None

        index = data.get("index") if isinstance(data, dict) else None
        if isinstance(index, int) and 0 <= index < len(options):
            return options[index]
        return None

    async def choose_options(
        self,
        group_label: str,
        options: list[str],
        profile_summary: str = "",
        max_select: int = 3,
    ) -> list[int]:
        """Seleciona até `max_select` opções compatíveis com a atividade da empresa.

        Uma única chamada ao LLM para o grupo inteiro de checkboxes, evitando
        marcar todas as 150 categorias com o mesmo CNAE. Retorna [] se nenhuma
        opção se encaixa no perfil.
        """
        if not options or not os.getenv("GEMINI_API_KEY"):
            return []

        numbered = "\n".join(f"{i}: {opt}" for i, opt in enumerate(options))
        prompt = f"""
Você ajuda a preencher o cadastro de uma empresa fornecedora.

Perfil da empresa:
{profile_summary or "(sem dados)"}

Pergunta (seleção múltipla): {group_label}

Opções (índice: texto):
{numbered}

Escolha no MÁXIMO {max_select} índices das opções que se aplicam a ESTA empresa
— seja a atividade que ela fornece, os documentos que ela possui, ou a categoria
que a descreve. Seja criterioso: marque só o que realmente se aplica ao perfil.
Se NENHUMA opção se aplica, retorne lista vazia.
Responda somente JSON válido, sem markdown: {{"indices": [0, 3]}}
""".strip()

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            data = json.loads(response.text or "[]")
        except Exception as exc:
            logger.warning("choose_options_failed", group=group_label[:60], error=str(exc))
            return []

        indices = data.get("indices") if isinstance(data, dict) else data
        if not isinstance(indices, list):
            return []
        valid = [i for i in indices if isinstance(i, int) and 0 <= i < len(options)]
        return valid[:max_select]

    def _reconstruct(self, fields: list[FormField], raw: list[dict]) -> list[FormField]:
        by_index = {
            item.get("index"): item.get("semantic_type")
            for item in raw
            if isinstance(item, dict)
        }

        classified_fields = []
        for index, field in enumerate(fields):
            try:
                semantic_type = SemanticType(by_index.get(index))
            except ValueError:
                semantic_type = SemanticType.UNKNOWN

            classified_fields.append(
                field.model_copy(update={"semantic_type": semantic_type})
            )

        return classified_fields
