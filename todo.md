# TODO — Agente de Automação de Formulários

> Última atualização: Dia 5
> Status geral: **Fase 4 EM ANDAMENTO** — 3 de 4 fases concluídas + entradas da Fase 4 implementadas

---

## Fase 1 — Discovery e Setup ✅ CONCLUÍDA

**Estimativa:** 1 dia útil | **Executado em:** Dia 1

### Atividades

- [x] Análise dos portais (AngloGold Ashanti + Jaguar Mining documentados)
- [x] Setup da stack (Python, Playwright, Pydantic, Faker, Google GenAI SDK)
- [x] Validação Playwright — browser abre, navega, detecta campos no portal AngloGold
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
- `infrastructure/formaters.py` — formatação CNPJ, CEP, telefone, e-mail corporativo
- `infrastructure/browser/crawler.py` — `DOMCrawler` com suporte a iframe e extração de labels
- `domain/services/classifier_port.py` + `infrastructure/llm/gemma_adapter.py` — classificador semântico

---

## Fase 3 — Preenchimento Automatizado ✅ CONCLUÍDA

**Estimativa:** 2 dias úteis | **Executado em:** Dia 4

### Atividades

- [x] Geração de dados fake — `domain/services/generator.py` com 21 tipos semânticos
- [x] Preenchimento automático — `infrastructure/browser/filler.py` (`FormFiller`)
- [x] Upload de arquivos fake — geração de PDF/PNG mínimos válidos em `/tmp`
- [x] Navegação entre etapas — `infrastructure/browser/navigator.py` (`NavigationOrchestrator`)

### Entrega

> ✅ Fluxo automatizado ponta a ponta implementado.

### Artefatos produzidos

**FormFiller** (`infrastructure/browser/filler.py`)
- [x] Roteador por `FieldType`: text, email, tel, number, textarea, select, radio, checkbox, file, date
- [x] `_fill_select` — fallback em 3 níveis: value → label → primeira opção não-vazia
- [x] `_fill_file` — resolve caminho, cria arquivo fake temporário se necessário
- [x] Suporte a `frame_locator` (iframe-aware)

**NavigationOrchestrator** (`infrastructure/browser/navigator.py`)
- [x] Loop multi-página com limite de segurança (`max_pages=15`)
- [x] Pipeline por página: crawl → classify → generate → fill → screenshot → next
- [x] `_click_next` — lista priorizada de 13 seletores comuns para botões de avanço
- [x] `_is_success_page` — detecta 10 indicadores de conclusão (PT + EN)
- [x] `StepReport` + `RunReport` com histórico completo de execução

**Testes** (`tests/test_filler_navigator.py`)
- [x] 12 testes unitários — FormFiller (text, email, select, checkbox, file, error cases)
- [x] 2 testes de integração leve do NavigationOrchestrator (success + no-next-button)
- [x] 14/14 passando

---

## Fase 4 — Generalização e Robustez ⏳ EM ANDAMENTO

**Estimativa:** 2–3 dias úteis | **Previsão:** Dias 5–7

### Concluído no Dia 5

- [x] **PortalDiscovery** — `infrastructure/browser/portal_discovery.py`
  - Descobre formulário a partir da URL pública do portal (não do link do form)
  - 3 estratégias em cascata: iframe embutido → link direto → botão/texto
  - Suporte a nova aba (popup) e navegação na mesma aba
  - 8 plataformas conhecidas: Microsoft Forms, Google Forms, Typeform, JotForm…
- [x] **Extração de labels no DOMCrawler** — `infrastructure/browser/crawler.py`
  - Label por `<label for="id">`, `<label>` pai, `aria-label`, `aria-labelledby`
  - Opções de SELECT agora retornam texto visível (não valor interno)
  - Melhora significativa na qualidade da classificação semântica
- [x] **CLI** — `app/run.py`
  - Typer — `python run.py <URL> <PORTAL> [opções]`
  - Integra PortalDiscovery + NavigationOrchestrator em um comando
  - Opções: `--headless`, `--slow-fill`, `--max-pages`, `--iframe`, `--screenshots`, `--model`
- [x] **Coerência de dados** — `DataGenerator`
  - E-mail corporativo usa o mesmo domínio da razão social gerada anteriormente
- [x] **README atualizado** — pipeline completo, exemplos de uso, estrutura atual
- [x] **Correções no domain model** — `FormStatus`, `filled_values`, `DESCONHECIDO`, `DOCUMENTO_PDF`

### Pendente

- [ ] Refinamento heurístico — reduzir dependência de labels exatos (fuzzy match para `UNKNOWN`)
- [ ] Retry layer — decorator `@with_retry(max=3, backoff=1.5)` para `_fill_field` e `_click_next`
- [ ] Anti-bot stealth — user-agent rotativo, mouse movement simulado, delays aleatórios
- [ ] Validação em portal real — executar contra AngloGold ou Jaguar e documentar resultado
- [ ] Tratamento de CAPTCHA — pausa e notificação quando detectado

### Entrega esperada

> Agente adaptável para portal nunca visto antes, rodando via CLI em uma linha.

---

## Riscos ativos

| Risco | Status | Mitigação atual |
|---|---|---|
| Iframes complexos | ✅ Resolvido | `frame_locator` automático no crawler e no filler |
| Validação de domínio de e-mail | ✅ Resolvido | `company_email()` usa a razão social gerada |
| Portal sem link/botão reconhecível | ✅ Parcial | Fallback retorna página atual; discovery extensível |
| Upload com validação server-side | ✅ Parcial | PDF/PNG mínimos válidos — pode falhar em validação de conteúdo |
| Captcha | ⚠️ Não encontrado ainda | Monitorar — pausa manual se aparecer |
| MFA / autenticação externa | ⚠️ Não encontrado ainda | A avaliar |
| Componentes altamente dinâmicos | 🔄 Parcial | Screenshot + slow_mo + 13 seletores de next button |
| Bloqueios anti-bot | 🔄 Parcial | Fase 4 pendente — stealth mode |

---

## Stack confirmada

- **Python 3.11+**
- **Playwright 1.44+** — automação de browser
- **Pydantic 2.7+** — entidades e validação
- **Faker (pt_BR)** — geração de dados fictícios
- **Google GenAI SDK** — classificador semântico via Gemini (`gemma-4-26b-a4b-it`)
- **Structlog** — logs estruturados
- **Typer** — CLI (`app/run.py`)
- **pytest + pytest-asyncio** — testes

## Arquitetura

```
Hexagonal simplificada + fluxo agentic modular

domain/         → entidades puras, sem dependência externa
infrastructure/ → browser (Playwright) + formatters + llm (adapters)
app/run.py      → CLI — orquestra tudo em um comando
tests/          → unitários + integração leve (mocks do Playwright)
```
