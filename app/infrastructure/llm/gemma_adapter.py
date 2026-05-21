from __future__ import annotations

import json
import os
from google import genai as google_genai
from dotenv import load_dotenv

from domain.entities.form import FormField, SemanticType
from domain.services.classifier_port import ClassifierPort

class GemmaClassifier(ClassifierPort):

    def __init__(self, model: str = "gemma-4-26b-it", api_key: str | None = None):
        load_dotenv()
        self._client = google_genai.Client(api_key=api_key or os.getenv("GEMINI_API_KEY"))
        self._model = model

    async def _classify(self, fields: list[FormField]) -> list[FormField]:
        hints = self._extract_hints(fields)
        raw = await self._call_llm(hints)
        return self._reconstruct(fields, raw)

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
