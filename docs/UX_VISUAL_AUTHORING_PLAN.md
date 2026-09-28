# Autoria visual do AWS FlowOps Studio — plano em execução

Plano original: 14/09/2026. Atualização de validação: 28/09/2026. Estado: **implementação automatizada e CI remota da árvore candidata validadas; avaliação humana permanece pendente**.

O usuário autorizou concluir todas as ondas em 16/09 e reforçou a reformulação visual próxima ao `starter-react-lib`: biblioteca/etapas, canvas central, inspetor contextual e barra compacta. O incremento em curso inclui parâmetros atômicos, criação por objetivo, revisão, histórico de edição e componente React delimitado. O registro corrente é `.agents/runs/visual-authoring-completion.json`; registros anteriores não certificam todos os critérios AC01–AC18. A avaliação humana tem participantes confirmados, mas ainda não há resultados; roteiro em [Avaliação com participantes](UX_AUTHORING_USER_STUDY.md).

As seções de diagnóstico abaixo registram o estado observado em 14/09 e as decisões do plano original. São referências históricas, não uma declaração de que os defeitos descritos continuam presentes nem de que todas as entregas foram concluídas.

## Estado validado em 27/09/2026

A árvore corrente em `codex/code-defined-tours` foi validada localmente sem conta AWS real. O gate consolidado com PostgreSQL, Moto/Docker e setup smoke habilitados terminou com **358 testes + 197 subtests aprovados, zero falhas, zero skips e 96,44% de cobertura**. Depois desse gate foram corrigidas duas fragilidades de automação: o setup passou a reutilizar o runtime Lambda local quando já existe, e os browsers legados foram alinhados à UI visual atual. Os quatro fluxos de navegador previstos pelo workflow local têm evidência `PASS`: acceptance geral, laboratório local, workspace completo e authoring-completion.

Também estão verdes Ruff/formatação, mypy, Bandit, os três testes do editor React, build/reprodutibilidade do frontend, `npm audit`, `pip-audit` isolado e `python -m build`. Nenhuma dessas validações executou mutação em uma conta AWS real. A **Resource Discovery v2** usa caminhos somente leitura, explícitos e limitados; o laboratório usa Moto.

A árvore candidata foi publicada na branch `codex/code-defined-tours`. Para o SHA exato `f73eaee9acc5b12a1e4955305ddeb16b242c08f1`, o GitHub Actions executou o workflow `Quality` por `push` (run 36434488494) e por `pull_request` (run 36434498525); ambos terminaram em `success`. O estudo com cinco participantes técnicos e cinco não técnicos continua sem resultados reais. Nenhum resultado humano é inferido de teste automatizado.


## 1. Recomendação executiva

Priorizar a configuração de uma tarefa completa sem JSON, não a substituição do canvas. Entregar **consultar DynamoDB → selecionar/transformar dados → aprovar → invocar Lambda → investigar/exportar** com formulários contextuais, objetos/listas editáveis e escolha visual da origem de cada valor.

Manter o modelo `Runbook` e o motor atuais. Usar **Configurar visualmente** como padrão, **Ver código** como consulta e **Editar código** como ação avançada explícita. JSON será o formato do editor técnico; YAML e JSON continuam disponíveis na importação/exportação existente.

Aproveitar o `starter-react-lib/apps/builder` do usuário: organização do espaço de trabalho, contrato declarativo dos campos, validação contextual e tratamento de prévia válida/código pendente. O usuário declarou autoria e autorizou reutilização em 14/09/2026. O marcador `UNLICENSED` dos manifests não é tratado como impedimento a esse reúso autorizado. Dependências de terceiros conservam seus próprios termos; não se presume transferência de direitos sobre elas.

**Primeiro recorte:** evoluir os componentes Streamlit existentes e os adaptadores puros de autoria. Não exige Next.js, novo serviço ou outro motor. Extração de componentes React do builder fica como alternativa delimitada para a superfície do editor caso a experiência necessária não seja atendida; não como migração integral do produto.

Hipótese a validar: o maior obstáculo atual é traduzir intenção em configuração e referências de dados; trocar o renderizador do grafo, sozinho, não elimina esse obstáculo.

## 2. Escopo, método e limites da evidência

Foram lidos o contrato do repositório, README, arquitetura, segurança, operações, regras de contexto, skills de descoberta/planejamento/documentação/conclusão, código das jornadas e testes relacionados. Também foram examinadas as instruções locais e o código dos builders fornecidos. A análise das referências não altera suas instruções, pacotes ou código.

Inspeção de navegador em sessões separadas no endereço `http://127.0.0.1:8510/`, com o contexto visível **Desenvolvimento · 000000000000 · sa-east-1 · Demonstração**. A sessão do usuário não foi recarregada nem teve seu formulário submetido. Não foram acionados salvar, publicar, executar, aprovar, descobrir recursos ou consultar AWS. As sessões temporárias de inspeção não são rascunhos persistidos.

Foram visitadas as dez páginas do menu e aberto o diálogo **Preparar evento**. O procedimento disponível estava na revisão 1, sem versão publicada; o histórico mostrava zero execuções. Portanto, esta inspeção confirma controles/estados vazios e os pontos de fricção, **não certifica execução e aprovação de ponta a ponta nesta rodada**. Para essas partes, foram rastreados código, testes e evidências anteriores, identificadas como anteriores.

### Cobertura observada

| Jornada/página | Observação atual | Consequência para o plano |
| --- | --- | --- |
| Visão geral | Um procedimento, zero execuções, métricas e tabelas vazias | Estado vazio precisa levar à próxima tarefa, não apenas informar ausência |
| Procedimentos | Modelo dentro de seção recolhida; revisão/publicações; importação YAML/JSON e exportação | Destacar criação por objetivo, revisão e continuidade no editor |
| Editor visual | Canvas, clique para diálogo, seletor alternativo de etapa, organizar/desfazer, validar/salvar/publicar | Reaproveitar; o problema não é ausência total de edição visual |
| Configurar lógica | Diálogo mostra JSON geral e, abaixo, `items` e `template` como JSON novamente | Unificar a edição; não basta dividir o JSON em várias áreas de texto |
| Conectar | Orientação para arrastar alças e usar menu de contexto para ramos | Adicionar conexão por seleção/teclado, mantendo identidade dos ramos |
| Executar | “Nenhum procedimento disponível”, pois não há publicação selecionável | Explicar o pré-requisito e oferecer retorno à revisão/publicação autorizada |
| Execuções | Filtros e estado sem registros | Preservar filtros; ligar resultado/erro à etapa e versão corretas |
| Aprovações | Nenhuma pendência; ajuda diferencia simulação e execução efetiva demo | Melhorar contexto e acesso à pendência; não concluir que o motor esteja quebrado |
| Auditoria | Filtro de evento, tabela e detalhes técnicos | Resumo legível com aprofundamento técnico opcional |
| Recursos AWS | Serviço e botão de busca explícita, somente leitura | Manter distinção entre inventário real e catálogo de operações |
| Catálogo de ações | 150 ações habilitadas e 431 serviços conhecidos pelo SDK nesta instalação; risco, disponibilidade e schemas | Conhecer o schema não significa poder executar; explicar campos de forma útil |
| Guia | Passos sobre Query, transformação, aprovação e exportação; sem tour | Integrar links contextuais ao editor; manter documentação, não overlays |

No catálogo, a ajuda genérica explica tipos, mas não a intenção operacional de vários campos. A árvore de saída também expôs descrições do SDK em inglês dentro de `additionalProperties`, fora da seção técnica recolhida. É uma lacuna observada de localização/explicação, não indicação para traduzir nomes de API ou valores de enum persistidos.

### Evidências de código usadas no diagnóstico

As referências abaixo apontam para a árvore local inspecionada; números de linha são pontos de entrada e podem mudar durante a implementação.

| ID | Evidência |
| --- | --- |
| E01 | [typed_inputs.py](C:/Development/projects/personal/aws-flowops/flowops/streamlit/typed_inputs.py:13): campos escalares; objetos/listas caem em área JSON; seção inicialmente recolhida |
| E02 | [node_editor.py](C:/Development/projects/personal/aws-flowops/flowops/streamlit/node_editor.py:38): lógica exige JSON por campo; diálogo chama formulário técnico antes das ferramentas |
| E03 | [ui.py](C:/Development/projects/personal/aws-flowops/flowops/streamlit/ui.py:428): parâmetros definidos em JSON; `_node_form` contém configuração JSON; `_parameter_inputs` também exige JSON para objetos/listas |
| E04 | [resource_picker.py](C:/Development/projects/personal/aws-flowops/flowops/streamlit/resource_picker.py:42): descoberta explícita, Query/GetItem, escolha de índice e chaves; aplicar requisição substitui `node.config` |
| E05 | [query_builder.py](C:/Development/projects/personal/aws-flowops/flowops/providers/aws/query_builder.py:59): construtor literal; chaves S/N, limites, restrições de GetItem e operadores |
| E06 | [workspace.py](C:/Development/projects/personal/aws-flowops/flowops/streamlit/workspace.py:180): mapper separado do formulário; prévia técnica e tipos; retorno antecipado para ações `core.*` |
| E07 | [mapping.py](C:/Development/projects/personal/aws-flowops/flowops/core/mapping.py:1): fontes ancestrais, schemas achatados, destino por nomes separados por pontos; coleções e chaves especiais não são um editor recursivo |
| E08 | [models.py](C:/Development/projects/personal/aws-flowops/flowops/domain/models.py:54), [expressions.py](C:/Development/projects/personal/aws-flowops/flowops/core/expressions.py:1) e [logic.py](C:/Development/projects/personal/aws-flowops/flowops/core/logic.py:1): modelo versionado, DSL de caminhos, transformação pura; sem execução arbitrária de código |
| E09 | [serialization.py](C:/Development/projects/personal/aws-flowops/flowops/core/serialization.py:1): importação/exportação YAML/JSON já existem; importação normal cria nova identidade |
| E10 | [catalog.py](C:/Development/projects/personal/aws-flowops/flowops/providers/aws/catalog.py:182) e [actions.py](C:/Development/projects/personal/aws-flowops/flowops/providers/aws/actions.py:74): schema do SDK limitado em profundidade, controle `_flowops` de paginação, preparação do payload dentro do provedor |
| E11 | [templates.py](C:/Development/projects/personal/aws-flowops/flowops/templates.py:324): modelo Query → map → approval → Lambda já existe e deve ser a base da entrega |
| E12 | [results.py](C:/Development/projects/personal/aws-flowops/flowops/streamlit/results.py:1), [live_execution.py](C:/Development/projects/personal/aws-flowops/flowops/streamlit/live_execution.py:1), [failure_workspace.py](C:/Development/projects/personal/aws-flowops/flowops/streamlit/failure_workspace.py:1): resultados, exportação sanitizada, execução acompanhada e diagnóstico |
| E13 | [pyproject.toml](C:/Development/projects/personal/aws-flowops/pyproject.toml:12) e adaptador instalado `streamlit-flow-component==1.6.1`: interface Python expõe cliques, arestas, layout e zoom, não um registro `nodeTypes` com formulários React arbitrários |
| E14 | [registro do incremento anterior](C:/Development/projects/personal/aws-flowops/.agents/runs/graph-organization.json:1) e [evidência consolidada](C:/Development/projects/personal/aws-flowops/docs/WORKSPACE_USABILITY.md:63): intermitência ainda aberta, auditoria TLS bloqueada e CI da árvore exata não executada |

### Matriz priorizada de oportunidades

Classificação: **ausência** = caminho ainda inexistente; **descoberta** = recurso existe mas é difícil encontrar/usar; **limitação** = contrato/adaptador não cobre o caso; **defeito/risco** = comportamento incorreto observado ou risco de código a confirmar. Esforço P/M/G e prioridade são estimativas de engenharia, não medições com usuários. P0 condiciona a entrega; P1 pertence ao primeiro recorte; P2/P3 são incrementos posteriores.

| Oportunidade e evidência | Classe | Público | Impacto | Esforço | Risco | Prioridade |
| --- | --- | --- | --- | --- | --- | --- |
| Objetos/listas e lógica sem JSON (E01/E02/E06) | Ausência | Todos, sobretudo negócio | Alto | G | Alto: tipos e expressões | P1 |
| Parâmetros visuais na autoria e execução (E03) | Ausência | Autores/operadores | Alto | M | Médio: ausência/default/null | P1 |
| Origem do valor junto ao campo, sem IDs memorizados (E06/E07) | Descoberta + limitação | Todos | Alto | G | Alto: referência e escopo | P1 |
| Reedição do builder Dynamo sem apagar opções avançadas (E04) | Risco de código: atribuição integral confirmada; perda não exercitada no navegador | Desenvolvedores | Alto | M | Alto: mudança silenciosa | P0 |
| Buffer inválido preservado e aplicação única por etapa (E01–E04) | Limitação + fragmentação | Todos | Alto | M/G | Alto: perda de trabalho | P0 |
| Corrigir navegação/seleção intermitente em atualização ao vivo (E14) | Defeito anterior aberto; causa desconhecida | Operadores | Alto | A diagnosticar | Alto | P0 antes de promoção |
| Explicar Query/GetItem/Scan, índice, paginação e custo (E04/E05/E10) | Descoberta + limitação | Autores não especialistas | Alto | M | Alto: escopo AWS | P1 |
| Configuração visual em primeiro plano; código recolhido (diálogo observado, E02) | Descoberta | Todos | Alto | P/M | Baixo se estado compartilhado | P1 |
| Criar por objetivo e checklist com próximos passos (Procedimentos/Executar) | Descoberta | Iniciantes | Alto | M | Baixo | P1 |
| Conectar/editar ramo por teclado e lista de dependências (E07/E13) | Ausência no caminho principal observado | Teclado/negócio | Alto | M | Alto se reordenar execução | P1 |
| Aprovação com intenção, destino e dados de origem (E11/E12) | Descoberta + apresentação incompleta | Aprovadores | Alto | M | Alto: conteúdo aprovado | P1 |
| Navegação agrupada e links entre inventário/catálogo/editor | Descoberta | Todos | Médio | M | Médio: continuidade | P2; links da jornada em P1 |
| Guia, catálogo e auditoria com ajuda localizada e útil | Descoberta + defeito de localização observado | Todos | Médio | M | Baixo | P1 no recorte, P2 restante |
| Cards React customizados, portas de dados, undo/redo geral | Limitação do adaptador + ausência | Autores frequentes | Médio/alto | G | Alto: sincronização | P3 após validar necessidade |

## 3. Referências: mecanismos úteis e limites

Fontes oficiais consultadas em 13–14/09/2026. As recomendações de encaixe são **inferências sobre o FlowOps**, não promessas dos fornecedores. Nenhuma biblioteca, dependência ou serviço foi instalado para esta análise.

| Referência | Mecanismo concreto a aproveitar | Limite / encaixe / dependência |
| --- | --- | --- |
| [AWS Workflow Studio](https://docs.aws.amazon.com/step-functions/latest/dg/workflow-studio.html) | Biblioteca de ações/padrões, canvas e inspetor; modos visuais/técnicos; pausa de renderização com definição inválida | Inspiração de interação. A definição é ASL, não `Runbook`; não implica migrar para Step Functions ou usar a UI oficial como biblioteca |
| [Cloudscape — criação](https://cloudscape.design/patterns/resource-management/create/) | Formulário direto para tarefas menores; wizard para configurações longas/interdependentes; validação por etapa e revisão | Adaptar padrões aos componentes atuais. Seus componentes têm [Apache-2.0](https://raw.githubusercontent.com/cloudscape-design/components/main/LICENSE), mas adoção direta acrescentaria uma camada React e outra base visual |
| [Make — mapeamento](https://help.make.com/mapping) e [tipos](https://help.make.com/item-data-types) | Separar origem/destino e navegar por coleções; controles conforme tipo | Inspiração, não contratação/integração do serviço. No FlowOps, prévia não deve exigir executar módulo real. Não importar semântica de índices, coerções ou funções da ferramenta |
| [JSON Forms](https://jsonforms.io/) | Separar schema de dados, organização visual e dados editados; validação e campos condicionais | [MIT](https://raw.githubusercontent.com/eclipsesource/jsonforms/master/LICENSE). Candidato para componente React futuro; não é plug-in nativo Streamlit e não fornece a semântica Dynamo/map/approval do FlowOps. Schemas locais `any` e recursão limitada exigem adaptação |
| [stepfunctions-generator](https://github.com/cleissonbarbosa/stepfunctions-generator) / [demo verificada](https://cleissonbarbosa.github.io/stepfunctions-generator/) | Grafo/JSON lado a lado, validação e histórico de edições válidas | MIT; aplicação React com Monaco e `asl-viewer`. A própria demo orienta editar transições/detalhes via JSON. Boa referência do espaço de trabalho; não resolve autoria sem código por si só |
| [asl-viewer](https://github.com/cleissonbarbosa/asl-viewer) | Renderização e layout de ASL, eventos de seleção, inspeção | Apache-2.0; biblioteca React centrada em ASL. Não é o motor de execução nem um substituto direto do canvas FlowOps. Maturidade produtiva não foi certificada aqui |
| [Amazon States Language Service](https://github.com/aws/amazon-states-language-service) | Diagnósticos/autocomplete especializados | MIT; valida ASL, não regras FlowOps, RBAC ou referências do nosso motor. Adiar, salvo futuro target ASL aprovado separadamente |
| [React Flow — custom nodes](https://reactflow.dev/learn/customization/custom-nodes) | Nós React próprios para controles contextualizados | A capacidade existe no React Flow, mas o wrapper instalado não a expõe diretamente. Não atribuir a limitação a uma suposta “versão básica” paga/gratuita |

Não é necessário validar todas as afirmações secundárias do anexo para escolher a solução. A data de atualização citada para `asl-viewer` e o trecho CDN do Toolkit não foram usados como prova de maturidade ou base da decisão. Não foi adotado compilador ASL, simulador Step Functions nem novo target de execução.

### Referências locais fornecidas pelo usuário

**`saas-builder-v13`: referência inicial de apresentação.** Na leitura realizada, `PRODUCT.md` descrevia uma entrada visual/documental; `App.tsx` registrava landing/FAQ/roadmap/benchmarks; `WorkflowSection.tsx` continha cinco cartões demonstrativos com avanço por temporizador. No último check, a pasta `C:/Development/projects/personal/aws-flowops/references/saas-builder-v13` já não estava disponível. Esses achados são históricos desta análise, sem links locais ativos; a recomendação de reúso se baseia no `starter-react-lib` atualmente disponível. Não portar animação promocional para representar execução real.

**`starter-react-lib/apps/builder`: referência funcional mais próxima para configuração contextual.** Não é editor de DAG AWS: configura módulos SaaS predefinidos. Há funcionalidades reais e áreas em mock/prévia. A inspeção foi estática; não foram executados instalação, build ou testes do monorepo.

| Parte inspecionada | Aproveitar no FlowOps | Adaptação ou exclusão |
| --- | --- | --- |
| [WorkbenchShell](C:/Development/projects/personal/aws-flowops/references/starter-react-lib/apps/builder/features/workbench/components/layout/workbench-shell.tsx:17) / [WorkbenchMain](C:/Development/projects/personal/aws-flowops/references/starter-react-lib/apps/builder/features/workbench/components/layout/workbench-main.tsx:5) | Navegação separada da superfície de trabalho e do inspetor; dimensionamento por tokens | Adaptar densidade ao pt-BR e acesso por teclado. Não ocultar controles essenciais no mobile sem alternativa |
| [ModuleManifest](C:/Development/projects/personal/aws-flowops/references/starter-react-lib/apps/builder/features/modules/types/module-manifest.type.ts:1) / [ModuleSettingsSection](C:/Development/projects/personal/aws-flowops/references/starter-react-lib/apps/builder/features/workbench/components/properties/sections/module-settings-section.tsx:30) | Metadados de apresentação por tipo, rótulo, ajuda e opções | O manifesto genérico cobre boolean/number/select/string, não objetos/listas recursivos. O caminho genérico de Input envia texto; não copiar coerção para números AWS |
| [WorkbenchProvider](C:/Development/projects/personal/aws-flowops/references/starter-react-lib/apps/builder/features/workbench/providers/workbench.provider.tsx:21) / [mapper de configuração](C:/Development/projects/personal/aws-flowops/references/starter-react-lib/apps/builder/features/export/mappers/map-builder-state-to-project.ts:17) | Transições explícitas e validação derivada do estado | `ProjectConfig` é domínio SaaS. Usar o `Runbook` existente, sem segundo contrato de execução; estado local não equivale a salvamento durável |
| [MailPreviewOutlet](C:/Development/projects/personal/aws-flowops/references/starter-react-lib/apps/builder/features/modules/mail/components/preview/mail-preview-outlet.tsx:30) / [estado do editor](C:/Development/projects/personal/aws-flowops/references/starter-react-lib/apps/builder/features/modules/mail/services/mail-template-editor.service.ts:24) | Exemplo concreto de fonte editável preservada, prévia derivada e fallback para último conteúdo válido | No builder, Preview/Source/HTML é especializado em e-mail. No FlowOps, fazer Configurar/Ver JSON/Editar JSON, com aplicação explícita; não introduzir TSX ou chamadas automáticas de prévia AWS |
| [validação do módulo](C:/Development/projects/personal/aws-flowops/references/starter-react-lib/apps/builder/features/workbench/components/properties/sections/module-validation-section.tsx:7) | Erros associados ao módulo/etapa, severidade e correção contextual | Caminhos precisos para campos e validação backend autoritativa; `any` deve aparecer como “tipo não confirmado” |
| [ExportPanel](C:/Development/projects/personal/aws-flowops/references/starter-react-lib/apps/builder/features/export/components/export-panel.tsx:100) / [testes de configuração](C:/Development/projects/personal/aws-flowops/references/starter-react-lib/apps/builder/features/export/test/project-config.test.ts:1) | Resumo de prontidão, dependências, pendências e testes de contrato | ZIP/GitHub estão explicitamente desabilitados nesse painel. Preservar exportações FlowOps existentes; não substituir por controles de prévia |

### Estratégia de reúso autorizado

1. **Agora, no plano:** adaptar arquitetura de interação e contratos de estado; registrar origem e os limites encontrados.
2. **Primeira implementação, se aprovada:** reproduzir os padrões em componentes Streamlit existentes, com funções puras testáveis. Copiar TSX para Python não é reúso executável; reaproveitar regras e casos de teste onde equivalentes.
3. **Se houver componente React delimitado:** extrair seletivamente layout/inspetor, primitives e estado de editor para um pacote local do FlowOps, com rastreabilidade do arquivo/versão de origem. Auditar a árvore de dependências necessária de `@nicobelle/ui`; não importar todos os módulos/auth/billing/infra, nem depender do registro privado do monorepo sem necessidade.
4. Manter o código de referência intacto. A autorização cobre o uso no FlowOps, não implica publicar seus pacotes ou redistribuir credenciais. Nenhuma chave ou fluxo de integrações do builder é necessário à autoria AWS.

## 4. Experiência proposta

### Navegação e descoberta

Organizar por intenção sem remover capacidades: **Criar e editar** (Procedimentos/Editor), **Operar** (Executar/Execuções/Aprovações), **Consultar** (Recursos AWS/Catálogo/Auditoria/Guia). A visão geral continua sendo entrada e resumo. Preservar IDs internos das páginas e usar links contextuais com procedimento, etapa e revisão selecionados.

Recursos AWS responde “o que existe na conta/região?”. Catálogo responde “o que esta ação faz e o que posso configurar?”. Não são duplicados; o primeiro pode acessar AWS mediante ação explícita, o segundo consulta metadados locais. Dentro do editor, ambos devem convergir no seletor da etapa, evitando obrigar a navegar pelo menu para cada campo.

Estados de prontidão separados: **em edição**, **campos pendentes**, **válido**, **rascunho salvo**, **versão publicada**. Não usar “salvo” para texto mantido apenas em memória. Publicar e executar continuam ações distintas, com suas permissões.

### Controles de configuração

| Tipo/caso | Controle padrão | Contrato de comportamento |
| --- | --- | --- |
| Texto | Campo curto ou área multilinha conforme finalidade | Sem aspas JSON; exemplo separado do valor; nunca inventar recurso real |
| Número/integer | Campo numérico com unidade/faixa | Preservar 0, negativos permitidos e precisão; erro em vez de coerção silenciosa |
| Booleano | Escolha Sim/Não; presença configurável para opcionais | Omitido não vira `false`; obrigatório não ganha valor acidental |
| Enum | Seleção com rótulo pt-BR | Persistir valor original do contrato AWS |
| Objeto | Grupo de propriedades, “Adicionar propriedade”, nome/tipo/origem/valor | Chaves duplicadas bloqueadas; nomes técnicos persistidos; exclusão explícita |
| Lista | Linhas/itens expansíveis com adicionar/remover/mover | Identidade de UI estável independente do índice; preservar ordem e tipos |
| Estrutura aninhada | Mesmo componente recursivo, com caminho e recolhimento | Limite visual explícito; preservar subárvore que exceder capacidade, não truncar configuração |
| Opcionais/nulos | “Não enviar”, “Definir valor” e “Nulo” somente quando aceito | Ausente, null, vazio, 0 e false são estados diferentes |
| Recurso AWS | Buscar + conta/região/ambiente + seleção; alternativa manual visual | Entrada manual não exige JSON nem contorna autorização/validação; busca só por comando explícito |
| Condicional | Exibir quando aplicável com explicação | Ao desativar, informar se campo será omitido; preservar valor no buffer até decisão |

Ajuda por campo deve responder **o que**, **como**, **por quê** e, quando relevante, consequência/custo. Exemplo: “Chave de partição: selecione o identificador que delimita a consulta. Use um parâmetro para reutilizar este procedimento com outro pagamento. Query exige igualdade nesta chave.”

### Origem do valor: um controle comum

Cada campo oferece **Fixo · Parâmetro · Contexto · Resultado anterior · Expressão avançada**. Na transformação de uma lista aparece também **Item atual**, apenas dentro do escopo que o motor aceita.

Em “Resultado anterior”, árvore por nome da etapa → coleção/objeto → campo; mostrar tipo declarado, disponibilidade e prévia de exemplo. A interface gera o caminho técnico. O usuário não precisa digitar `nodes.query.output.Items` nem lembrar `prepare_event`.

“Mapear toda a lista” e “Escolher um item” são decisões diferentes. Não selecionar o primeiro elemento automaticamente. Fontes de ramos que talvez não tenham executado precisam de aviso/validação de disponibilidade, mesmo quando são ancestrais no grafo. Schemas desconhecidos não recebem selo de compatibilidade garantida.

Separar **referência** de **transformação**:

- Referência usa um dado como está; selecionar uma coluna não executa filtro nem converte tipos.
- “Selecionar/renomear campos de cada item” produz `core.map` com template visual.
- “Filtrar lista” produz `core.filter` com campo, operador e valor; neste primeiro recorte, uma condição suportada. Grupos AND/OR arbitrários não são fingidos como existentes.
- “Condição” produz comparação e conexões Verdadeiro/Falso visíveis. Operadores limitados aos já existentes e compatíveis com os tipos.
- “Montar evento” produz objeto/lista no `Payload`; não exige uma ação AWS extra.
- Conversões numéricas, cálculos e manipulação de datas não são parte implícita de `map`. São extensões futuras explícitas; a DSL atual não aceita funções arbitrárias.

Mostrar dados DynamoDB em apresentação legível, mas gerar referências ao formato real (`S`, `N`, `M`, `L` etc.). Um atributo DynamoDB `N` transporta texto numérico; não prometer que renomeá-lo o transforma em JSON number. O primeiro cenário usa identificadores/status de texto; demais tipos têm validação e limites sinalizados.

### Visual/Código e prevenção de perda

O único modelo persistido de execução é `Runbook`. O buffer do formulário/código é estado de autoria, não outro modelo de execução. Trocar a visão não salva, publica ou executa nada.

1. Abrir etapa carrega uma cópia de edição e sua revisão base. Botão **Aplicar à etapa** valida e atualiza somente o rascunho de sessão.
2. **Ver código** mostra JSON derivado do rascunho aplicado, somente leitura. **Editar código** cria buffer separado com aviso de alterações pendentes.
3. JSON válido pode ser pré-visualizado, mas só **Aplicar código** o transfere à etapa. Não usar importação normal de procedimento para esse caso: ela cria nova identidade.
4. JSON inválido permanece no buffer com erro/caminho/linha quando disponível. A prévia mostra a última versão válida, claramente identificada; não simula que está sincronizada.
5. Ao trocar de modo/etapa, conservar buffers pendentes. Se houver risco de conflito, oferecer Aplicar, Continuar editando ou Descartar explicitamente. Não reinicializar conteúdo por alteração de chave de widget/hash.
6. Propriedades válidas não suportadas pelo visual são preservadas e identificadas. Alteração visual faz patch somente nos campos assumidos pelo controle. O builder de Query não pode substituir todo `config` e perder `_flowops`, projeções ou expressões existentes.
7. Se a configuração técnica não puder ser reconhecida com fidelidade, o trecho fica “Configuração avançada preservada”; o visual não a reescreve. Não existe promessa de converter qualquer código arbitrário em controles.
8. Campos extras proibidos no nível `Runbook`/`Node`, versões desconhecidas e ações não disponíveis produzem diagnóstico; não são descartados para tornar o documento “válido”. Preservar o texto importado enquanto o usuário corrige.
9. Salvar usa revisão otimista existente; conflito mantém o trabalho local e oferece comparação/recarregamento decidido pelo usuário, nunca sobrescrita automática. Publicações e snapshots históricos não são editados.
10. JSON é o editor técnico inicial. YAML permanece intercâmbio existente; não criar dois editores simultâneos nem prometer round-trip de comentários YAML. Comparação é semântica de dados, não igualdade de formatação.

Limite do contrato atual: `Parameter.default` usa `None` como padrão; não suporta, por si só, uma nova distinção persistida entre “default ausente” e “default explicitamente null”. A UI não inventará essa semântica. A distinção exigida em payloads/configurações deve ser preservada; eventual expansão do contrato de parâmetros exige decisão e testes próprios.

### Alternativas ao canvas

| Visão | Uso recomendado | Preservação de lógica |
| --- | --- | --- |
| Canvas + configuração contextual | Fluxos ramificados, inspeção de dependências e execução | Nó selecionado abre o mesmo editor; não duplicar formulário técnico e visual concorrentes |
| Etapas em lista estruturada | Teclado, telas menores e revisão rápida | Mostrar predecessores, ramos e junções. Não sugerir que a ordem da lista define execução; reordenação semântica exige editar conexões |
| Assistente por objetivo | Primeira criação da jornada DynamoDB/Lambda | Assistente real de autoria, com voltar/avançar/revisão, operando sobre o mesmo rascunho |
| Modelos por objetivo | Trabalho recorrente e público de negócio | Metadados explicam resultado, permissões e riscos; usuário escolhe recursos, não recebe produção como default |

Primeira entrega: canvas existente + navegação por etapas com botões + assistente do modelo de referência. Assistente não tenta converter qualquer DAG em sequência. Se o fluxo ganhar topologia fora do modelo, explicar o limite e continuar no canvas/lista preservando os dados. Não remover branches ou aprovação para manter o wizard linear. Nenhum tour será reintroduzido.

## 5. Esboços de telas e jornada obrigatória

Esboços conceituais, não screenshots de funcionalidades implementadas. O inspetor pode ocupar a lateral em telas amplas ou o diálogo/página contextual existente em telas menores; a primeira implementação não depende de um novo frontend.

```text
Procedimento: Reprocessar pagamentos         Demonstração | Rascunho não salvo
[Fluxo] [Etapas] [Revisão]                          [Salvar rascunho]
--------------------------------------------------------------------------
Adicionar etapa     Fluxo / dependências             Configurar etapa
Consultar AWS       Início → Consultar → Preparar    [Visual] [Ver código]
Transformar         → Aprovar → Enviar → Fim         Tabela: [payments    v]
Condição                                             [Buscar recursos]
Aprovação           [Organizar]                      Chave: paymentId
                                                     Origem: [Parâmetro v]
                                                     Valor:  [Pagamento v]
                                                     [Aplicar à etapa]
```

```text
Preparar evento — Para cada pagamento
Origem da lista: [Consultar pagamentos > Itens v]  [Ver exemplo fictício]
Campo de destino     Tipo       Origem             Valor / campo
payment_id           Texto     Item atual         Identificador
status               Texto     Item atual         Status
 [+ Campo]     [Prévia tabular]     [Ver estrutura técnica]

Evento para a Lambda
source               Texto     Fixo               flowops
payments             Lista     Resultado anterior Preparar evento > Itens
contexto              Objeto    Propriedades        [Expandir]
  ambiente           Texto     Contexto           Ambiente
  etiquetas          Lista     Itens fixos        [operacional] [+ Item]
```

```text
Revisão do procedimento
Consulta: payments · chave informada · página limitada
Transformação: payment_id e status; nenhum dado convertido implicitamente
Destino: payment-processor · aguardar resposta
Aprovação: antes do envio · política de autorização do ambiente
Pendências: [Ir ao campo]      Rascunho: salvo na revisão N
[Voltar a editar]  [Validar]  [Publicar versão — se autorizado]

Após publicar: [Simular]    Em demonstração: nenhuma conta AWS real
Execução: Consulta ✓ → Preparação ✓ → Aprovação simulada → Lambda simulada
[Entrada] [Saída] [Diagnóstico]              [Exportar JSON] [Exportar CSV]
```

### Jornada detalhada sem digitar JSON ou expressões

| Passo | Ação do usuário / resposta da interface | Contrato e estado |
| --- | --- | --- |
| 1. Objetivo | Escolher “Consultar pagamentos e enviar para Lambda”; ler resumo, ambientes e requisitos | Derivar do modelo existente; IDs técnicos gerados; dados fictícios explicitamente identificados |
| 2. Recurso | Confirmar contexto; buscar tabela e estrutura por botões; selecionar índice quando aplicável | Nenhuma busca ao abrir. Sem permissão: mensagem específica e alternativa de nome manual sem JSON; isso não concede leitura/execução |
| 3. Consulta | Selecionar partição, origem e valor; definir condição de ordenação e limites | Operadores compatíveis com a estrutura. Em GSI não oferecer leitura fortemente consistente. Limites de avaliação/páginas/volume separados |
| 4. Tipo de leitura | Comparar “Item pela chave (GetItem)”, “Itens pela partição (Query)” e “Varredura (Scan)” | Query não vira Scan para contornar uma chave ausente. Scan fica fora do assistente inicial e exige escolha operacional explícita |
| 5. Parâmetros | “Usar parâmetro” → criar nome amigável, tipo, obrigatoriedade, descrição e valor de exemplo | Atualiza parâmetros e vínculo em uma mudança atômica do rascunho; reutilizar o mesmo editor no envio da execução |
| 6. Exemplo | “Ver exemplo fictício” ou escolher saída histórica autorizada | Origem, versão, instante e truncamento visíveis; amostra não prova schema completo nem dados atuais da AWS |
| 7. Transformação | Selecionar lista de pagamentos; opcionalmente filtrar status; escolher/renomear campos | UI gera `core.filter`/`core.map`; item atual é escopo controlado; retorno permanece objeto com lista `items` |
| 8. Evento | Adicionar propriedades, objetos e listas; vincular pagamentos transformados; revisar prévia | Monta `Payload` como dados. O provedor já serializa objetos/listas; não serializar duplamente na UI |
| 9. Lambda | Buscar/selecionar função ou informar nome visualmente; escolher modo de invocação com explicação | Padrão do modelo: aguardar resposta. Invocação assíncrona não é apresentada como sucesso do processamento interno da função |
| 10. Aprovação | Texto comum para intenção e tokens de contexto permitidos; revisar destino e dados relevantes | Prévia ligada ao snapshot/execução. Aprovação manual não substitui aprovações adicionais impostas pela política. Não prometer editor de RBAC ou novos aprovadores por nó |
| 11. Revisar | Lista de pendências com salto ao campo; validar; salvar; publicar conforme papel | Aplicar ≠ salvar ≠ publicar. Publicação usa versão imutável. Sem permissão, explicar qual operação está indisponível |
| 12. Operar | Simular a versão publicada; acompanhar etapa; inspecionar erro/saída; exportar JSON/CSV | Para exercitar aprovação humana no laboratório, execução efetiva **demo** separada da simulação. Em modo AWS, simulação pode fazer leituras reais; não prometer “offline” |

### Semântica AWS que a interface deve preservar

`Query` exige igualdade na chave de partição, admite condição de ordenação e tem paginação; `Limit` limita itens avaliados, não garante quantidade retornada após filtro. Uma página pode ter zero itens e ainda ter continuação. Filtro não torna a leitura gratuita; GSI não permite consistência forte. A UI deve separar “limite por requisição” dos limites do FlowOps. [Referência Query](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_Query.html).

`GetItem` usa a chave primária completa da tabela e retorna um item ou ausência; não consulta índice. Ocultar controles de índice/limite que não se aplicam e sinalizar a troca de contrato de saída antes de alterar vínculos. [Referência GetItem](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_GetItem.html).

`Scan` avalia itens de tabela/índice, com paginação e custo próprios; não é fallback de Query nem equivalente a filtrar uma lista já obtida. Mantê-lo como operação deliberada, fora do primeiro assistente. [Referência Scan](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_Scan.html).

O provedor já aceita `_flowops` com `paginate`, `max_pages`, `max_items` e `max_bytes`. Aproveitar esses controles e seus limites existentes, inicialmente com paginação automática desligada e prévia dos valores efetivos. Não criar um laço no navegador para carregar tudo. Resultado truncado deve impedir alimentação silenciosa de etapas posteriores quando assim exige o motor.

### Mensagens e recuperação

| Situação | Mensagem/ação proposta |
| --- | --- |
| Ainda não buscou | “Nenhum recurso foi consultado. Confirme conta/região e clique em Buscar.” |
| Carregando | “Buscando tabelas no contexto selecionado…”; impedir submissão repetida; não apagar seleção anterior |
| Sem resultado | “Nenhuma tabela encontrada neste contexto. Revise os filtros ou informe um nome.” |
| Acesso negado | “Seu perfil não permite consultar estes recursos. O rascunho foi mantido.”; sem sugerir ampliar permissões automaticamente |
| Referência quebrada | “A etapa de origem foi removida ou não fornece este campo. Selecione outra origem.” |
| Tipo desconhecido | “Este tipo depende da saída em execução; a amostra não confirma todos os casos.” |
| JSON inválido | “Não foi possível aplicar. Seu texto está preservado; a prévia mostra a última versão válida.” |
| Conflito de revisão | “Existe um rascunho mais recente. Suas alterações não foram sobrescritas. Compare antes de salvar.” |
| Nada publicado | “Este procedimento ainda não tem versão publicada. Revise e publique, se tiver permissão.” |
| Aprovação simulada | “A simulação não cria pendência humana. Para testar a decisão, use o modo de demonstração efetivo.” |
| Voltar/fechar | Preservar buffer; se necessário, decisão explícita entre continuar, aplicar e descartar |
| Falha em etapa | Nome, motivo e ação possível; exportar evidência sanitizada. Não oferecer repetir mutação insegura como correção automática |

## 6. Arquitetura e opções técnicas

### Comparação para este projeto

| Alternativa | Benefício | Custo/risco | Decisão |
| --- | --- | --- | --- |
| Evoluir Streamlit + adaptadores de autoria | Reutiliza diálogos, sessão, provider e testes; entrega vertical sem novo serviço | Estado de widgets/reruns e listas complexas precisam de projeto e testes rigorosos | **Recomendada para a primeira entrega** |
| Componente React próprio, embutido somente no editor | Reúso executável seletivo de componentes do builder; controles ricos e estado local mais fino | Bundle, bridge, acessibilidade, autenticação/contexto e sincronização versionada adicionais | Alternativa técnica delimitada, condicionada à avaliação do primeiro recorte |
| Migrar toda a aplicação para Next.js/builder | Liberdade de composição do frontend | Reescrita, integração de todas as jornadas, superfície de segurança e operação maiores | Não recomendado neste plano |
| Trocar FlowOps/React Flow por ASL Viewer como modelo principal | Recursos prontos para ASL | Conversão com perdas ou segundo motor/contrato; não resolve os formulários AWS genéricos | Não adotar |

Não adotar JSON Forms + Cloudscape + todo `@nicobelle/ui` simultaneamente. Se a opção React for necessária, selecionar uma base de componentes, extrair o mínimo autorizado do builder e comparar um formulário recursivo de referência com JSON Forms; só então justificar dependência e manutenção.

### Responsabilidades propostas

- **Apresentação:** editor contextual, lista, assistente, ajuda e validação junto aos campos em Streamlit; sem boto3 e sem persistência indireta.
- **Estado de autoria:** rascunho aplicado, buffers por etapa/campo, revisão base, modo e pendências. IDs de itens de UI não entram no contrato de execução. Chaves de widget estáveis; não usar conteúdo sensível nas chaves.
- **Adaptadores puros:** leitura da configuração existente, reconhecimento da parte visualmente suportada, aplicação de patch, geração de caminhos e relatório de trechos preservados. Recebem dados, retornam dados/diagnósticos; não acessam AWS.
- **Metadados de apresentação por ação:** grupos, rótulos pt-BR, ajuda, exemplos e editor especializado. Reutilizar `Action.metadata.input_schema`, sem criar outra lista de permissões/operações executáveis.
- **DynamoDB:** estender o construtor existente com bindings reconhecidos, edição reversível, valores padrão seguros e opções avançadas preservadas. Não confundir `DescribeTable` com schema completo dos atributos dos itens.
- **Lógica e expressões:** usar `core.logic`, `core.expressions` e `core.mapping`. Corrigir/estender o navegador de caminhos da apresentação sem ampliar silenciosamente a DSL. Nomes que não possam ser endereçados pela DSL devem ser explicitamente sinalizados.
- **Validação:** schema estrutural e tipos na autoria; `validate_graph` e políticas continuam autoridade final. Distinguir rascunho editável incompleto de procedimento publicável. Valor de tipo `any` não significa “validado com certeza”.
- **Persistência/engine/provider:** salvar/publicar pelo contrato existente, execução pelo engine, transporte/preparação pelo provider. Nenhum efeito operacional causado por rerender ou alternância de modo.

Fluxo de estado proposto:

```text
Canvas / Lista / Assistente / Código
                ↓ mesma seleção e buffers isolados
       Validar alteração + Aplicar explicitamente
                ↓
       Runbook em rascunho de sessão
                ↓ Salvar com revisão esperada
       Rascunho persistido
                ↓ Publicar com autorização
       Versão imutável → Engine → Provider AWS

Erro de edição → buffer preservado + última prévia válida
Conflito ao salvar → comparar, não sobrescrever
```

### Invariantes e limites

As referências canônicas continuam sendo [segurança](C:/Development/projects/personal/aws-flowops/docs/SECURITY.md:1), [arquitetura](C:/Development/projects/personal/aws-flowops/docs/ARCHITECTURE.md:1) e [operações](C:/Development/projects/personal/aws-flowops/docs/OPERATIONS.md:1).

- Não ampliar grants, allowlist genérica, conta/região/recurso, aprovações, idempotência ou caminhos de retry por conveniência do formulário.
- Textos, exemplos e prévias não podem registrar credenciais, DSNs, tokens ou payloads sensíveis indiscriminadamente. Dados de execução permanecem sanitizados e limitados; não enviar dados do projeto a serviços de referência.
- Demonstrar com fixtures. Prévia histórica exige autorização e origem identificada. Leitura AWS real, quando disponível na implementação, é explícita, limitada e passa pelo provider.
- Edição visual não altera versão publicada nem execução em curso. Alteração de labels não muda IDs de referência; renomeação de identificadores exige atualização validada ou rejeição clara.
- Mudança de ação, remoção de nó e troca Query/GetItem devem mostrar impacto nos vínculos. Nenhuma reconexão automática pode apagar a intenção de aprovação/ramificação.
- Proposta inicial não requer migração de banco nem `schema_version` novo. Caso a implementação encontre necessidade de nova semântica de parâmetros/expressões, separar decisão de contrato e migração; não reinterpretar documentos antigos.
- Não adotar autosave de payloads em `localStorage` por imitação das referências. Permanência após fechar/reabrir navegador depende de salvar explicitamente pelo contrato atual; não prometer recuperação durável de todo buffer inválido.

## 7. Plano incremental, dependências e reversão

Estimativas relativas, não calendário prometido. As ondas são sequenciais onde compartilham UI/estado. Nenhum paralelismo de escrita sobre os mesmos arquivos será presumido.

| Onda | Entrega / dependência | Área de mudança prevista | Verificação de saída |
| --- | --- | --- | --- |
| 0 — estabilizar e delimitar | Reconciliar árvore atual; diagnosticar intermitência E14; fixar contratos de edição e casos antigos | Sessão/canvas/live interaction e testes relacionados; plano de trabalho próprio | Reprodução ou diagnóstico com evidência e correção testada; não encerrar falha por repetição verde isolada |
| 1 — fundação da autoria | Buffer/patch, presença/tipos, objetos/listas, origem do valor, formulário visual de parâmetros; depende dos contratos da onda 0 | `typed_inputs`, `node_editor`, helpers de autoria e `mapping`; nomes finais definidos na implementação | Testes puros e AppTest de estado, types, round-trip, propriedades desconhecidas e ausência de efeitos |
| 2 — recorte DynamoDB/Lambda | Reedição de Query, parâmetros, filtro/map, payload aninhado, recurso destino e mensagem contextual de aprovação; depende de 1 | `resource_picker`, construtor Dynamo, `workspace`, editor, template de referência | Mesmo procedimento criado e reeditado sem JSON; old config preservada; fixtures sem AWS real |
| 3 — jornada completa | Entrada por objetivo, navegação de etapas/teclado, revisão/publicação/execução demo, inspeção/exportação e guia; depende de 2 | UI de procedimentos/editor/execução, resultados, localização, testes browser | Os 12 passos completos; simulação e aprovação manual demo verificadas separadamente; falha exportável |
| 4 — expansão orientada por uso | Generalizar formulários para ações frequentes, lógica adicional, catálogo/inventário/ajuda e navegação global | Incrementos por ação e journey, evitando promessa de cobertura completa automática | Critérios por ação; métricas de onde ainda se exige código; revisão de riscos AWS |
| 5 — editor React delimitado, se necessário | Testar extração autorizada do builder e custom nodes/portas/undo; depende de avaliação 1–4 e aprovação técnica específica | Um componente frontend com mensagens versionadas; backend intacto | Prova de não perda, teclado, revisão concorrente e build/segurança; comparar benefício medido antes de expandir |

**A primeira entrega de produto abrange as ondas 0–3**, não apenas um formulário bonito ou um protótipo de campo. Inclui o modo avançado preservado e o caminho sem arrastar. A estabilização prévia não é autorização para reescrever o motor.

Escopo inicial dos editores especializados: Query/GetItem S/N nos casos reconhecidos pelo construtor, parâmetros, uma condição de filtro, projeção/renomeação via map, objeto/lista de payload Lambda e mensagem de aprovação. Chaves binárias, condições não reconhecidas, cálculos, conversões gerais e configurações arbitrárias permanecem avançadas/preservadas. A jornada de referência completa usa os casos suportados; não se declara “todo o catálogo sem código”.

### Reaproveitar, melhorar, criar e adiar

| Reaproveitar | Melhorar | Criar | Adiar |
| --- | --- | --- | --- |
| Modelo Runbook, versões, engine/provider, schemas, template, resultados/exportações, layout atual | Campos tipados, builder Dynamo, mapper, diálogo, ajuda pt-BR, revisão e continuidade | Editor recursivo de valores, seletor de origem integrado, contrato de buffer/patch, parâmetros visuais, assistente do objetivo e conexões por teclado | Migração Next.js, target ASL, serviços externos, tour, conversões arbitrárias, editor visual de toda AWS, undo/redo geral |

### Riscos e reversão

| Risco | Mitigação / condição | Reversão |
| --- | --- | --- |
| Perda de opções no visual/código | Reconhecimento parcial + patches + casos de compatibilidade; parar a entrega se perder dados | Retornar ao editor técnico preservado; definições continuam no formato atual |
| Reruns perdem buffer/foco/seleção | Estado estável, aplicação por intenção, testes de interleaving; não confiar apenas no último render | Desabilitar entrada do novo editor, preservando helpers/definições compatíveis e dados salvos |
| Conversão incorreta de tipos Dynamo/listas | Contrato wire explícito, sem casts implícitos; amostras não são schema | Manter trecho avançado; não regravar configuração antiga |
| Complexidade excessiva do assistente | Restringir ao modelo reconhecido; lista/canvas continuam disponíveis | Remover acesso ao assistente sem converter o grafo |
| Novas dependências React elevam manutenção | Só após prova delimitada; extração mínima e auditoria | Voltar à UI Streamlit; não acoplar armazenamento ao componente |
| Falhas de ambiente/CI anteriores | Tratar TLS, intermitência e CI da árvore exata como pendências independentes | Sem promoção/deploy até evidência adequada; não relaxar gates |

Na implementação, usar branch técnica, preservar alterações locais e reverter apenas hunks do incremento aprovado. Não apagar bancos, referências, rascunhos ou histórico. O plano atual, por ser documental, pode ser revertido removendo somente seus dois arquivos novos.

## 8. Aceitação e estratégia de validação

Os critérios abaixo nasceram como metas do plano. A coluna de reconciliação registra o que a árvore de 27/09/2026 demonstra de fato. **PASS** exige evidência automatizada compatível com o critério; **PARCIAL** identifica uma parte ainda não demonstrada literalmente. O estudo humano e a CI remota não são usados para completar artificialmente estes ACs.

| ID | Critério mensurável | Evidência exigida |
| --- | --- | --- |
| AC01 | Os 12 passos da jornada de referência podem ser configurados com zero edição manual de JSON ou expressão | Jornada de navegador com fixtures, registrando ações e zero preenchimento de editor técnico |
| AC02 | Visual → código válido → visual preserva estrutura, tipos, IDs, vínculos e opções não alteradas | Comparação profunda de fixtures, excluindo apenas metadados de UI; ordem de listas preservada |
| AC03 | Configuração avançada não reconhecida permanece idêntica após editar outro campo e salvar | Casos com `_flowops`, opções extras válidas, expressão e subárvore aninhada |
| AC04 | Código inválido, erro de campo, voltar, fechar/reabrir editor na sessão e troca de modo não apagam o buffer | AppTest + navegador; “última versão válida” identificada; descarte somente explícito |
| AC05 | Ausente/null/false/0/texto vazio/lista vazia/objeto vazio não se confundem | Matriz de tipos nos helpers, parâmetros e payload; respeitar limitações declaradas do contrato de default |
| AC06 | Objetos e listas suportados permitem adicionar/remover/editar/reordenar itens sem JSON | Testes com três níveis, listas de objetos/listas, nomes duplicados e limites excedidos |
| AC07 | Referências inválidas, tipos incompatíveis conhecidos e item fora de escopo são bloqueados com caminho de correção | Testes negativos de ancestrais/ramos, remoção, mudança Query/GetItem, índices e valores indisponíveis; `any` sinalizado |
| AC08 | Alterar visão, abrir formulário, validar ou renderizar prévia fictícia causa zero chamadas AWS e zero submit/publish | Spies/fakes que falham em qualquer chamada; comparação de revisão/eventos/execuções antes/depois |
| AC09 | Backend mantém autorização mesmo com submissão forjada ou papel sem grant | Testes VIEWER/AUTHOR/OPERATOR/APPROVER, produção, motivo, confirmação, two-person e aprovação vinculada |
| AC10 | Aprovação simulada não cria pendência; execução efetiva demo pausa e exige decisão autorizada | Dois testes independentes; rejeição impede envio e aprovação permite continuação pelo motor |
| AC11 | Salvar usa revisão esperada, conflito mantém buffer, publicado/histórico permanecem imutáveis | Regressões Repository/engine + AppTest com dois rascunhos concorrentes |
| AC12 | Criar, conectar com ramo, configurar, revisar e inspecionar funcionam só com teclado | Jornada sem drag/drop; foco restaurado após diálogo, nomes acessíveis e erros alcançáveis |
| AC13 | Formulários e ações essenciais não se sobrepõem nem desaparecem em 1440/1024/390 px | Medições geométricas + inspeção visual; formulário em coluna única quando necessário |
| AC14 | Labels, ajuda, validação, estados e confirmação são pt-BR no recorte | Inspeção de página/diálogo e teste de localização; identificadores/código original isolados e rotulados |
| AC15 | Resultados de sucesso/erro/pendência e exportações mantêm identificação da etapa e sanitização | JSON/CSV, CSV seguro para planilha, truncamento, zero segredo e diagnóstico da versão correta |
| AC16 | Procedimentos antigos importados em JSON/YAML continuam editáveis/executáveis nos mesmos casos | Fixtures de serialização e versão; nenhuma conversão silenciosa para ASL ou schema novo |
| AC17 | Query mantém contrato de chaves, índice, limite/paginação e ausência de fallback para Scan | Casos GetItem com índice inválido, GSI/consistência, número inválido, aliases e continuidade vazia |
| AC18 | Repetição da jornada com atualizações de execução não troca página/resultado nem perde edição | Regressão determinística da intermitência identificada + repetição browser; repetir verde não substitui causa corrigida |

### Reconciliação AC01–AC18 — 27/09/2026

| AC | Estado | Evidência atual |
| --- | --- | --- |
| AC01 | PASS | `scripts/browser_authoring.py` percorre criação → configuração → revisão → publicação → simulação → execução demo → aprovação → resultado/exportação; `keyboard.json` registra `manual_JSON=false` e `manual_expressions=false`. |
| AC02 | PASS | `test_visual_authoring.py` e `test_react_editor.py` verificam round-trip, tipos, IDs/bindings e aplicação atômica sem perder subárvores opacas. |
| AC03 | PASS | `test_dynamodb_authoring.py::test_read_roundtrip_retains_advanced_options_and_bindings` e `test_react_editor.py::test_inline_patch_preserves_advanced_values_and_validates_types`. |
| AC04 | PASS | `test_visual_authoring.py::test_invalid_code_buffer_survives_navigation_and_blocks_mode_switch`, buffers de sessão e conflitos preservados nos testes de presenter. |
| AC05 | PASS | `test_edit_buffer_roundtrip_keeps_absence_null_false_zero_nested_and_advanced` e teste JS que garante campo numérico vazio ≠ zero. |
| AC06 | PASS | `test_visual_list_add_reorder_remove_without_json` e editor recursivo cobrem edição visual de coleções/objetos dentro dos limites declarados. |
| AC07 | PASS | `test_broken_reference_and_item_scope_cannot_be_applied`, incompatibilidade conhecida e validações de mapping bloqueiam referências inválidas. |
| AC08 | PASS | Preview fictícia e revisão são puras; testes de workspace/collection-preview verificam ausência de persistência/chamada operacional ao apenas renderizar/revisar. |
| AC09 | PASS | `test_policies.py`, `test_engine.py`, `test_hardening.py` e testes do bridge exercitam grants, produção, two-person e payload forjado/fail-closed. |
| AC10 | PASS | Engine/application distinguem dry-run de execução efetiva; browser authoring comprova que simulação não cria pendência e execução demo efetiva pausa para aprovação. |
| AC11 | PASS | `test_concurrent_draft_updates_only_one_wins` e `test_revision_conflict_preserves_and_exports_local_work`; publicação/versionamento permanecem imutáveis. |
| AC12 | PASS | `scripts/browser_authoring.py` percorre a jornada sem interação de ponteiro nos comboboxes: Tab/Shift+Tab, Enter, Space, texto e confirmação direta por Enter; a execução `authoring-completion` passou após essa mudança. |
| AC13 | PASS | `browser_layout.py` mede 1440/1024/390 e o React registra as mesmas larguras; `--layout-only` passou após tornar a visão Canvas determinística. |
| AC14 | PASS | `test_localization.py`, inspeção das dez páginas no workspace e browser atual validam pt-BR no recorte, preservando identificadores AWS. |
| AC15 | PASS | `test_results.py`, `test_workspace_usability.py` e browser authoring validam etapa correta, JSON/CSV, sanitização e exportação do resultado Lambda. |
| AC16 | PASS | `test_serialization.py`, migrações e contratos confirmam JSON/YAML antigos como Runbook, sem conversão implícita para ASL. |
| AC17 | PASS | `test_query_builder.py` + `test_dynamodb_authoring.py` cobrem chave/índice/tipos/limite e recusam combinações inválidas sem fallback silencioso para Scan. |
| AC18 | PASS | `test_live_selection_regression.py`, sincronização de `flowops:selected_runbook`, undo/redo e browsers repetidos comprovam que reruns não reaplicam seleção obsoleta nem trocam o procedimento criado. |

Com a confirmação direta por teclado dos `selectbox` BaseWeb, **AC01–AC18 estão automatizadamente comprovados no escopo definido**. A CI remota da árvore candidata exata também passou; isso não substitui o estudo humano planejado.

### Testes existentes a ampliar, não substituir

[test_typed_inputs.py](C:/Development/projects/personal/aws-flowops/tests/test_typed_inputs.py:1), [test_query_builder.py](C:/Development/projects/personal/aws-flowops/tests/test_query_builder.py:1), [test_mapping.py](C:/Development/projects/personal/aws-flowops/tests/test_mapping.py:1), [test_serialization.py](C:/Development/projects/personal/aws-flowops/tests/test_serialization.py:1), [test_canvas_sync.py](C:/Development/projects/personal/aws-flowops/tests/test_canvas_sync.py:1), [test_streamlit_editor_journey.py](C:/Development/projects/personal/aws-flowops/tests/test_streamlit_editor_journey.py:1), [test_streamlit_business_journeys.py](C:/Development/projects/personal/aws-flowops/tests/test_streamlit_business_journeys.py:1), [test_results.py](C:/Development/projects/personal/aws-flowops/tests/test_results.py:1) e [browser_workspace.py](C:/Development/projects/personal/aws-flowops/scripts/browser_workspace.py:1).

Na implementação aprovada: primeiro helpers puros e testes negativos, depois AppTest, depois navegador com fixtures, depois checks canônicos do repositório. Ruff, mypy, pytest com cobertura mínima 96%, Bandit, auditoria de dependências, build e CI remota da árvore candidata foram executados com sucesso. Integrações opt-in relevantes devem ser explicitadas; nenhum teste exige conta AWS de produção.

### Avaliação de usabilidade proposta

Rodada exploratória com 5 usuários técnicos e 5 não técnicos autorizados, usando dados fictícios e permissões coerentes com o papel. É amostra qualitativa para encontrar obstáculos, não prova estatística de adoção.

Tarefas: criar a jornada, trocar pagamento por parâmetro, acrescentar propriedade aninhada/lista, corrigir vínculo quebrado, identificar por que a execução aguarda aprovação, exportar o resultado correto. Separar autoria e aprovação quando houver two-person; não exigir que um participante tenha todos os grants.

Medir conclusão sem ajuda, tempo, intervenções, erros recuperados, abandono e cada momento em que seria necessário código. Metas iniciais para discussão: pelo menos 8/10 concluem a configuração sem ajuda do facilitador, zero JSON/expressão nos casos suportados, zero perda de rascunho e 10/10 distinguem demonstração, simulação e execução real antes de executar. Tempo deve ser comparado a uma linha de base coletada, não a uma redução inventada. Resultados por perfil, não apenas média agregada.

Se as metas falharem, corrigir os pontos observados antes de expandir o catálogo ou trocar framework. Considerar React delimitado se forem comprovados limites de estado, teclado ou responsividade que a solução Streamlit não atender no recorte.

## 9. Estado atual da entrega — 27/09/2026

A implementação deixou de ser apenas uma proposta. O editor visual, o componente React delimitado, os formulários recursivos, histórico, criação por objetivo, revisão contextual, Resource Discovery v2 e jornadas de execução/aprovação estão implementados na árvore local e passaram pelos gates descritos acima.

Os problemas técnicos encontrados durante a validação desta rodada foram tratados em vez de ocultados: seleção persistente de runbook no Streamlit, testes PostgreSQL com tokens não reexecutáveis, sandbox Moto contaminado entre execuções, cleanup de setup no Windows, runtime Lambda baixado desnecessariamente, teste browser preso ao antigo campo JSON e helper de layout dependente da visão anterior.

**Gates locais atuais:** suíte consolidada verde com cobertura mínima; browsers de acceptance geral, laboratório local, workspace e authoring verdes; checks estáticos/segurança/build/audits verdes. A evidência exata e atual fica nos task-runs em `.agents/runs/` e em `browser-artifacts/`.

**Pendência que não deve ser simulada:** a avaliação com T01–T05 e N01–N05 ainda não foi realizada. A árvore candidata está limpa, publicada em `codex/code-defined-tours`, e o SHA `f73eaee9acc5b12a1e4955305ddeb16b242c08f1` passou no workflow remoto `Quality` por `push` e `pull_request`. Os AC01–AC18 estão verdes nos gates automatizados locais e remotos; isso não é apresentado como substituto para a avaliação humana planejada.

Impacto AWS da validação: nenhum acesso a conta AWS real; somente demo/fakes/Moto. Impacto de persistência: sem migração nova. Impacto de deploy: nenhum. Reversão: alterações continuam isoladas na branch técnica e não foram promovidas.
