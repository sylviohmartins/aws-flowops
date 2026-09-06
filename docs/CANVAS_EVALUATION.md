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
O adaptador conserva `StreamlitFlowState` e só troca a instância em mudanças externas. Essas
mudanças também avançam uma revisão na chave do widget: o wrapper 1.6.1 pode devolver o valor
anterior enquanto recebe novos props, descartando um nó recém-inserido se a identidade do
widget não mudar. Movimentos/seleções recebidos do navegador conservam a revisão e o iframe.
O pacote fica atrás de `workflow_canvas`; ações, políticas, identidade e execução nunca
residem no canvas. Conteúdo de nós é escapado; a edição livre de Markdown fica desligada.
Retornos do navegador podem alterar posições, seleção e conexões, nunca configurações AWS.

A versão foi fixada por mudanças incompatíveis no upstream. A revisão não equivale a
auditoria completa do bundle JavaScript. Conexões recém-criadas no browser também precisam
ser normalizadas: o componente usa `deletable=False` quando essa propriedade não é enviada.
O editor persiste a alteração em sua working copy e renderiza novamente as arestas com as
permissões adequadas, sem habilitar edição em modo readonly. Use o menu de contexto da aresta
para editar seu branch ou desconectá-la.

A remoção de arestas mantém a instância do canvas: somente conexões novas precisam dessa
normalização. O resultado de Validate permanece visível em reruns sem mudanças e é invalidado
quando a definição muda. Publicação e execução continuam validando o grafo independentemente
desse feedback de UI.

O percurso Chromium passou integralmente no
[Quality 34060950606](https://github.com/sylviohmartins/aws-flowops/actions/runs/34060950606),
incluindo inserção, seleção, movimento, conexão/desconexão e persistência. O teste aguarda o
término dos reruns usando o estado do aplicativo exposto pelo Streamlit. AppTest cobre os
formulários; `test_canvas_sync.py` cobre os contratos de estado antigo e de novas arestas;
o navegador exercita o iframe real. Evidências e limites estão em [ACCEPTANCE.md](ACCEPTANCE.md).
