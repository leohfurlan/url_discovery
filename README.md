# URL Discovery — Agente de Preenchimento de Formulários

> **IMPORTANTE — O agente NÃO submete formulários por padrão.**
>
> O comportamento padrão é preencher todos os campos e parar **antes** de clicar em Submit/Enviar.
> Nenhum dado é enviado ao portal sem autorização explícita.
>
> Para habilitar a submissão, defina `ALLOW_FORM_SUBMIT=true` no `.env`
> **ou** use a flag `--submit` na linha de comando — somente após validar
> manualmente os dados gerados para o portal em questão.
> Veja a seção [Controle de Submissão](#controle-de-submissão) abaixo.

Agente Python que acessa portais de fornecedores, descobre o formulário de cadastro automaticamente e o preenche com dados gerados por IA — sem intervenção manual.

## Como funciona

O agente recebe a **URL pública do portal** (não o link direto do formulário). O pipeline é:

```
[opcional] Cartão CNPJ + Contrato Social + Demonstrações Financeiras (PDF)
  │
  ▼
DocumentExtractor        Lê PDFs via pdfplumber, detecta o tipo de documento e envia
  │                      o texto ao Gemma para extração estruturada em JSON.
  │                      Resultado: CompanyProfile com dados reais da empresa.
  │                      (Se omitido, DataGenerator usa Faker como antes.)
  ▼
URL do portal
  │
  ▼
PortalDiscovery          Detecta iframe embutido, link ou botão que leva ao formulário.
  │                      Suporta Microsoft Forms, Google Forms, Typeform, JotForm, etc.
  ▼
DOMCrawler               Extrai campos do DOM (input, select, textarea, labels, opções).
  │                      Suporta iframes — Microsoft Forms é sempre servido em iframe.
  ▼
GemmaClassifier          Classifica cada campo em 3 estágios:
  │                      1. Heurística local — regex/keywords, zero chamadas de API
  │                      2. Cache persistente — ~/.url_discovery/cls_cache.json
  │                      3. Gemma via API — só para campos sem resposta nos estágios anteriores
  ▼
DataGenerator            Usa dados reais do CompanyProfile quando disponíveis;
  │                      fallback automático para Faker em campos não extraídos.
  ▼
FormFiller               Preenche cada campo com o valor gerado.
  │                      Estratégias por tipo: text, email, select, combobox, radio, checkbox, file, date.
  ▼
NavigationOrchestrator   Gerencia formulários multi-página, detecta botões "Próximo" e
                         identifica a página de confirmação de envio. Preenche campos
                         condicionais em loop até o DOM estabilizar (_fill_until_stable).
```

## Instalação

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
playwright install chromium
```

Crie um arquivo `.env` na raiz baseado no `.env.example`:

```
GEMINI_API_KEY=sua_chave_aqui

# false = preenche e para antes do Submit (padrão/seguro para testes)
# true  = submete o formulário (somente em produção autorizada)
ALLOW_FORM_SUBMIT=false

# Email real da empresa — usado em campos de e-mail dos formulários.
# O Cartão CNPJ da Receita Federal não contém e-mail; defina aqui para
# que formulários recebam o e-mail real da empresa (opcional).
COMPANY_EMAIL=seu_email@empresa.com.br
```

## Como executar

```powershell
$env:PYTHONPATH = "app"
python app\run.py <URL_DO_PORTAL> <NOME_DO_PORTAL>
```

### Exemplos

```powershell
# Execução padrão — abre browser visível, descobre e preenche o formulário
python app\run.py "https://portal.example.com/cadastro" vulcaflex

# Sem interface gráfica (CI/automação)
python app\run.py "https://portal.example.com" empresa --headless

# Com delay entre campos (portais sensíveis a digitação rápida)
python app\run.py "https://portal.example.com" empresa --slow-fill

# Informando o iframe diretamente (pula a etapa de discovery)
python app\run.py "https://portal.example.com" empresa --iframe 'iframe[src*="forms.office.com"]'

# Ajuda completa
python app\run.py --help
```

### Opções

| Opção | Padrão | Descrição |
|---|---|---|
| `--headless` | `False` | Roda sem janela do browser |
| `--slow-fill` | `False` | Delay extra entre campos |
| `--max-pages` | `15` | Limite de páginas do formulário |
| `--iframe` | auto | Seletor CSS do iframe, se já conhecido |
| `--audit-dir` | `./audit` | Raiz dos artefatos de auditoria (logs + screenshots) |
| `--per-question-shots` / `--no-per-question-shots` | `True` | Tira 1 screenshot por pergunta preenchida (cobertura 100%) |
| `--model` | `gemma-4-26b-a4b-it` | Modelo Gemma para classificação e extração de documentos |
| `--docs-dir` | — | Diretório com PDFs reais da empresa — extrai antes de abrir o browser |
| `--no-cache` | `False` | Força reprocessamento dos PDFs mesmo que cache esteja disponível |
| `--clear-cls-cache` | `False` | Limpa o cache de classificação semântica (`~/.url_discovery/cls_cache.json`) |
| `--submit` / `--no-submit` | env | Sobrescreve `ALLOW_FORM_SUBMIT` do `.env` |

### Usando dados reais da empresa

Coloque os PDFs em `docs/` (pasta ignorada pelo git) e execute com `--docs-dir`:

```powershell
python app\run.py "https://portal.example.com" empresa --docs-dir ./docs --no-submit
```

O agente detecta automaticamente o tipo de cada documento:

| Documento | Campos extraídos |
|---|---|
| Cartão CNPJ (Receita Federal) | CNPJ, Razão Social, Nome Fantasia, CNAE, Endereço, CEP, Cidade, UF, Telefone, E-mail |
| Contrato Social / Alteração | Sócio principal, CPF do sócio, Objeto Social |
| Demonstrações Financeiras / Extrato | Banco, Agência, Conta, Favorecido, Faturamento, Período |

**Fluxo com `--docs-dir`:**

1. Documentos são extraídos **antes** de abrir o browser (~3 min com OCR)
2. Campos críticos (`cnpj`, `razao_social`) e dados bancários são validados com aviso
3. Browser abre já com o perfil montado — preenchimento usa dados reais

```
→ Carregando documentos reais de: docs
→ Perfil carregado: EMPRESA LTDA / CNPJ: 00.000.000/0001-00
✓  Todos os campos essenciais extraídos dos documentos.
→ Abrindo portal: ...
```

**PDFs escaneados (sem texto):** suportados via OCR automático com `gemma-4-26b-a4b-it` Vision. O modelo recebe as páginas renderizadas em PNG a 300 DPI. Tempo médio: ~2 min por documento escaneado.

**E-mail de contato:** extraído do campo "ENDEREÇO ELETRÔNICO" do Cartão CNPJ. Caso o documento não contenha esse campo, defina `COMPANY_EMAIL` no `.env` como fallback.

**Fallback automático:** campos ausentes nos documentos são preenchidos com Faker — transparente, sem erro.

### Exemplos com controle de submissão

```powershell
# Padrão: preenche e para antes do Submit (seguro para testes)
python app\run.py "https://portal.example.com" empresa

# Forçar não-submissão mesmo que .env diga true
python app\run.py "https://portal.example.com" empresa --no-submit

# Habilitar submissão via flag (produção)
python app\run.py "https://portal.example.com" empresa --submit
```

## Auditoria de logs e screenshots

Cada execução grava **todas as evidências no mesmo lugar**: o log estruturado da sessão e os screenshots de cada pergunta preenchida ficam juntos, na pasta do portal.

```
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
```

**Cobertura de 100% das questões.** Além da visão completa de cada página, o agente tira **um screenshot por pergunta preenchida** — o campo é rolado até a viewport, destacado com um contorno e fotografado junto do seu rótulo e do valor preenchido. Grupos de radio/checkbox (ex.: "selecione as categorias") geram uma evidência por grupo, não por opção.

O `manifest.json` registra, por pergunta: rótulo, tipo semântico, valor preenchido, confiança da classificação e o caminho do screenshot — e um resumo de cobertura (`questions`, `captured`, `coverage_pct`). O `README.md` da execução traz a mesma informação em tabela, com links clicáveis para cada imagem.

| Opção | Efeito |
| --- | --- |
| `--audit-dir <caminho>` | Muda a raiz dos artefatos (padrão `./audit`) |
| `--no-per-question-shots` | Mantém só a visão geral por página (mais rápido, sem print por pergunta) |
| `--log-file-path <arquivo>` | Salva o log fora da pasta de auditoria (screenshots continuam em `audit/`) |

> A pasta `audit/` é ignorada pelo git (saída local de execução, igual aos logs).

## Controle de Submissão

**Por padrão o agente nunca envia dados.** O pipeline completo roda — descoberta, crawl, classificação, geração de valores e preenchimento — mas o clique no botão final (Submit / Enviar) é bloqueado.

Isso garante que execuções de teste, CI e desenvolvimento não enviem dados reais a portais de fornecedores.

### Resultado `SUBMIT_BLOCKED`

Quando `ALLOW_FORM_SUBMIT=false` e o agente chega ao botão de submissão final, o log exibe:

```
[warning] submit_blocked  page=2  portal=...  reason=ALLOW_FORM_SUBMIT=false
```

E o relatório final mostra `Resultado: SUBMIT_BLOCKED` — indicando que o formulário foi preenchido com sucesso e estava pronto para envio, mas a submissão foi bloqueada por configuração.

### Habilitando a submissão

1. **Via `.env`** (persistente — afeta todas as execuções):
   ```
   ALLOW_FORM_SUBMIT=true
   ```

2. **Via flag CLI** (pontual — sobrescreve o `.env`):
   ```powershell
   python app\run.py "https://portal.example.com" empresa --submit
   ```

> **Atenção:** antes de habilitar, valide os screenshots gerados na pasta de auditoria (ver seção [Auditoria](#auditoria-de-logs-e-screenshots)) para confirmar que os dados estão corretos para o portal específico. O classificador semântico nem sempre acerta 100% dos campos.

### Validar extração antes de rodar

Para inspecionar quais campos foram extraídos dos PDFs sem abrir o browser:

```powershell
python app\validate_docs.py
```

Saída esperada com os 3 documentos configurados:

```
============================================================
  COMPANY PROFILE EXTRAIDO
============================================================
  [OK]   CNPJ                   00.000.000/0001-00
  [OK]   Razao Social           EMPRESA LTDA
  [OK]   Banco                  Nubank
  [OK]   Agencia                0001
  [OK]   Conta                  000000000-0
  ...
  Campos preenchidos: 17/20
============================================================
```

## Como executar os testes

```powershell
$env:PYTHONPATH = "app"
python -m pytest app\tests -v
```

## Estrutura do projeto

```
app/
  run.py                          CLI — ponto de entrada principal
  domain/
    entities/
      form.py                     Modelos: FormField, FormPage, FormSession, SemanticType
      company_profile.py          CompanyProfile — dados reais extraídos de PDFs
    services/
      classifier_port.py          Port (interface) do classificador semântico
      classifier.py               Classificação em 2 estágios: heurística → LLM fallback
      generator.py                DataGenerator — dados reais (perfil) com fallback fake
      document_extractor.py       DocumentExtractor — lê PDFs e monta CompanyProfile
  infrastructure/
    formaters.py                  Formatadores: CNPJ, CPF, telefone, CEP, e-mail corporativo
    browser/
      portal_discovery.py         PortalDiscovery — encontra o formulário no portal
      crawler.py                  DOMCrawler — extrai campos do DOM com labels
      filler.py                   FormFiller — preenche campos por tipo + screenshots
      navigator.py                NavigationOrchestrator — fluxo multi-página
    audit/
      audit_session.py            AuditSession — logs + screenshots por execução (manifest/README)
    llm/
      gemma_adapter.py            GemmaClassifier — classifica campos (3 estágios: heurística → cache → LLM)
      heuristic.py                Classificação local por regex/keywords (zero chamadas de API)
      cls_cache.py                Cache persistente de classificações semânticas
    pdf/
      pdf_reader.py               Extração de texto e detecção de tipo de documento
      gemma_extractor.py          Extração estruturada de campos via Gemma (JSON)
  tests/                          Testes unitários e de integração
  portals/                        Documentação de portais analisados
urls                              Lista de portais mapeados
```

## Portais documentados

- AngloGold Ashanti
- Jaguar Mining

## Arquitetura

Hexagonal simplificada: `domain/` não depende de nada externo. `infrastructure/` implementa os ports. `run.py` orquestra tudo.

O classificador (`GemmaClassifier`) é trocável — qualquer implementação de `ClassifierPort` funciona. A classificação opera em 3 estágios: heurística local por regex (sem API) → cache persistente em `~/.url_discovery/cls_cache.json` → Gemma via API apenas para campos sem resposta nos estágios anteriores. Se a `GEMINI_API_KEY` não estiver configurada, campos não cobertos pela heurística são classificados como `UNKNOWN`.

### Prioridade de resolução de valores

Para cada campo do formulário, o `DataGenerator` aplica esta ordem:

1. **Dado real dos PDFs** — campo correspondente no `CompanyProfile`
2. **`COMPANY_EMAIL`** (apenas campos de e-mail) — variável do `.env`, usado quando o Cartão CNPJ não contém "ENDEREÇO ELETRÔNICO"
3. **Faker** — geração automática como fallback final

Variáveis de ambiente relevantes:

| Variável | Obrigatória | Descrição |
|---|---|---|
| `GEMINI_API_KEY` | Sim | Chave da API Google AI (Gemma) |
| `ALLOW_FORM_SUBMIT` | Não | `true` para submeter formulários (padrão: `false`) |
| `COMPANY_EMAIL` | Não | E-mail real da empresa para campos de contato |
