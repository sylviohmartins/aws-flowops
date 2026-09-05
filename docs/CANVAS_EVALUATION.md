# Avaliação do canvas — 2026-09-05

Fontes primárias: [streamlit-flow](https://github.com/dkapur17/streamlit-flow),
[alternativa streamlit-react-flow](https://github.com/rajagurunath/streamlit-react-flow),
[componentes Streamlit](https://docs.streamlit.io/develop/api-reference/custom-components).

Escolha: `streamlit-flow-component==1.6.1`, licença MIT, distribuição PyPI com frontend
empacotado. API inspecionada no código original: nós, edges, clique, movimento, controles,
minimap, menus e sincronização de estado. A alternativa possui superfície menor e não
traz vantagem funcional para este contrato. Não há motivo comprovado para manter um
frontend independente ou criar outro componente neste projeto.

O README de 1.6.1 alerta sobre memória e loops se o estado for reinicializado a cada rerun.
O adaptador conserva `StreamlitFlowState` e só troca a instância em mudanças externas.
O pacote fica atrás de `workflow_canvas`; ações, políticas, identidade e execução nunca
residem no canvas. Conteúdo de nós é escapado; a edição livre de Markdown fica desligada.
Retornos do navegador podem alterar posições, seleção e conexões, nunca configurações AWS.

A versão foi fixada por mudanças incompatíveis no upstream. A revisão não equivale a
auditoria completa do bundle JavaScript. O fluxo visual precisa de teste de navegador;
AppTest cobre os formulários, mas não emula as interações do iframe React.
