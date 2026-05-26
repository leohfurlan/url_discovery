# TODO — Agente de Automação de Formulários

> Última atualização: Dia 8 (2026-05-26)
> Status geral: **Fase 4 EM ANDAMENTO** — 3 de 4 fases concluídas + módulo de importação de dados reais + cache semântico + campos condicionais implementados

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

### Concluído no Dia 6

- [x] **Suporte a SPAs sem `id`/`name` nos campos (Microsoft Forms)** — `infrastructure/browser/crawler.py`
  - `_build_selector` com fallback para `[aria-labelledby="..."]` quando `id` e `name` estão vazios
  - Resolução de múltiplos IDs separados por espaço no `aria-labelledby` via `split(/\s+/)`
  - Priorização de `aria-labelledby` sobre `aria-label` genérico (`'Single line text'`) na extração de labels
  - Resultado: classificação semântica passou de `UNKNOWN` para `razao_social`, `cnpj`, `telefone`, etc.
- [x] **`_wait_for_stable_dom` mais robusto** — `infrastructure/browser/navigator.py`
  - `state="attached"` → `state="visible"` para garantir que React hidratou os atributos antes do crawl
  - Timeout 6 s → 8 s; sleep de fallback 1.5 s → 2.0 s
- [x] **Botões de submissão final adicionados** — `_NEXT_BUTTON_SELECTORS`
  - `'button:has-text("Submit")'`, `'button:has-text("Enviar")'`, `'button:has-text("Submeter")'`, `'button:has-text("Start now")'`
- [x] **Controle de submissão `ALLOW_FORM_SUBMIT`** — `.env`, `.env.example`, `run.py`, `navigator.py`
  - `_FINAL_SUBMIT_SELECTORS` — conjunto de seletores que representam submissão final
  - `NavigationResult.SUBMIT_BLOCKED` — resultado distinto quando Submit é bloqueado por config
  - `_next_is_final_submit()` — helper que verifica se o próximo botão visível é de submissão final
  - Flag CLI `--submit` / `--no-submit` — sobrescreve variável de ambiente pontualmente
  - Check de bloqueio executa **antes** do `_is_success_page` — botão Submit visível prova que não é página de confirmação
- [x] **`_is_success_page` sem falsos positivos** — usa `innerText` (texto visível) em vez de `page.content()` (HTML + JS bundle)
- [x] **README atualizado** — aviso de segurança no topo, seção "Controle de Submissão", opção `--submit` na tabela
- [x] **Validação em portal real** — AngloGold Ashanti testado e documentado
  - 6/6 campos preenchidos com semântica correta
  - Resultado: `SUBMIT_BLOCKED` — formulário pronto para envio, Submit não clicado

### Concluído no Dia 7 (2026-05-25)

- [x] **Módulo de importação de dados reais via PDF** — substitui Faker pelos dados reais da empresa
  - `domain/entities/company_profile.py` — `CompanyProfile` (Pydantic) + `DocumentType` enum
  - `infrastructure/pdf/pdf_reader.py` — extração de texto com pdfplumber + detecção de tipo por palavras-chave
  - `infrastructure/pdf/gemma_extractor.py` — extração estruturada JSON via Gemma (mesmo client/modelo do projeto)
  - `domain/services/document_extractor.py` — `DocumentExtractor`: varre diretório, mescla perfis por prioridade
  - `domain/entities/form.py` — novos `SemanticType`: `FAVORECIDO`, `NOME_SOCIO`, `CPF_SOCIO`
  - `domain/services/generator.py` — `DataGenerator` aceita `CompanyProfile` opcional; fallback fake preservado
  - `domain/services/classifier.py` — heurísticas para os 3 novos tipos semânticos
  - `app/run.py` — parâmetro `--docs-dir <path>` para informar pasta com os PDFs
  - `pyproject.toml` — dependência `pdfplumber>=0.11`

**Documentos suportados:**

| Documento | Campos extraídos |
|---|---|
| Cartão CNPJ (Receita Federal) | CNPJ, Razão Social, Nome Fantasia, CNAE, Endereço, CEP, Cidade, UF, Telefone, IE, IM |
| Contrato Social / Alteração | Sócio principal, CPF do sócio, Objeto Social |
| Demonstrações Financeiras | Banco, Agência, Conta, Favorecido, Faturamento anual |

**Uso:**
```powershell
python app\run.py "https://portal.example.com" empresa --docs-dir ./docs --no-submit
```

### Concluído no Dia 8 (2026-05-26)

- [x] **Classificação semântica em 3 estágios** — `infrastructure/llm/gemma_adapter.py`, `heuristic.py`, `cls_cache.py`
  - `heuristic.py` — classificação local por regex/keywords, zero chamadas de API (cobre os campos mais comuns)
  - `cls_cache.py` — cache persistente JSON em `~/.url_discovery/cls_cache.json` (SHA-256 do hint do campo)
  - `GemmaClassifier` atualizado: heurística → cache → LLM (reduz drasticamente chamadas à API)
  - `--clear-cls-cache` no CLI — limpa o cache antes de iniciar quando necessário
- [x] **Cache de PDFs** — `domain/services/document_extractor.py`
  - Resultado do DocumentExtractor cacheado entre sessões
  - `--no-cache` no CLI — força reprocessamento mesmo com cache disponível
- [x] **Campos condicionais** — `infrastructure/browser/navigator.py` `_fill_until_stable`
  - Preenche campos em loop por rodada até o DOM parar de revelar novos campos
  - Cobre formulários onde cada resposta desvela a próxima pergunta (ex: Jaguar Mining — Questionário de Integridade)
  - `max_rounds=20` como limite de segurança
- [x] **COMBOBOX** — `domain/entities/form.py` + `infrastructure/browser/crawler.py` + `filler.py`
  - Novo `FieldType.COMBOBOX` para dropdowns React/SPA sem native `<select>` (role="combobox")
  - `_fill_combobox`: clica para abrir → localiza opção por texto → fallback para digitar + Enter
- [x] **Parsing de endereço em partes** — `domain/services/generator.py`
  - `DataGenerator._ensure_addr_parts` parseia `CompanyProfile.endereco` em logradouro / número / complemento / bairro
  - Coerência de sessão: partes geradas fake também são consistentes entre si
- [x] **Testes unitários DOMCrawler** adicionados à suíte

### Pendente

- [ ] **Refinar extração de label Microsoft Forms** — usar `querySelector('span:nth-child(2)')` dentro do `QuestionId_...` para capturar título puro, sem número prefixado (`"1."`) e sem helper text do `QuestionInfo_...` (padrão XPath identificado: `//*[@id="QuestionId_r..."]/div[1]/span/span[1]/span[2]`)
- [ ] Refinamento heurístico — reduzir dependência de labels exatos (fuzzy match para `UNKNOWN`)
- [ ] Retry layer — decorator `@with_retry(max=3, backoff=1.5)` para `_fill_field` e `_click_next`
- [ ] Anti-bot stealth — user-agent rotativo, mouse movement simulado, delays aleatórios
- [ ] Tratamento de CAPTCHA — pausa e notificação quando detectado
- [ ] Testes unitários para `DocumentExtractor`, `pdf_reader` e `gemma_extractor`

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
| Componentes altamente dinâmicos (SPAs) | ✅ Resolvido | `aria-labelledby` multi-ID, `state="visible"`, seletores de Submit |
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
