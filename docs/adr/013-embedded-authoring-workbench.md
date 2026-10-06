# 013 — Área de autoria React embutida

Data: 16/09/2026. Validação atualizada em 27/09/2026. Decisão: componente delimitado implementado; validação automatizada local concluída, com CI remota da árvore candidata e avaliação humana ainda pendentes.

## Contexto

O primeiro recorte de autoria visual reaproveitou os formulários Streamlit. O proprietário pediu explicitamente uma experiência mais próxima do seu `starter-react-lib/apps/builder`, autorizando seu reúso. Formulários isolados não entregavam a mesma composição de biblioteca, superfície de trabalho e inspetor contextual.

## Decisão

Introduzir `frontend/flow-editor` com React e React Flow, somente na visão **Canvas avançado**, padrão do editor. Adaptar a composição do workbench autorizado, sem importar módulos SaaS, dependências privadas, infraestrutura ou credenciais. Usar CSS local e elementos de formulário nativos; não combinar bibliotecas de design adicionais. Manter os formulários recursivos especializados existentes em **Configuração completa**: uma migração completa deles para React continua uma decisão futura, dependente de evidência de uso.

O único contrato persistido continua `Runbook`. A bridge usa mensagens versionadas e limitadas, com revisão otimista e autorização no Python. A aplicação é atômica em uma cópia do rascunho. A seleção e os buffers não causam chamadas AWS. O código JSON chega como texto para evitar perda de precisão de números. Os ativos e avisos de licença são distribuídos no pacote Python, sem CDN ou serviço extra.

## Consequências

Node passa a ser necessário para desenvolver/reconstruir o componente, não para executar o pacote. A CI inclui testes JavaScript, build reproduzível, auditoria e jornada de navegador. Muda a superfície de edição, não engine, provider, grants, schema de banco, versões publicadas ou aprovações. Conexões de execução e vínculos de dados são distintos e continuam validados no backend.

Limites explícitos: histórico de desfazer/refazer somente da sessão/revisão; portas limitadas na caixa com alternativa por painel; campos escalares limitados por profundidade/quantidade/precisão; formulário completo separado para estruturas e consultas. Fluxos arbitrários não são convertidos em assistentes lineares.

## Reversão e aceitação

É possível voltar à visão **Canvas** ou **Lista de etapas** sem converter definições. Retirar a entrada React não exige migração de banco. A validação automatizada local inclui testes React, build reproduzível, browsers em 1440/1024/390 e a jornada completa de authoring. A avaliação com cinco participantes técnicos e cinco não técnicos foi preparada, mas não realizada; nenhum ganho de tempo ou usabilidade foi medido ainda. O registro corrente dos testes e pendências fica em `docs/UX_VISUAL_AUTHORING_PLAN.md` e no run de conclusão, não nesta decisão arquitetural.
