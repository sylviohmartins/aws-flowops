# Workspace: implementação e validação

Estado reconciliado em 10 de setembro de 2026: implementação local na branch `codex/code-defined-tours`;
sem promoção, push ou deploy. O [guia do operador](../flowops/streamlit/operator_guide.md)
é a fonte única do passo a passo e também aparece no menu da aplicação.

## Escopo entregue

Atualização local em 15/09/2026: autoria visual em implementação conforme
[plano aprovado](UX_VISUAL_AUTHORING_PLAN.md). Campos recursivos, buffers Visual/JSON,
parâmetros, consulta DynamoDB não destrutiva, seleção de origens, lista/assistente e conexões
por teclado foram integrados. A validação consolidada e os limites ficam no registro
`.agents/runs/visual-authoring-implementation.json`; isso **não declara todas as AC01–AC18 concluídas**.
O padrão de buffer separado da última configuração válida adapta a referência de builder autorizada,
sem importar Next.js, dependências ou infraestrutura adicionais.

| Requisito | Comportamento | Arquivos principais |
| --- | --- | --- |
| Menu | Nomes orientados à tarefa, seleção e foco visíveis, catálogo e guia | `navigation.py`, `integration.py`, `ui.py` |
| Edição visual | Clique na caixa abre edição contextual; teclado/lista continuam disponíveis | `node_editor.py`, `ui.py`, `workspace.py`, `failure_workspace.py` |
| Execução | Grafo lê checkpoints a cada 2 s; linhas distinguem execução, sucesso, aprovação, erro e ramos não percorridos | `canvas.py`, `live_execution.py` |
| DynamoDB → Lambda | Template Query → map → aprovação → Invoke; construtor preserva opções avançadas e exige outra etapa para trocar a operação já configurada; schema separado por tabela | `templates.py`, `resource_picker.py`, `dynamodb_authoring.py`, `demo.py` |
| AWS | 149 operações curadas em 18 serviços; consulta aos modelos do SDK; demais operações exigem allowlist do host | `providers/aws/catalog.py`, `actions.py`, `action_catalog.py` |
| Aprovação | Explicação explícita da simulação; pausa/retomada no demo live; controles indicam quando outra pessoa precisa decidir | `ui.py`, `workspace.py`, `node_editor.py` |
| Exportação | Seleção pelo nó ou lista; JSON/CSV da saída e JSON do checkpoint, inclusive falhas | `results.py` |
| Tour | Código e ativos do tour removidos; documentação estática incluída no pacote | `operator_guide.md`, `pyproject.toml`, `README.md` |

Os caminhos de UI da tabela ficam sob `flowops/streamlit/`. Os templates ficam sob `flowops/`.
O catálogo amplo não significa que o backend DEMO execute todas essas operações; a interface
informa essa diferença. Operações AWS novas não recebem retries automáticos de mutação.

## Melhorias de React Flow: seleção e organização do grafo

Revisão em 13/09/2026, após a [padronização da interface](INTERFACE_DESIGN.md):

| Melhoria identificada | Situação e decisão |
| --- | --- |
| Edição dentro das caixas, com controles próprios | Pendente. Hoje o clique abre um diálogo contextual, não um formulário embutido na caixa. Exige evoluir/substituir o componente de canvas e preservar o contrato Python. |
| Mapeamento visual de saída → entrada por portas tipadas | Pendente. O editor já possui campos, estruturas de dados e mapeamento por expressões; falta a conexão visual entre campos. Depende de portas e validação próprias. |
| Organização automática com reversão | Implementada como melhoria imediata de melhor custo/risco: melhora a leitura sem migrar o editor nem alterar execução. |
| Desfazer/refazer completo | Pendente. A reversão entregue é somente da última organização, não de exclusão, conexão ou edição de configurações. |

O [guia de layout do React Flow](https://reactflow.dev/learn/layouting/layouting) explica que o
posicionamento é separado do renderizador. O adaptador instalado, `streamlit-flow-component` 1.6.1,
oferece layouts, mas não um reconhecimento explícito de conclusão do layout assíncrono.
Para este incremento, `graph_layout.py` usa ordenação topológica determinística no Python:
camadas da esquerda para a direita, espaçamento fixo e ordenação pelo centro dos predecessores.
**Não é uma integração ELK/Dagre** nem um algoritmo de roteamento de conexões; não há dependências novas.

`Organizar fluxo` modifica apenas posições no rascunho da sessão. IDs, ordem das definições,
configurações, ramos, tentativas, compensações e conexões não são modificados. Campos incompletos
e componentes desconectados são aceitos; ciclos, IDs repetidos, destinos inexistentes e tamanhos
acima de 200 etapas/1.000 conexões são rejeitados sem alteração parcial.

O desfazer guarda somente posições e uma assinatura da geometria/estrutura/revisão. Edições nos
campos são preservadas; mover, inserir/remover caixas, alterar conexões ou salvar outra revisão
invalida a reversão. Os botões revalidam `runbook.edit`. Salvar continua explícito e versões
publicadas permanecem imutáveis. O mínimo de zoom do canvas passou de 0,5 para 0,1 para permitir
enquadrar fluxos mais compridos; grafos muito grandes ainda exigem navegação e ajustes manuais.

Passo a passo: [Organize a área do fluxo](../flowops/streamlit/operator_guide.md#organize-a-área-do-fluxo).
Regressões: `tests/test_graph_layout.py`, `tests/test_canvas_sync.py` e o trecho de organização,
desfazer, arraste e salvamento em `python -m scripts.browser_workspace`.
Evidências desta rodada são separadas das anteriores em `browser-artifacts/organization-*.log`
e `.agents/runs/graph-organization.json`. Esta entrega não autoriza promoção, push ou deploy.

Impactos deste incremento: nenhuma chamada AWS real, migração, mudança de RBAC/aprovações ou
instalação adicional. Para reverter, retirar somente `graph_layout.py` e os trechos relacionados
de UI/canvas/documentação/testes; posições já salvas continuam compatíveis com o schema existente.
Preservar os outros arquivos alterados e todos os bancos. Limites de espaço fixo, histórico de
desfazer de um passo e as melhorias pendentes acima são deliberados.

Validação final do incremento: **262 testes passaram, um falhou, cinco opt-in foram ignorados;
cobertura 96,29%**. A falha é `test_agent_repository_contract_is_self_consistent`: o validador
de instruções rejeita corretamente o registro de intermitência ainda aberto no task run.
Uma rodada anterior tinha 263 testes aprovados, antes de registrar explicitamente esse risco;
isso não substitui o resultado final. Nenhum teste ou gate foi desabilitado.
Ruff, mypy (58 módulos), Bandit, build e a jornada Chromium anterior passaram.
A última jornada completa do workspace, **sem instrumentação**, também passou, com organização/desfazer/arraste,
aprovação manual, exportações e **33 medições responsivas sem falhas**. Os screenshots do
canvas organizado e das páginas em 1.024/390 px foram inspecionados.

Limitações de validação: `pip-audit` continua bloqueado pela cadeia de certificados TLS local;
a CI da árvore exata não foi executada, e Docker/PostgreSQL/setup opt-in não foram repetidos
neste incremento de apresentação. Dois ensaios anteriores perderam uma interação de navegação
ou seleção de diagnóstico durante atualizações ao vivo; a repetição instrumentada passou sem
alteração do mecanismo. A causa da intermitência continua **não confirmada**, registrada para
investigação antes de promoção, sem alegação de correção. A instrumentação temporária foi
retirada; o registro de eventos de widgets da fixture ficou em `workspace/widget-trace.json`.
O aviso de fluxo já organizado agora permanece entre reruns e tem regressão em AppTest;
isso é distinto da intermitência de navegação/seleção ainda não confirmada.
Nenhuma dessas pendências autoriza reduzir gates ou reiniciar a prévia descartando rascunhos.

## Evidências locais

- Python: 229 testes e 196 subtestes passaram; cobertura de linhas/ramos **96,14%**, gate de 96% preservado.
- A suíte acima deixou cinco testes opt-in sem executar. PostgreSQL e laboratório Docker foram
  executados separadamente na rodada abaixo; o smoke test opt-in de instalação/setup continua não executado.
- Ruff, mypy (54 módulos), Bandit e validação de instruções do repositório passaram.
- Wheel e sdist gerados em `browser-artifacts/workspace/dist`; o wheel contém o guia e não contém ativos de tour.
- `scripts/browser_acceptance.py`: criar/configurar, selecionar, arrastar, conectar/desconectar, mapear, salvar, publicar, executar e repetir no Chromium.
- `scripts/browser_workspace.py` **PASS**: banco temporário, clique nas caixas, edição/fechamento por teclado, construtor DynamoDB, aprovação manual, linha animada, resultados, falha de consulta em uma segunda versão e exportação do diagnóstico correto. Viewport móvel verificado após recolher o menu. O resultado corrente fica em `browser-artifacts/workspace/result.json`.
- Dados, logs, downloads e screenshots de validação ficam em `browser-artifacts/workspace/` (ignorados pelo Git).
- Testes AppTest agora encerram seus runtimes antes de limpar SQLite, evitando disputa de arquivos no Windows.

### Integrações Docker executadas em 10/09/2026

- Docker Desktop respondeu com Engine 28.1.1 e contexto `desktop-linux`.
- Laboratório isolado pelo projeto/rede `flowops-workspace-tests-20260910`, com Moto 5.2.3
  em `127.0.0.1:5000` e PostgreSQL 16 em `127.0.0.1:55432`. Nenhum container/volume anterior foi substituído.
- `tests/test_postgres.py` e `tests/test_pending_queue.py`: **5 testes passaram em 8,07 s**.
  O banco `integration_checks` é exclusivo dessa validação, separado do banco do laboratório.
- `FLOWOPS_TEST_LOCAL_AWS=1` com `tests/test_local_aws.py`: **8 testes e 14 subtestes passaram em 41,66 s**.
  A jornada verificou efeitos em DynamoDB/SQS/SNS/S3 e Lambda executada em contêiner, além de lotes,
  DLQ, rejeição de aprovação, reexecução sem duplicação, conflito condicional, compensação de falha
  real da função e preservação dos dados ao repetir o seed. Esses números incluem testes de
  fronteira já presentes na suíte geral; não devem ser somados como testes únicos de cobertura.
- `python -m scripts.browser_local_lab`: **PASS** no Chromium, com descoberta, runbook salvo,
  parâmetros, aprovação, Lambda Docker, atualização de `PAY-1004` para `PROCESSED` e reexecução
  pelo ramo `already_done`. Resultado: `browser-artifacts/local-result.json`.
- O download pelo GHCR falhou duas vezes com EOF. O Docker Hub do mesmo mantenedor entregou
  a imagem, e os manifests `linux/amd64` de ambos os registros foram verificados como idênticos:
  `sha256:1ed98f3049a8b89083dabb5273b1db8ce3a0352dc9f2c17600eee872106c198d`.
  A imagem foi etiquetada localmente com o nome GHCR esperado, sem mudar `compose.local.yml`,
  desabilitar TLS ou substituir a execução da Lambda por um sucesso fictício.
- Logs e relatórios JUnit: `browser-artifacts/workspace/integration/`.
- Ao terminar, somente os dois containers do projeto de teste foram parados; o volume
  PostgreSQL e as evidências foram preservados. A prévia DEMO em `8510` permaneceu ativa.
  Moto mantém fixtures em memória: elas serão recriadas no próximo seed, não recuperadas do volume PostgreSQL.

## Validação ainda bloqueada

O bloqueio anterior do Docker foi resolvido e as integrações acima passaram.
`pip-audit` foi tentado anteriormente no ambiente global e no virtualenv: houve falha
de certificado e, ao usar as raízes do sistema pelo adaptador truststore já instalado no pip,
reset de conexão. A verificação TLS não foi desabilitada. Isso não é um resultado de auditoria limpo.
A CI GitHub da árvore exata ainda não foi executada. Esses controles permanecem obrigatórios
antes de promoção; nenhuma alteração enfraquece os gates existentes.
O completion gate desta rodada retornou `FAIL` exclusivamente por esses dois checks pendentes;
isso não invalida os resultados aprovados das integrações nem autoriza promoção.

## Impacto, riscos e reversão

- **AWS:** nenhuma chamada a uma conta real. Ações novas mantêm classificação, validação botocore,
  autorização, limite de escopo, simulação e não-idempotência. Metadados/modelos não substituem testes AWS reais autorizados.
- **Persistência:** nenhuma migração ou mudança de schema. Versões publicadas e snapshots anteriores permanecem imutáveis.
  A integração aplicou o schema existente somente em bancos novos do PostgreSQL de teste.
- **Segurança:** sem novas dependências, credenciais ou permissões de workflow; serviços genéricos sensíveis continuam bloqueados.
  CSV neutraliza strings interpretáveis como fórmulas. Exportações usam saídas limitadas/sanitizadas pelo engine.
- **Deploy:** nenhum. Prévia DEMO local em `127.0.0.1:8510`, usando somente `browser-artifacts/workspace/preview.db`.
  O banco `flowops.db` anterior não foi modificado por essa prévia.
- **Rollback:** encerrar a prévia e restaurar o pacote/código anterior ao promover esta mudança, preservando os bancos.
  Runbooks que usem ações/templates novos devem permanecer inativos em uma versão antiga que não os conheça.
- **Limites:** polling de 2 s pode não exibir estados intermediários muito rápidos; o estado final permanece auditável.
  Aprovação na simulação é intencionalmente simulada. O demo usa recursos fictícios e possui cobertura menor que o catálogo.

## Retomada

1. Preservar as evidências locais aprovadas e conferir se a árvore não recebeu novas alterações.
2. Preservar as evidências das integrações Docker aprovadas; repetir em laboratório isolado se a árvore mudar.
3. Reexecutar `pip-audit` com conectividade disponível.
4. Validar a árvore exata na CI antes de decidir promoção.
5. Conferir `.agents/runs/workspace-usability.json` e executar o completion gate final.

O rastreamento tem sete requisitos funcionais concluídos e um requisito de validação bloqueado.
A skill `task-completion` exige manter esse bloqueio explícito: os checks externos pendentes
impedem um resultado final `PASS` e a liberação para promoção.
