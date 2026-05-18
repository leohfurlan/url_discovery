# URL Discovery

Projeto Python para mapear portais de fornecedores, registrar fluxos de acesso e preparar a base para automatizar a descoberta e o preenchimento de formularios com uma arquitetura modular.

## Objetivo

A ideia inicial do projeto e evoluir para uma aplicacao de IA com componentes trocaveis, permitindo substituir o LLM com facilidade e adicionar agentes especializados. Nesta fase, o repositorio contem:

- entidades de dominio para representar formularios, paginas, campos e resultados de execucao;
- formatadores para dados comuns do Brasil, como CNPJ, CPF, telefone, CEP e e-mail corporativo;
- crawler com Playwright para validar acesso a formularios e capturar screenshots;
- documentacao inicial de portais e riscos;
- testes automatizados para formatadores e entidades.

## Estrutura

```text
app/
  domain/entities/        Modelos de dominio dos formularios
  infrastructure/         Formatadores e integracoes de infraestrutura
  infrastructure/browser/ Crawler baseado em Playwright
  portals/                Documentacao por portal analisado
  tests/                  Testes automatizados
  doc/                    Escopo e documentacao geral
urls                      Lista inicial de portais analisados
```

## Requisitos

- Python 3.13 ou superior
- pip
- Playwright Chromium

Dependencias Python usadas atualmente:

- `pydantic`
- `pytest`
- `playwright`

## Instalacao

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install pydantic pytest playwright
playwright install chromium
```

## Como executar os testes

Os testes esperam que a pasta `app` esteja no `PYTHONPATH`.

```powershell
$env:PYTHONPATH = "app"
pytest app\tests
```

## Como executar o crawler

```powershell
$env:PYTHONPATH = "app"
python app\infrastructure\browser\crawler.py
```

O crawler atual abre o navegador, acessa o formulario configurado no arquivo e gera screenshots locais. Esses arquivos de imagem sao ignorados pelo Git porque sao artefatos de execucao.

## Portais documentados

- AngloGold Ashanti
- Jaguar Mining

## Observacoes para GitHub

O `.gitignore` ja evita subir ambiente virtual, caches, arquivos temporarios, logs, bancos locais, segredos de ambiente e screenshots gerados pelo crawler.
