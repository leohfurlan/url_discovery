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

Crie um arquivo `.env` na raiz baseado no `.env.example`:

```
GEMINI_API_KEY=sua_chave_aqui

# false = preenche e para antes do Submit (padrão/seguro para testes)
# true  = submete o formulário (somente em produção autorizada)
ALLOW_FORM_SUBMIT=false
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
| `--submit` / `--no-submit` | env | Sobrescreve `ALLOW_FORM_SUBMIT` do `.env` |

### Exemplos com controle de submissão

```powershell
# Padrão: preenche e para antes do Submit (seguro para testes)
python app\run.py "https://portal.example.com" empresa

# Forçar não-submissão mesmo que .env diga true
python app\run.py "https://portal.example.com" empresa --no-submit

# Habilitar submissão via flag (produção)
python app\run.py "https://portal.example.com" empresa --submit
```

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

> **Atenção:** antes de habilitar, valide o screenshot gerado (`--screenshots`) para confirmar que os dados estão corretos para o portal específico. O classificador semântico nem sempre acerta 100% dos campos.

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
