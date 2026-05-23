# TODO — Agente de Automação de Formulários

> Última atualização: Dia 4 (fim)
> Status geral: **Fase 3 CONCLUÍDA** — 3 de 4 fases concluídas, Fase 4 pendente

---

## Fase 1 — Discovery e Setup ✅ CONCLUÍDA

**Estimativa:** 1 dia útil | **Executado em:** Dia 1

### Atividades

- [x] Análise dos portais (AngloGold Ashanti + Jaguar Mining documentados)
- [x] Setup da stack (Python, Playwright, Pydantic, Faker, Google GenAI SDK)
- [x] Validação Playwright — browser abre, navega, detecta 6 campos no portal AngloGold
- [x] Identificação de riscos (iframes, anti-bot, validação de domínio de e-mail)

### Entrega

> ✅ Navegação automatizada funcionando — crawler abre portal, detecta iframe e conta campos corretamente.

---

## Fase 2 — Parsing e Interpretação ✅ CONCLUÍDA

**Estimativa:** 2 dias úteis | **Executado em:** Dias 2 e 3

### Atividades

- [x] Parser de formulários — `DOMCrawler` extrai campos do DOM/iframe
- [x] Extração estruturada — `FormField` populado com `tag`, `label`, `selector`, `required`, `field_type`
- [x] Classificação semântica via IA — `GemmaClassifier` com Port & Adapter

### Entrega

> ✅ IA compreendendo os campos dinamicamente.

### Artefatos produzidos

- `domain/entities/form.py` — `FieldType`, `SemanticType`, `FormField`, `FormPage`, `FormSession`, `ExecutionResult`
- `infrastructure/formatters/masks.py` — formatação CNPJ, CEP, telefone, e-mail corporativo
- `infrastructure/browser/crawler.py` — `DOMCrawler` com suporte a iframe
- `interfaces/cli/main.py` — comando `crawl`
- `domain/services/classifier_port.py` + `infrastructure/llm/gemma_adapter.py` — classificador semântico

---

## Fase 3 — Preenchimento Automatizado ✅ CONCLUÍDA

**Estimativa:** 2 dias úteis | **Executado em:** Dia 4

### Atividades

- [x] Geração de dados fake — `domain/services/generator.py` com 21 tipos semânticos — 8/8 testes passando
- [x] Preenchimento automático — `infrastructure/browser/filler.py` (`FormFiller`)
- [x] Upload de arquivos fake — geração de PDF/PNG mínimos válidos em `/tmp`
- [x] Navegação entre etapas — `infrastructure/browser/navigator.py` (`NavigationOrchestrator`)

### Entrega

> ✅ Fluxo automatizado ponta a ponta implementado.

### Artefatos produzidos

**FormFiller** (`infrastructure/browser/filler.py`)
- [x] `FormFiller` — preenche `FormPage` usando valores de `FormSession`
- [x] Roteador por `FieldType`: text, email, tel, number, textarea, select, radio, checkbox, file, date
- [x] `_fill_select` — fallback em 3 níveis: value → label → primeira opção não-vazia
- [x] `_fill_radio` — busca por `name + value`, fallback no primeiro do grupo
- [x] `_fill_file` — resolve caminho, cria arquivo fake temporário se necessário
- [x] `_write_minimal_pdf` — PDF mínimo válido (`%PDF-1.4`, parseável)
- [x] `_write_minimal_image` — PNG mínimo válido (1x1 pixel, magic bytes corretos)
- [x] Suporte a `frame_locator` (iframe-aware, mesma abstração do DOMCrawler)
- [x] `take_screenshot` — salva screenshot em `/tmp` com nome parametrizável
- [x] `FillError` — exceção recuperável para falhas individuais de campo

**NavigationOrchestrator** (`infrastructure/browser/navigator.py`)
- [x] Loop multi-página com limite de segurança (`max_pages=15`)
- [x] Pipeline por página: crawl → classify → generate → fill → screenshot → next
- [x] `_click_next` — lista priorizada de 13 seletores comuns para botões de avanço
- [x] `_is_success_page` — detecta 10 indicadores de conclusão (PT + EN)
- [x] `StepReport` — relatório por etapa: campos encontrados, preenchidos, falhas, screenshot
- [x] `RunReport` — resultado final com `NavigationResult` enum e histórico de steps
- [x] `run_portal()` — função de conveniência para uso direto
- [x] Callback `on_page_done` para integração com CLI/UI
- [x] Integração com `FormStatus` na session

**Testes** (`tests/test_filler_navigator.py`)
- [x] 12 testes unitários — FormFiller (text, email, select, checkbox, file, error cases)
- [x] Validação dos geradores de PDF e PNG fake
- [x] 2 testes de integração leve do NavigationOrchestrator (success + no-next-button)

---

## Fase 4 — Generalização e Robustez ⏳ PENDENTE

**Estimativa:** 2–3 dias úteis | **Previsão:** Dias 5–7

### Atividades

- [ ] Refinamento heurístico — reduzir dependência de labels exatos
- [ ] Redução de dependência específica por portal
- [ ] Tratamento de erros — retry automático, backoff, logging estruturado completo
- [ ] Validação em terceiro portal inédito

### Entrega esperada

> Agente adaptável para portal nunca visto antes.

### Próximos passos concretos (início da Fase 4)

1. **Retry layer** — decorator `@with_retry(max=3, backoff=1.5)` para `_fill_field` e `_click_next`
2. **Heurística de label fuzzy** — se `SemanticType.UNKNOWN`, usar similaridade de string no label para inferir tipo
3. **Anti-bot stealth** — user-agent rotativo, mouse movement simulado, delays aleatórios
4. **Portal 3** — executar contra portal inédito e documentar falhas/adaptações necessárias

---

## Riscos ativos

| Risco | Status | Mitigação atual |
|---|---|---|
| iframes complexos | ✅ Resolvido | `frame_locator` automático no crawler e no filler |
| Validação de domínio de e-mail | ✅ Resolvido | `company_email()` nos formatters |
| Upload com validação server-side | ✅ Parcial | PDF/PNG mínimos válidos — pode falhar em validação de conteúdo |
| Captcha | ⚠️ Não encontrado ainda | Monitorar — pausa manual se aparecer |
| MFA / autenticação externa | ⚠️ Não encontrado ainda | A avaliar |
| Componentes altamente dinâmicos | 🔄 Parcial | Screenshot + slow_mo + 13 seletores de next button |
| Bloqueios anti-bot | 🔄 Parcial | Fase 4 — stealth mode |
| Validação documental real | ⏳ Pendente | Fase 4 |

---

## Stack confirmada

- **Python 3.11+**
- **Playwright 1.44+** — automação de browser
- **Pydantic 2.7+** — entidades e validação
- **Faker (pt_BR)** — geração de dados fictícios
- **Google GenAI SDK** — classificador semântico via Gemma (`gemma-4-26b-it`)
- **Structlog** — logs estruturados
- **Typer** — CLI
- **pytest + pytest-asyncio + pytest-playwright** — testes

## Arquitetura

```
Hexagonal simplificada + fluxo agentic modular
domain/         → entidades puras, sem dependência externa
infrastructure/ → browser (Playwright) + formatters + llm (adapters)
interfaces/     → CLI (Typer)
tests/          → unitários + integração
```