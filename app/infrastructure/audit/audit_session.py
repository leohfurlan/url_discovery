"""
infrastructure/audit/audit_session.py

AuditSession — centraliza, num único lugar por execução, TODA a evidência de
auditoria de um preenchimento: o log estruturado da sessão e os screenshots de
cada pergunta preenchida ficam juntos na mesma pasta do portal.

Estrutura gerada (exemplo do portal "jaguar-mining"):

    audit/
    └── jaguar-mining/
        └── 20260527_143000/          ← uma pasta por execução (timestamp)
            ├── session.log           ← log estruturado completo da sessão
            ├── README.md             ← índice legível: pergunta → screenshot
            ├── manifest.json         ← o mesmo índice em formato máquina-legível
            └── screenshots/
                ├── pagina-01.png            ← visão completa da página (full page)
                ├── p01-q01-razao_social.png ← 1 screenshot por pergunta preenchida
                ├── p01-q02-cnpj.png
                └── ...

Objetivo de cobertura: cada pergunta efetivamente preenchida gera o seu próprio
screenshot (campo destacado e centralizado na viewport), de modo que os prints
cubram 100% das questões respondidas. O `manifest.json` registra, por pergunta,
o rótulo, o tipo semântico, o valor preenchido e se o screenshot foi capturado —
permitindo verificar a cobertura de forma objetiva.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Raiz padrão dos artefatos de auditoria (relativa à raiz do projeto: app/..).
AUDIT_DIR = Path(__file__).resolve().parents[2] / "audit"

# Tamanho máximo do valor registrado no manifesto (evita poluir o JSON/README
# com textos longos — o screenshot é a evidência visual completa).
_MAX_VALUE_LEN = 120


def _slugify(text: str, fallback: str = "campo") -> str:
    """Converte rótulo/semântico em um fragmento seguro para nome de arquivo."""
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:40] or fallback


class AuditSession:
    """Gerencia a pasta de auditoria de UMA execução e acumula o manifesto.

    Uso típico:
        audit = AuditSession(portal="jaguar-mining")
        audit.setup()                     # cria as pastas
        _configure_logging(audit.log_path)
        ...
        audit.record_page(page_num=1, screenshot=path, url=...)
        audit.record_question(page_num=1, index=1, field=f, value=v,
                              screenshot=qpath, captured=True)
        ...
        audit.write_manifest(result="SUCCESS", final_url=...)
    """

    def __init__(
        self,
        portal: str,
        base_dir: Path | None = None,
        timestamp: str | None = None,
    ) -> None:
        self.portal = portal
        self.timestamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.root = (base_dir or AUDIT_DIR) / portal / self.timestamp
        self.screenshots_dir = self.root / "screenshots"
        # Acumulador ordenado de páginas → cada uma com sua lista de perguntas.
        self._pages: dict[int, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Caminhos
    # ------------------------------------------------------------------

    @property
    def log_path(self) -> Path:
        """Arquivo de log estruturado da sessão (fica ao lado dos screenshots)."""
        return self.root / "session.log"

    def setup(self) -> None:
        """Cria a árvore de diretórios da execução."""
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

    def overview_path(self, page_num: int) -> Path:
        """Caminho do screenshot de visão geral (full page) de uma página."""
        return self.screenshots_dir / f"pagina-{page_num:02d}.png"

    def question_path(self, page_num: int, index: int, slug: str) -> Path:
        """Caminho do screenshot de uma pergunta específica."""
        return self.screenshots_dir / f"p{page_num:02d}-q{index:02d}-{slug}.png"

    @staticmethod
    def slug_for(field: Any) -> str:
        """Deriva um slug estável para o arquivo a partir do campo."""
        semantic = getattr(field, "semantic_type", None)
        if semantic is not None:
            return _slugify(str(getattr(semantic, "value", semantic)))
        return _slugify(getattr(field, "label", "") or "", fallback="campo")

    # ------------------------------------------------------------------
    # Registro do manifesto
    # ------------------------------------------------------------------

    def record_page(self, page_num: int, screenshot: Path, url: str = "") -> None:
        """Registra a visão geral de uma página."""
        page = self._pages.setdefault(page_num, {"questions": []})
        page["overview_screenshot"] = self._rel(screenshot)
        page["url"] = url

    def record_question(
        self,
        page_num: int,
        index: int,
        field: Any,
        value: Any,
        screenshot: Path,
        captured: bool,
    ) -> None:
        """Registra uma pergunta preenchida e o seu screenshot."""
        page = self._pages.setdefault(page_num, {"questions": []})
        semantic = getattr(field, "semantic_type", None)
        ftype = getattr(field, "field_type", None)
        page["questions"].append({
            "index": index,
            "label": (getattr(field, "label", None) or "").strip() or None,
            "semantic_type": str(getattr(semantic, "value", semantic)) if semantic else None,
            "field_type": str(getattr(ftype, "value", ftype)) if ftype else None,
            "value": self._fmt_value(value),
            "confidence": getattr(field, "confidence", None),
            "classification_source": getattr(field, "classification_source", None),
            "selector": getattr(field, "selector", None),
            "screenshot": self._rel(screenshot),
            "captured": captured,
        })

    # ------------------------------------------------------------------
    # Escrita final (manifest.json + README.md)
    # ------------------------------------------------------------------

    def write_manifest(self, result: str = "", final_url: str = "") -> Path:
        """Escreve manifest.json e README.md com o índice das evidências.

        Retorna o caminho do README.md.
        """
        pages = [
            {"page_number": num, **self._pages[num]}
            for num in sorted(self._pages)
        ]
        total_q = sum(len(p["questions"]) for p in pages)
        captured = sum(1 for p in pages for q in p["questions"] if q["captured"])
        coverage = round(100.0 * captured / total_q, 1) if total_q else 0.0

        manifest = {
            "portal": self.portal,
            "timestamp": self.timestamp,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "result": result,
            "final_url": final_url,
            "totals": {
                "pages": len(pages),
                "questions": total_q,
                "captured": captured,
                "coverage_pct": coverage,
            },
            "pages": pages,
        }

        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        readme = self.root / "README.md"
        readme.write_text(self._render_readme(manifest), encoding="utf-8")

        logger.info(
            "audit_manifest_written",
            dir=str(self.root),
            questions=total_q,
            captured=captured,
            coverage_pct=coverage,
        )
        return readme

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _rel(self, path: Path) -> str:
        """Caminho relativo à raiz da execução (com barras normais)."""
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    @staticmethod
    def _fmt_value(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text if len(text) <= _MAX_VALUE_LEN else text[: _MAX_VALUE_LEN - 1] + "…"

    def _render_readme(self, manifest: dict[str, Any]) -> str:
        t = manifest["totals"]
        lines: list[str] = [
            f"# Auditoria — {manifest['portal']}",
            "",
            f"- **Execução:** `{manifest['timestamp']}`",
            f"- **Gerado em:** {manifest['generated_at']}",
            f"- **Resultado:** {manifest['result'] or '—'}",
            f"- **URL final:** {manifest['final_url'] or '—'}",
            "",
            "## Cobertura de screenshots",
            "",
            f"- Páginas: **{t['pages']}**",
            f"- Perguntas preenchidas: **{t['questions']}**",
            f"- Perguntas com screenshot: **{t['captured']}**",
            f"- Cobertura: **{t['coverage_pct']}%**",
            "",
            "Cada pergunta preenchida tem o seu próprio screenshot (campo destacado "
            "e centralizado). A visão completa de cada página também é capturada "
            "(`pagina-NN.png`). Logs e screenshots desta execução ficam todos nesta pasta.",
            "",
        ]
        for page in manifest["pages"]:
            lines.append(f"## Página {page['page_number']}")
            lines.append("")
            overview = page.get("overview_screenshot")
            if overview:
                lines.append(f"Visão geral: [`{overview}`]({overview})")
                lines.append("")
            if not page["questions"]:
                lines.append("_Sem perguntas preenchidas nesta página._")
                lines.append("")
                continue
            lines.append("| # | Pergunta | Tipo | Valor | Confiança | Screenshot |")
            lines.append("|---|----------|------|-------|-----------|------------|")
            for q in page["questions"]:
                label = (q["label"] or q["semantic_type"] or q["selector"] or "—")
                label = str(label).replace("|", "\\|")[:60]
                value = (q["value"] or "—").replace("|", "\\|").replace("\n", " ")
                shot = q["screenshot"]
                mark = f"[ver]({shot})" if q["captured"] else "⚠ não capturado"
                lines.append(
                    f"| {q['index']} | {label} | {q['field_type'] or '—'} | "
                    f"{value} | {q['confidence'] or '—'} | {mark} |"
                )
            lines.append("")
        return "\n".join(lines)
