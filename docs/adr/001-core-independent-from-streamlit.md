# ADR 001 — Core independente do Streamlit

- Status: Accepted
- Date: 2026-09-06

## Contexto

O produto precisa funcionar standalone hoje e ser embutido em outro Streamlit amanhã, sem
transformar `st.session_state` em banco de dados ou acoplar execução operacional ao ciclo de
rerun da UI.

## Decisão

Modelos, grafo, engine, policies, worker, serialização e persistência permanecem em módulos
Python sem dependência de Streamlit. A apresentação usa `FlowOpsPage`/`FlowOpsUI` e chama o
runtime por composição.

## Consequências

- engine pode ser reutilizado por testes, API ou CLI;
- reruns da UI não alteram estado durável implicitamente;
- hosts corporativos integram apenas identidade/contexto e não precisam conhecer detalhes do
  engine;
- a UI não pode introduzir regras de segurança que não existam também abaixo dela.
