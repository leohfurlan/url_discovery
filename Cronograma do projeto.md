# Objetivo do projeto

Desenvolver um agente de automação inteligente capaz de:

* interpretar formulários web dinamicamente
* identificar semanticamente os campos solicitados
* gerar dados fictícios
* preencher formulários automaticamente
* navegar entre múltiplas etapas
* adaptar-se a diferentes layouts sem hardcode específico

---

# Estimativa total

```text
7 a 10 dias úteis
```

Considerando:

* desenvolvimento em meio período
* necessidade de adaptação dinâmica
* comportamento variável dos portais
* debugging de automação web
* refinamento da camada de IA

---

# Escopo funcional esperado

## Entrada

* URL do portal
* parâmetros básicos de execução

## Processamento

* leitura do DOM
* parsing de campos
* classificação semântica via IA
* geração de dados fictícios
* preenchimento automático
* upload de documentos fake
* navegação entre páginas

## Saída

* formulário preenchido
* logs estruturados
* screenshots da execução
* evidências do fluxo

---

# Cronograma estimado

## Fase 1 — Discovery e Setup

Estimativa: 1 dia útil

### Atividades

* análise dos portais
* setup da stack
* validação Playwright
* identificação de riscos

### Entrega

```text
Navegação automatizada funcionando.
```

---

## Fase 2 — Parsing e Interpretação

Estimativa: 2 dias úteis

### Atividades

* parser de formulários
* extração estruturada
* classificação semântica via IA

### Entrega

```text
IA compreendendo os campos dinamicamente.
```

---

## Fase 3 — Preenchimento Automatizado

Estimativa: 2 dias úteis

### Atividades

* geração de dados fake
* preenchimento automático
* upload de arquivos
* navegação entre etapas

### Entrega

```text
Fluxo automatizado funcionando ponta a ponta nos portais base.
```

---

## Fase 4 — Generalização e Robustez

Estimativa: 2 a 3 dias úteis

### Atividades

* refinamento heurístico
* redução de dependência específica
* tratamento de erros
* validação em novo portal

### Entrega

```text
Agente adaptável para terceiro portal inédito.
```

---

# Riscos identificados

* captcha
* MFA/autenticação externa
* validação documental real
* bloqueios anti-bot
* componentes altamente dinâmicos
* iframes complexos
* upload com validação server-side

---

# Estratégia técnica resumida

## Stack principal

* Python
* Playwright
* LLM desacoplado via adapters
* Faker

## Arquitetura

```text
Arquitetura modular orientada a adaptabilidade e troca de componentes de IA.Hexagonal simplificada + fluxo agentic modular
```

## Estratégia de qualidade

```text
TDD seletivo
+
testes de integração
+
logs e screenshots automatizados
```
