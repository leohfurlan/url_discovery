# URL Discovery — Agente de Preenchimento de Formulários

Agente Python que acessa portais de fornecedores, descobre o formulário de cadastro automaticamente e o preenche com dados gerados por IA — sem intervenção manual.

## Como funciona

O agente recebe a **URL pública do portal** (não o link direto do formulário). O pipeline é:

```
URL do portal
  │
  ▼
PortalDiscovery          Detecta iframe embutido, link ou botão que leva ao formulário.
  │                      Suporta Microsoft Forms, Google Forms, Typeform, JotForm, etc.
  ▼
DOMCrawler               Extrai campos do DOM (input, select, textarea, labels, opções).
  │                      Suporta iframes — Microsoft Forms é sempre servido em iframe.
  ▼
GemmaClassifier          Classifica cada campo semanticamente via Gemini API
  │                      (CNPJ, Razão Social, E-mail corporativo, Estado, etc.)
  ▼
DataGenerator            Gera valores coerentes entre si:
  │                      e-mail corporativo usa o mesmo domínio da razão social gerada.
  ▼
FormFiller               Preenche cada campo com o valor gerado.
  │                      Estratégias por tipo: text, email, select, checkbox, radio, file.
  ▼
NavigationOrchestrator   Gerencia formulários multi-página, detecta botões "Próximo" e
                         identifica a página de confirmação de envio.
```

## Instalação

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
playwright install chromium
```

Crie um arquivo `.env` na raiz com sua chave da Gemini API:

```
GEMINI_API_KEY=sua_chave_aqui
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
| `--screenshots` | `/tmp` | Diretório para salvar screenshots |
| `--model` | `gemma-4-26b-a4b-it` | Modelo Gemini para classificação |

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
    entities/form.py              Modelos: FormField, FormPage, FormSession, SemanticType
    services/
      classifier_port.py          Port (interface) do classificador semântico
      generator.py                DataGenerator — gera dados fake coerentes
  infrastructure/
    formaters.py                  Formatadores: CNPJ, CPF, telefone, CEP, e-mail corporativo
    browser/
      portal_discovery.py         PortalDiscovery — encontra o formulário no portal
      crawler.py                  DOMCrawler — extrai campos do DOM com labels
      filler.py                   FormFiller — preenche campos por tipo
      navigator.py                NavigationOrchestrator — fluxo multi-página
    llm/
      gemma_adapter.py            GemmaClassifier — classifica campos via Gemini API
  tests/                          Testes unitários e de integração
  portals/                        Documentação de portais analisados
urls                              Lista de portais mapeados
```

## Portais documentados

- AngloGold Ashanti
- Jaguar Mining

## Arquitetura

Hexagonal simplificada: `domain/` não depende de nada externo. `infrastructure/` implementa os ports. `run.py` orquestra tudo.

O classificador (`GemmaClassifier`) é trocável — qualquer implementação de `ClassifierPort` funciona. Se a `GEMINI_API_KEY` não estiver configurada, todos os campos são classificados como `UNKNOWN` e o gerador usa valores genéricos.
