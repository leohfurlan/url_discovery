from __future__ import annotations

import json
import os
import structlog
from google import genai as google_genai
from dotenv import load_dotenv

from domain.entities.form import FormField, SemanticType
from domain.services.classifier_port import ClassifierPort
from infrastructure.llm.heuristic import heuristic_classify
from infrastructure.llm import cls_cache as cache

logger = structlog.get_logger(__name__)


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
            r if r is not None else field.model_copy(update={"semantic_type": SemanticType.UNKNOWN})
            for r, field in zip(result, fields)
        ]

    def _extract_hints(self, fields: list[FormField]) -> list[dict]:
        hints = []
        for index, field in enumerate(fields):
            hint = {"index": index}
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

Classifique cada campo em exatamente um dos tipos abaixo:
{json.dumps(semantic_types, ensure_ascii=False)}

Retorne somente JSON válido, sem markdown, neste formato:
[{{"index": 0, "semantic_type": "cnpj"}}]

Use "unknown" quando não houver informação suficiente.

Campos:
{campos_formatados}
""".strip()

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )

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
