# ADR-014 — Catálogo DynamoDB de runbooks com fallback local do navegador

## Contexto

O editor precisa sincronizar definições reutilizáveis para uma implantação AWS sem transformar
o histórico de execução em estado de sessão do Streamlit. A mesma instalação também deve ser
explorável sem conta AWS e sem depender de uma tabela previamente criada.

## Decisão

- O catálogo de definições usa uma tabela DynamoDB configurável por `FLOWOPS_CATALOG_TABLE`
  (padrão `flowops-runbook-catalog`) com `BillingMode=PAY_PER_REQUEST`.
- A tabela é criada sob demanda somente quando o host salva uma definição; a chave composta
  `ACCOUNT#<conta>#TEAM#<equipe>` / `RUNBOOK#<id>#VERSION#<versão>` evita mistura entre contas,
  equipes e versões. Itens são limitados a 300 KB.
- O provider valida o contexto confiável antes de obter o cliente. O catálogo não recebe
  credenciais nem endpoint arbitrário do runbook.
- Se a tabela estiver indisponível, a UI grava uma cópia limitada no `localStorage` por origem,
  conta e usuário, usando o componente Streamlit v2. A cópia pode ser restaurada como novo
  draft; ela não é usada para executar, aprovar ou auditar.
- `Repository` (SQLite/PostgreSQL) continua sendo a fonte de verdade para drafts, versões,
  snapshots, fila, checkpoints, aprovações e auditoria. Fechar o navegador não interrompe uma
  execução já submetida.

## Consequências

O caminho comum em ECS usa DynamoDB on-demand para o índice de baixo volume, sem capacidade
ociosa. A recuperação no navegador melhora a continuidade quando a tabela não existe ou está
temporariamente indisponível, mas não oferece compartilhamento entre dispositivos e deve ser
tratada como cópia não confiável. Limpar os dados do site ou trocar de navegador remove a cópia.

No modo local, a mesma implementação aponta para o DynamoDB do Moto Server. O teste de integração
verifica criação idempotente, escopo por conta/equipe e reexecução após reinício; a equivalência
com IAM, quotas e consistência de uma conta AWS real continua sendo validada em homologação.

## Rejeitadas

- usar somente `st.session_state` para persistir runbooks ou execuções;
- salvar tokens, receipt handles ou respostas de AWS no `localStorage`;
- usar Aurora/PostgreSQL para o índice barato de catálogo;
- permitir que um erro no catálogo impeça a gravação durável do draft no Repository.
