# Portal: jaguar-mining

**URL de entrada:** https://www.jaguarmining.com/contact/fornecedores
**URL do formulário:** https://forms.office.com/pages/responsepage.aspx?id=xebB3yjtcUaXaLD5aIpSDazPmPDG_JtHqpTriq_E7EFUMFlEWlc3NjlDNTc4RDI3SktTQlFBUDA4VCQlQCN0PWcu&route=shorturl
**Plataforma:** Microsoft Forms (forms.office.com)
**Total de páginas:** 10
**Analisado em:** 2026-05-18

---

## Resumo executivo

```text
5 riscos altos  — bloqueiam execução sem tratamento explícito
4 riscos médios — contornáveis com lógica adicional
2 riscos baixos — seleção direta, sem bloqueio técnico
```

O risco estrutural dominante é o uso de **Microsoft Forms dentro de um iframe**,
que afeta todas as 10 páginas antes de qualquer lógica de preenchimento.

---

## Risco estrutural (transversal a todas as páginas)

### [ALTO] Microsoft Forms em iframe

- **Localização:** todas as páginas
- **Descrição:** o formulário não roda diretamente no domínio da Jaguar — está incorporado via iframe do `forms.office.com`. O Playwright opera no contexto da página pai e não enxerga os elementos do formulário sem frame switching explícito.
- **Impacto:** nenhuma interação com campos funciona sem resolver este ponto primeiro.
- **Estratégia:**
  ```python
  # Localizar o iframe pelo domínio forms.office.com
  frame = page.frame_locator('iframe[src*="forms.office.com"]')
  # Todas as interações subsequentes via frame, não via page
  frame.locator('input[type="radio"]').first.click()
  ```
- **Pré-requisito para:** todos os demais blocos do agente.

---

## Riscos por página

### Página 1 — Tipo de fornecedor

| Campo | Tipo | Risco | Nível |
|---|---|---|---|
| Tipo de fornecedor | Radio único | Nenhum | Baixo |

- **Estratégia:** selecionar opção padrão configurável via parâmetro de execução.

---

### Página 2 — Normativas e expectativas

| Campo | Tipo | Risco | Nível |
|---|---|---|---|
| Li e aceito os termos | Seleção única | Nenhum | Baixo |
| Documentação necessária | Checkboxes múltiplas obrigatórias | Baixo | Baixo |

- **Documentação necessária:** 5 opções (Cartão CNPJ, Contrato social, Demonstrações financeiras, Certificado de qualidade, Certificado SSCA). Selecionar todas por padrão é a abordagem mais segura e não gera rejeição.

---

### Página 3 — Questionário de integridade

#### [ALTO] Perguntas encadeadas em cascata

- **Descrição:** 12 perguntas de sim/não onde cada resposta revela a pergunta seguinte via AJAX. O DOM muda após cada interação — o formulário não exibe todas as perguntas de uma vez.
- **Impacto:** o parser não pode extrair o formulário completo em uma única leitura. Qualquer abordagem de "parsear tudo e depois preencher" falha.
- **Estratégia:**
  ```python
  # Loop: responder → aguardar DOM estabilizar → detectar nova pergunta → repetir
  while nova_pergunta_visivel():
      responder_nao()
      page.wait_for_load_state("networkidle")
      re_parsear_perguntas_visiveis()
  ```
- **Decisão de design recomendada:** responder "Não" para todas as perguntas de integridade. Isso elimina a necessidade de gerar justificativas e reduz o loop a ~12 iterações previsíveis.

#### [ALTO] Campo de texto condicional ao "Sim"

- **Descrição:** qualquer pergunta respondida com "Sim" abre campo de texto livre pedindo descrição da situação.
- **Impacto:** o Faker não gera texto juridicamente coerente para esse contexto. Um `lorem ipsum` provavelmente passa tecnicamente, mas é semanticamente inválido.
- **Estratégia (se "Sim" for necessário):** acionar LLM com prompt contextualizado para gerar justificativa plausível. Ex:
  ```python
  prompt = f"Gere uma resposta curta e plausível para: '{pergunta}'. Tom: formal, empresarial, sem admitir irregularidade."
  ```
- **Estratégia preferencial:** manter todas as respostas como "Não" e nunca disparar este campo.

---

### Página 4 — Tratamento de dados pessoais (LGPD)

| Campo | Tipo | Risco | Nível |
|---|---|---|---|
| Aceite LGPD | Checkbox | Nenhum | Baixo |
| Declaração de não parentesco | Seleção única | Nenhum | Baixo |

- **Estratégia:** aceitar LGPD e selecionar "Não" na declaração de parentesco.

---

### Página 5 — Dados cadastrais

#### [MÉDIO] CNPJ/CPF sem máscara automática

- **Descrição:** o campo não aplica máscara automaticamente. O usuário deve digitar pontuação manualmente. Faker gera `12345678000195` — o campo espera `12.345.678/0001-95`.
- **Estratégia:**
  ```python
  # formatters.py
  def format_cnpj(raw: str) -> str:
      d = re.sub(r'\D', '', raw)
      return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}"
  ```

#### [MÉDIO] Inscrição Estadual/Municipal com condicional

- **Descrição:** seleção de "Isento" oculta campo de texto; "Outra" revela input adicional para o número.
- **Estratégia:** selecionar "Isento" para simplificar. Se precisar de número real, gerar valor fictício e formatar antes do preenchimento.

---

### Página 6 — Endereço

#### [MÉDIO] CEP sem máscara automática

- **Descrição:** mesmo padrão do CNPJ. O campo espera `12345-678` com traço manual.
- **Estratégia:**
  ```python
  def format_cep(raw: str) -> str:
      d = re.sub(r'\D', '', raw)
      return f"{d[:5]}-{d[5:8]}"
  ```

| Campo | Observação |
|---|---|
| UF | Listbox — selecionar por valor (ex: `SP`) |
| País | Campo texto livre — preencher `Brasil` |

---

### Página 7 — Dados de contato

#### [ALTO] Validação de domínio de e-mail

- **Descrição:** o campo exige que o e-mail tenha domínio da empresa (`nome@empresa.com.br`). E-mails com domínios públicos (gmail, hotmail, yahoo) são sinalizados e podem ser rejeitados.
- **Impacto:** `Faker.email()` gera domínios genéricos e falha na validação.
- **Estratégia:** compor o e-mail usando o domínio derivado do nome fantasia gerado:
  ```python
  nome_fantasia_slug = slugify(fake.company())  # ex: "construtora-alpha"
  email = f"contato@{nome_fantasia_slug}.com.br"
  ```
- **Observação:** Contato 2 é opcional — pular para reduzir complexidade.

---

### Página 8 — Dados comerciais

#### [ALTO] Categorias condicionais após classificação de fornecedor

- **Descrição:** selecionar "materiais", "serviços" ou "materiais e serviços" revela lista longa de checkboxes de categoria via AJAX. O DOM muda após a seleção.
- **Impacto:** mesmo padrão da página 3 — parser precisa re-rodar após seleção.
- **Estratégia:**
  ```python
  selecionar_classificacao("serviços")
  page.wait_for_load_state("networkidle")
  categorias = re_parsear_checkboxes_visiveis()
  selecionar_primeira_categoria(categorias)
  ```
- **Decisão de design:** selecionar apenas 1 categoria por padrão para minimizar interações.

---

### Página 9 — Dados bancários e fiscais

#### [MÉDIO] Banco via listbox com código + nome

- **Descrição:** a lista exibe entradas no formato `"001 - BANCO DO BRASIL"`. Selecionar por texto exato é frágil se o Faker gerar nome diferente do esperado pela lista.
- **Estratégia:** manter lista fixa dos bancos mais comuns e selecionar por valor exato:
  ```python
  BANCOS_VALIDOS = ["001 - BANCO DO BRASIL", "033 - SANTANDER", "237 - BRADESCO", "341 - ITAÚ UNIBANCO"]
  banco = random.choice(BANCOS_VALIDOS)
  ```

- **Conta/agência com dígito:** gerar número fictício no formato `NNNN-D` (agência) e `NNNNN-D` (conta). Não há validação de existência real esperada aqui.

---

### Página 10 — Demais informações

| Campo | Tipo | Estratégia |
|---|---|---|
| Porte de empresa | Seleção única | Selecionar "Pequena Empresa" como padrão |
| Descrição das atividades | Texto livre | LLM ou Faker sentences com contexto do CNAE |
| Comentários/Observações | Texto livre, opcional | Deixar em branco |
| Top 5 clientes | Texto livre, opcional | Deixar em branco |

---

## Matriz consolidada de riscos

| Risco | Página | Nível | Fase de tratamento |
|---|---|---|---|
| Microsoft Forms em iframe | Todas | Alto | Dia 1 — setup Playwright |
| Perguntas encadeadas em cascata | 3 | Alto | Dia 3 — navegação multi-step |
| Campo de texto condicional ("Sim") | 3 | Alto | Dia 3 — geração LLM condicional |
| Validação de domínio de e-mail | 7 | Alto | Dia 3 — formatters |
| Categorias condicionais AJAX | 8 | Alto | Dia 3 — re-parse pós-seleção |
| CNPJ/CPF sem máscara | 5 | Médio | Dia 3 — formatters.py |
| Inscrição Estadual/Municipal condicional | 5 | Médio | Dia 3 — lógica condicional |
| CEP sem máscara | 6 | Médio | Dia 3 — formatters.py |
| Banco via listbox com código | 9 | Médio | Dia 3 — lista fixa de valores |
| Checkboxes múltiplas obrigatórias | 2 | Baixo | Dia 2 — parser padrão |
| Aceites LGPD/declarações | 4 | Baixo | Dia 2 — parser padrão |

---

## Decisões de design recomendadas

```text
1. Responder "Não" para todas as perguntas de integridade (pág. 3)
   → elimina loop de justificativa via LLM
   → reduz 12 interações AJAX a sequência previsível

2. Selecionar "Isento" para Inscrição Estadual e Municipal (pág. 5)
   → evita lógica condicional de campo extra

3. Pular Contato 2 (pág. 7)
   → campos opcionais não agregam cobertura de teste

4. Selecionar "serviços" como classificação padrão (pág. 8)
   → subset menor de categorias, menos interações

5. Deixar campos opcionais em branco (pág. 10)
   → Comentários, Top 5 Clientes — sem impacto na submissão
```

---

## Arquivos de suporte necessários

```text
portals/
└── jaguar-mining/
    ├── risks.md               ← este arquivo
    ├── screenshots/           ← capturas manuais de cada página
    └── field_map.json         ← output do DOM crawler (Dia 1)

infrastructure/
└── formatters.py              ← CNPJ, CEP, e-mail de domínio (Dia 3)
```