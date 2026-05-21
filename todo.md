# TODO — Agente de Automação de Formulários

> Última atualização: Dia 3 (fim)
> Status geral: **Fase 2 concluída** — 2 de 4 fases entregues

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

### Artefatos produzidos

- `pyproject.toml` com todas as dependências
- `.env.example` com variáveis de ambiente
- Estrutura de diretórios hexagonal: `domain/`, `infrastructure/`, `interfaces/`, `tests/`
- `risks.md` com riscos mapeados por portal

---

## Fase 2 — Parsing e Interpretação ✅ CONCLUÍDA

**Estimativa:** 2 dias úteis | **Executado em:** Dias 2 e 3

### Atividades

- [x] Parser de formulários — `DOMCrawler` extrai campos do DOM/iframe
- [x] Extração estruturada — `FormField` populado com `tag`, `label`, `selector`, `required`, `field_type`
- [x] Classificação semântica via IA — `GemmaClassifier` com Port & Adapter

### Entrega

> ✅ IA compreendendo os campos dinamicamente — dado um `FormField` com label arbitrário, o agente infere o tipo semântico correto via Gemma.

### Artefatos produzidos

**Entidades de domínio** (`domain/entities/form.py`)
- [x] `FieldType` — enum dos tipos estruturais do DOM (text, email, radio, select, file…)
- [x] `SemanticType` — enum do que o agente infere (cnpj, razao_social, email_corporativo…)
- [x] `FormField` — campo com seção DOM (crawler preenche) + seção semântica (LLM preenche)
- [x] `FormPage` — página com lista de campos + número da página
- [x] `FormSession` — estado de execução: página atual + valores preenchidos
- [x] `ExecutionResult` — resultado final: sucesso/erro + evidências

**Formatters** (`infrastructure/formatters/masks.py`)
- [x] `format_cnpj()` — formatação e validação de CNPJ
- [x] `format_cep()` — formatação de CEP
- [x] `format_phone()` — formatação de telefone fixo e celular
- [x] `company_email()` — geração de e-mail com domínio da empresa (resolve risco Jaguar pág. 7)
- [x] Testes unitários — 17/17 passando

**DOM Crawler** (`infrastructure/browser/crawler.py`)
- [x] Detecção automática de iframe
- [x] `frame_locator` transparente para os dois portais
- [x] Extração de campos visíveis após interação inicial
- [x] Screenshot automático na abertura

**CLI** (`interfaces/cli/main.py`)
- [x] Comando `crawl` com flags `--portal`, `--page`, `--no-headless`, `--slow-mo`
- [x] Saída dos campos encontrados no terminal

**Classificador semântico** (`domain/services/classifier_port.py` + `infrastructure/llm/gemma_adapter.py`)
- [x] `ClassifierPort` — contrato abstrato com Template Method, `@final` no método público e `_ensure_contract` em runtime
- [x] `GemmaClassifier` — adapter com `_extract_hints`, `_call_llm` (async nativo via `client.aio`) e `_reconstruct`
- [x] Prompt com campos formatados por linha e saída JSON estruturada via `response_mime_type`
- [x] Fallback para `SemanticType.UNKNOWN` quando sem chave ou resposta inválida
- [x] Testes unitários — 4/4 passando (integração marcada com `skipif` aguardando chave no CI)

---

## Fase 3 — Preenchimento Automatizado ⏳ PENDENTE

**Estimativa:** 2 dias úteis | **Previsão:** Dias 4–5

### Atividades

- [ ] Geração de dados fake — integração Faker + LLM por `SemanticType`
- [ ] Preenchimento automático — `FormFiller` usando Playwright
- [ ] Upload de arquivos fake
- [ ] Navegação entre etapas (multi-page flow)

### Entrega esperada

> Fluxo automatizado funcionando ponta a ponta nos portais AngloGold e Jaguar.

---

## Fase 4 — Generalização e Robustez ⏳ PENDENTE

**Estimativa:** 2–3 dias úteis | **Previsão:** Dias 6–8

### Atividades

- [ ] Refinamento heurístico — reduzir dependência de labels exatos
- [ ] Redução de dependência específica por portal
- [ ] Tratamento de erros — retry, fallback, logging estruturado
- [ ] Validação em terceiro portal inédito

### Entrega esperada

> Agente adaptável para portal nunca visto antes.

---

## Riscos ativos

| Risco | Status | Mitigação atual |
|---|---|---|
| iframes complexos | ✅ Resolvido | `frame_locator` automático no crawler |
| Validação de domínio de e-mail | ✅ Resolvido | `company_email()` nos formatters |
| Captcha | ⚠️ Não encontrado ainda | Monitorar — pausa manual se aparecer |
| MFA / autenticação externa | ⚠️ Não encontrado ainda | A avaliar |
| Componentes altamente dinâmicos | 🔄 Parcial | Screenshot + slow_mo para debug |
| Bloqueios anti-bot | 🔄 Parcial | User-agent padrão do Playwright |
| Upload com validação server-side | ⏳ Pendente | Fase 3 |
| Validação documental real | ⏳ Pendente | Fase 3 |

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