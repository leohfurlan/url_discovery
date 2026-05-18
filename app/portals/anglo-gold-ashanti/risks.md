# Portal: anglo-gold-ashanti

**URL de entrada:** https://www.anglogoldashanti.com.br/fornecedores/
**URL do formulário:** https://forms.office.com/pages/responsepage.aspx?id=fksHnnCQs0inUeM698H4-1cQwu8TX79CrqJ-qCil_whUQ1BGNkZLUDNPNTZLSk5TUkYwTUlCV1hBSS4u&origin=lprLink&route=shorturl
**Plataforma:** Microsoft Forms (forms.office.com)
**Total de páginas:** 1
**Analisado em:** 2026-05-18

---

## Resumo executivo

```text
0 riscos altos
1 risco médio  — CNPJ sem máscara (mesmo padrão da Jaguar)
1 risco baixo  — Microsoft Forms em iframe (já resolvido na Jaguar)
```

Formulário mais simples do escopo. 6 campos de texto curto, uma página, sem
lógica condicional, sem uploads, sem perguntas encadeadas. O agente que funciona
na Jaguar cobre este portal sem nenhuma alteração de arquitetura.

---

## Risco estrutural (transversal)

### [BAIXO] Microsoft Forms em iframe

- **Descrição:** mesmo padrão da Jaguar — formulário incorporado via iframe do `forms.office.com`.
- **Impacto:** baixo, pois o frame switching já estará implementado como parte da solução base.
- **Estratégia:** reutilizar `frame_locator` implementado para a Jaguar sem modificação.

---

## Riscos por campo

### [MÉDIO] CNPJ sem máscara automática

- **Descrição:** mesmo comportamento identificado na Jaguar (pág. 5) — o campo espera pontuação manual.
- **Impacto:** `Faker` gera CNPJ sem formatação e o campo pode rejeitar ou registrar incorretamente.
- **Estratégia:** reutilizar `format_cnpj()` do `formatters.py` já previsto no projeto.

---

### Demais campos — sem risco identificado

| Campo | Tipo | Estratégia |
|---|---|---|
| Razão Social | Texto curto | `fake.company()` |
| Atividade da empresa | Texto curto | `fake.bs()` ou CNAE fixo |
| Nome para contato | Texto curto | `fake.name()` |
| Telefone para contato | Texto curto | `fake.phone_number()` formatado |
| Email para contato | Texto curto | `fake.company_email()` |

- **Observação sobre e-mail:** ao contrário da Jaguar, não há indicação de validação de domínio. `Faker.company_email()` deve ser suficiente. Monitorar se houver rejeição na execução.

---

## Matriz consolidada de riscos

| Risco | Campo | Nível | Fase de tratamento |
|---|---|---|---|
| Microsoft Forms em iframe | Todos | Baixo | Dia 1 — reuso da solução Jaguar |
| CNPJ sem máscara | CNPJ | Médio | Dia 3 — reuso de `formatters.py` |

---

## Decisões de design recomendadas

```text
1. Não criar adapter específico para este portal
   → o adapter genérico cobre 100% dos campos

2. Usar como caso de validação do agente no Dia 3
   → formulário previsível ideal para smoke test ponta a ponta
   → se o agente falhar aqui, o problema é na base, não no portal

3. Priorizar este portal antes da Jaguar nos testes iniciais
   → menos variáveis, feedback mais rápido
```

---

## Arquivos de suporte necessários

```text
portals/
└── anglo-gold-ashanti/
    ├── risks.md               ← este arquivo
    ├── screenshots/           ← captura da página única
    └── field_map.json         ← output do DOM crawler (Dia 1)
```