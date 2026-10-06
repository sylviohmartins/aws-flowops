# Padrão visual do AWS FlowOps

Aplicação operacional em pt-BR: clareza, densidade moderada e controles de segurança visíveis.
Não é uma landing page. Preserve o tema claro/escuro escolhido pelo usuário e a ordem de leitura.

## Fonte de verdade

Os valores e seletores estão em [workspace.css](flowops/streamlit/workspace.css).
O contrato e a validação estão em [Design da interface](docs/INTERFACE_DESIGN.md).

- Use os contêineres `flowops-workspace`, `flowops-navigation` e `flowops-node-editor`.
- Use a grade compartilhada para campos e ações relacionados; não misture divisões de colunas
  diferentes entre linhas de um mesmo conjunto de filtros.
- Espaçamentos: 8 px dentro dos controles, 16 px entre elementos relacionados, 24 px para
  separações maiores quando necessárias. Não adicione margens negativas para acertar uma tela.
- Títulos de página devem ter o mesmo nível visual; títulos de seção são subordinados.
- Botões de uma barra de ações ocupam a largura da célula e têm alvo mínimo de 44 px.
- Em telas estreitas, quebre a grade sem reordenar elementos no DOM. Nomes extensos,
  identificadores AWS e conteúdo em pt-BR não devem empurrar a página horizontalmente.
- JSON, tabelas e canvas podem ter rolagem interna. Não esconda conteúdo ou confirmações para
  eliminar transbordamentos. Não remova foco, rótulos, alertas ou ações por razões estéticas.
- Não estilize o host, classes geradas pelo framework ou controles internos do React Flow
  com seletores globais. Revise os testes quando a versão do Streamlit mudar.

Referência de método: [Impeccable — layout](https://impeccable.style/docs/layout/) e
[polish](https://impeccable.style/docs/polish/). Orientações adaptadas; a skill e seus hooks não
foram instalados nem executados neste projeto.
