"""
infrastructure/llm/cls_cache.py

Cache persistente de classificações semânticas.
Chave: SHA-256 (16 hex) do texto normalizado do campo (label + name + options).
Valor: string do SemanticType.

Armazenado em ~/.url_discovery/cls_cache.json — persiste entre portais e sessões.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from domain.entities.form import FormField, SemanticType

_CACHE_FILE = Path.home() / ".url_discovery" / "cls_cache.json"

_memory: dict[str, str] = {}
_dirty = False
_loaded = False


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    if _CACHE_FILE.exists():
        try:
            _memory.update(json.loads(_CACHE_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass


def _flush() -> None:
    global _dirty
    if not _dirty:
        return
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(
        json.dumps(_memory, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _dirty = False


def fingerprint(field: FormField) -> str:
    text = "|".join([
        (field.label or "").lower().strip(),
        (field.name or "").lower().strip(),
        (field.placeholder or "").lower().strip(),
        "|".join(o.lower() for o in field.options),
    ])
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def get(fp: str) -> SemanticType | None:
    _load()
    val = _memory.get(fp)
    if val is None:
        return None
    try:
        return SemanticType(val)
    except ValueError:
        return None


def put_batch(items: list[tuple[str, SemanticType]]) -> None:
    global _dirty
    _load()
    for fp, semantic in items:
        _memory[fp] = semantic.value
    _dirty = True
    _flush()
