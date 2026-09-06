# ADR 002 — Draft mutável, publicação imutável e export determinístico

- Status: Accepted
- Date: 2026-09-06

## Contexto

Operações auditáveis precisam reproduzir exatamente a definição executada, enquanto autores
precisam editar runbooks de forma concorrente e versioná-los em Git.

## Decisão

Drafts usam revisão compare-and-swap. Publicação cria uma nova versão insert-only com digest
da definição. Execuções carregam snapshot e digest. YAML/JSON de exportação é determinístico e
importação cria novo draft por padrão.

## Consequências

- histórico publicado não é reescrito;
- uma execução pode provar qual definição utilizou;
- conflitos de edição aparecem antes de sobrescrever outro autor;
- arquivos exportados podem participar de revisão/GitOps sem serem a fonte autoritativa da
  execução em andamento.
