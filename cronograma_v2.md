# Cronograma v2 — Agente de Preenchimento de Formulários

> Atualizado em: 2026-05-25
> Baseado no progresso real até o Dia 7.

---

## Resumo executivo

| Fase | Descrição | Status | Dias reais |
|---|---|---|---|
| 1 | Discovery e Setup | ✅ Concluída | Dia 1 |
| 2 | Parsing e Interpretação | ✅ Concluída | Dias 2–3 |
| 3 | Preenchimento Automatizado | ✅ Concluída | Dia 4 |
| 4 | Generalização e Robustez | ⏳ Em andamento | Dias 5–7+ |
| 5 | Testes em produção e portais novos | 🔜 Planejada | Dias 8–10 |

---

## Fase 1 — Discovery e Setup ✅

**Dias 1** | Entregue no prazo.

- Setup da stack (Python, Playwright, Pydantic, Faker, Google GenAI SDK)
- Validação Playwright com o portal AngloGold Ashanti
- Documentação dos 2 portais iniciais

---

## Fase 2 — Parsing e Interpretação ✅

**Dias 2–3** | Entregue no prazo.

- `DOMCrawler` — extração de campos do DOM/iframe
- `FormField` com label, selector, required, field_type
- `GemmaClassifier` com Port & Adapter (heurística + LLM fallback)
- Formatadores brasileiros (CNPJ, CPF, CEP, telefone, e-mail corporativo)

---

## Fase 3 — Preenchimento Automatizado ✅

**Dia 4** | Entregue antes do prazo.

- `DataGenerator` com 21 tipos semânticos + memória de sessão
- `FormFiller` — roteador por FieldType (text, email, select, checkbox, file, date)
- `NavigationOrchestrator` — fluxo multi-página com loop de segurança
- 14/14 testes passando

---

## Fase 4 — Generalização e Robustez ⏳

**Dias 5–7+** | Em andamento — avanço substancial.

### ✅ Dia 5 — PortalDiscovery e CLI
- `PortalDiscovery` — 3 estratégias em cascata (iframe → link → botão)
- Suporte a 8 plataformas conhecidas (Microsoft Forms, Google Forms, etc.)
- CLI Typer completa (`--headless`, `--slow-fill`, `--max-pages`, `--iframe`, etc.)

### ✅ Dia 6 — SPAs e Controle de Submissão
- Suporte a Microsoft Forms sem `id`/`name` via `aria-labelledby`
- `ALLOW_FORM_SUBMIT` — controle de segurança para não submeter sem autorização
- `NavigationResult.SUBMIT_BLOCKED` como resultado explícito
- Validação em portal real (AngloGold Ashanti — 6/6 campos corretos)

### ✅ Dia 7 — Importação de Dados Reais via PDF
- `DocumentExtractor` — lê Cartão CNPJ, Contrato Social e Demonstrações Financeiras
- Extração via Gemma + `pdfplumber` (detecção automática de tipo por palavras-chave)
- `CompanyProfile` — modelo Pydantic com 20+ campos; fallback automático para Faker
- Novos `SemanticType`: `FAVORECIDO`, `NOME_SOCIO`, `CPF_SOCIO`
- Parâmetro `--docs-dir` na CLI

### 🔲 Pendente na Fase 4
- Refinamento de label Microsoft Forms (sem número prefixado)
- Fuzzy match para campos com hint ambíguo (reduz dependência de labels exatos)
- Retry layer com backoff para `_fill_field` e `_click_next`
- Anti-bot stealth (user-agent rotativo, delays aleatórios)
- Testes unitários para o módulo de extração de PDF

---

## Fase 5 — Testes em Produção e Portais Novos 🔜

**Estimativa: Dias 8–10**

### Objetivos
- Validar `--docs-dir` com PDFs reais (Cartão CNPJ + Contrato Social + DRE)
- Executar contra 3+ portais novos além de AngloGold e Jaguar Mining
- Medir taxa de acerto da classificação semântica (meta: >85% sem LLM fallback)
- Montar base de casos de teste com screenshots e logs

### Atividades planejadas
- [ ] Teste end-to-end com dados reais: `--docs-dir` + portal real + `--no-submit`
- [ ] Validação manual dos campos preenchidos vs. dados do Cartão CNPJ
- [ ] Identificar campos que ainda caem no LLM fallback → expandir heurísticas
- [ ] Documentar 3+ novos portais em `app/portals/`
- [ ] Testes de regressão automatizados (gravar sessão e comparar)

---

## Riscos e impedimentos

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| PDFs escaneados (sem texto) | Alta | Médio | Warning + fallback Faker; documentar limitação |
| Gemma não extrai campos corretamente | Média | Alto | Validação manual obrigatória antes de `--submit` |
| Portal com CAPTCHA | Média | Alto | Pausa manual; monitorar nas execuções |
| Rate limit Gemini API | Baixa | Médio | `--docs-dir` faz chamadas síncronas em batch pequeno |
| Formulário com campos financeiros não mapeados | Média | Baixo | Fallback para `TEXTO_LIVRE` → Faker |

---

## Stack atual

| Componente | Biblioteca | Versão mínima |
|---|---|---|
| Browser automation | playwright | 1.44 |
| Data models | pydantic | 2.7 |
| Fake data | faker[pt_BR] | 25.0 |
| LLM | google-genai | 1.0 |
| **PDF extraction** | **pdfplumber** | **0.11** |
| Logging | structlog | 24.0 |
| CLI | typer | 0.12 |
| Tests | pytest + pytest-asyncio | 8.2 |
