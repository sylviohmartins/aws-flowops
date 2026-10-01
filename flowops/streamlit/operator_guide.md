# Guia passo a passo do FlowOps

Este guia está sempre disponível no menu. Comece pelo exemplo **Consulta DynamoDB para Lambda**:
ele mostra uma consulta real do ponto de vista do contrato AWS, a transformação do resultado,
a aprovação e a criação dos dados enviados a uma Lambda. No modo **Demonstração**, todos os recursos são fictícios.

## 1. Entenda a área de trabalho

| Área | Quando usar |
| --- | --- |
| Visão geral | Consultar indicadores e execuções recentes |
| Procedimentos | Criar a partir de modelos; importar, exportar, clonar e arquivar |
| Editor visual | Adicionar etapas, conectar caixas, configurar e publicar |
| Executar | Escolher uma versão publicada e fornecer seus parâmetros |
| Execuções | Acompanhar o grafo, investigar erros e exportar saídas |
| Aprovações | Revisar solicitações pausadas e registrar uma decisão |
| Auditoria | Investigar quem fez o quê, onde, quando e por quê |
| Recursos AWS | Descobrir recursos por leitura explícita |
| Catálogo de ações | Buscar operações e consultar suas estruturas de dados e permissões |

Confira o indicador de **ambiente, conta, região e modo** antes de operar. Demonstração usa dados
fictícios; Laboratório local usa o emulador; AWS real usa o contexto definido pela aplicação hospedeira.

## 2. Crie o procedimento do exemplo

1. Abra **Procedimentos → Criar a partir de um modelo**.
2. Em **Modelo**, escolha **Consulta DynamoDB para Lambda**.
3. Preencha **Equipe** com sua equipe autorizada; use **Nome do procedimento (opcional)** para distinguir a cópia.
4. Clique **Criar procedimento**. Isso cria um rascunho, sem executar as etapas.
5. Abra **Editor visual** e selecione esse procedimento.

O fluxo será: Início → Consultar DynamoDB → Preparar evento → Aprovar envio → Enviar para Lambda → Fim.
Os IDs estáveis são `query`, `prepare_event`, `approve` e `invoke`; expressões usam esses IDs, não os títulos das caixas.

## 3. Adicione e configure uma caixa

Em **Adicionar etapa**, filtre por **Serviço da ação** e **Buscar ação**, escolha **Ação**
e clique **Inserir antes do fim**. Clique na caixa para abrir **Editar etapa**.
O botão **Editar etapa selecionada** e a lista **Propriedades da etapa** oferecem acesso alternativo por teclado.

- **Nome da etapa** descreve a intenção. **Habilitada** define se a etapa participa da execução.
- **Configuração visual** (ou **Configurar lógica**) permite preencher texto, números e opções, criar objetos e listas, adicionar/remover campos e mover itens para cima. Confira o **Tipo** antes de preencher: texto `0`, número `0`, falso, nulo e campo ausente são diferentes.
- **Valor de outra origem** permite escolher um parâmetro, contexto ou saída anterior. Confirme com **Usar origem** e depois **Aplicar configuração ao rascunho**. Não é necessário escrever a expressão gerada. Tipos desconhecidos são sinalizados, sem conversão automática.
- **Ver JSON** mostra o buffer sem editar; **Editar JSON** é a opção técnica. JSON inválido impede aplicação/troca para o visual e fica preservado. O buffer sobrevive a fechar o editor e navegar na mesma sessão; não substitui um salvamento durável.
- **Propriedades avançadas da etapa** contém nome, habilitação e tratamento de falhas; aplicar essas propriedades não substitui a configuração visual.
- **Tratamento de falha** permite Interromper (`STOP`), Continuar (`CONTINUE`), Tentar novamente (`RETRY`), Seguir caminho de falha (`FAIL_BRANCH`) ou Intervenção manual (`MANUAL_INTERVENTION`). Novas tentativas exigem idempotência; são permitidas de 1 a 5 tentativas, com intervalo de 0 a 10 segundos.
- **Voltar ao fluxo** fecha o painel. Aplicar campos ainda não salva uma revisão durável: finalize com **Salvar rascunho**.

Arraste as alças para conectar nós. Use o menu da conexão para escolher seu ramo.
Em uma condição, conecte `true` e `false`; em FAIL_BRANCH, configure o destino de falha.
Duplicar uma caixa copia a configuração, mas exige revisar suas novas conexões.

Em **Visão de edição**, escolha **Canvas**, **Lista de etapas** ou **Assistente**. As três visões
usam o mesmo rascunho, sem reordenar conexões. No assistente, aplique os campos e use **Próxima etapa**;
a ordem apresentada respeita dependências, mas não significa que todos os ramos serão executados.
**Conectar etapas sem arrastar** oferece origem, destino, ramo e remoção por teclado. Uma remoção
pode deixar o rascunho desconectado: corrija e valide antes de salvar.

Em **Detalhes do procedimento → Parâmetros do procedimento**, adicione um campo do tipo Objeto
para cada parâmetro. Defina `type` (tipo), `required` (obrigatório), `description` (instrução de
preenchimento) e, se necessário, `default` (padrão). O padrão precisa ter o tipo correto.
No contrato atual, padrão nulo equivale a não ter padrão; um parâmetro obrigatório precisará
ser informado ao executar. Não coloque senhas ou credenciais nos parâmetros/configurações.

### Organize a área do fluxo

1. Use **Organizar fluxo** para alinhar as caixas da esquerda para a direita conforme as conexões,
   separando etapas paralelas. Isso muda somente as posições; não configura campos nem executa ações.
2. Confira o resultado usando zoom e o minimapa. Fluxos com ciclos ou conexões para etapas
   inexistentes precisam ser corrigidos antes; campos incompletos não impedem a organização.
3. **Desfazer organização** restaura as posições anteriores na mesma sessão. É um único desfazer,
   disponível até salvar, mover caixas ou alterar a estrutura/conexões. Edições de nomes e campos são preservadas.
4. Clique **Salvar rascunho** quando quiser gravar as posições. Uma versão já publicada não muda.

Organizar não valida se o procedimento pode executar; continue usando **Validar**.
As caixas usam espaçamento fixo: fluxos muito grandes podem exigir zoom e ajustes manuais.
Leitores sem permissão de edição podem consultar o grafo, mas não reorganizá-lo.

## 4. Construa a Query DynamoDB

O exemplo usa uma tabela `payments` com chave de partição `paymentId` do tipo texto.
Na caixa **Consultar DynamoDB**, o JSON é:

```json
{
  "TableName": "{{ params.table_name }}",
  "KeyConditionExpression": "#pk = :pk",
  "ExpressionAttributeNames": {"#pk": "paymentId"},
  "ExpressionAttributeValues": {":pk": {"S": "{{ params.payment_id }}"}},
  "Limit": 30
}
```

`#pk` representa o nome da chave; `:pk` representa seu valor tipado. `S` significa texto;
use `N` para números DynamoDB, cujo valor também é uma string. `Limit` limita uma página de leitura.
Uma Query usa igualdade na chave de partição e pode restringir a chave de ordenação. Ela não equivale a SQL arbitrário.

Para gerar a configuração sem escrever esse JSON:

1. Escolha `dynamodb.query` ou `dynamodb.get_item` na paleta.
2. Clique na caixa, abra **Buscar recursos e montar consulta DynamoDB** e clique **Buscar recursos para esta etapa**.
3. Escolha **Recurso encontrado** e **Aplicar recurso selecionado**.
4. Use **Carregar estrutura da tabela**. Se mudar a tabela, carregue a nova estrutura.
5. Confira **Leitura do DynamoDB**: GetItem exige a chave completa; Query aceita condição de chave. Para trocar uma etapa já configurada entre essas operações, crie outra etapa e revise os vínculos: a saída muda entre `Item` e `Items`.
6. Escolha o índice ou mantenha a chave primária; em **Origem da chave**, escolha valor fixo ou parâmetro textual. Chaves `N` usam texto decimal na API, sem converter parâmetros numéricos implicitamente.
7. Se houver chave de ordenação, selecione condição e, para `between`, o limite superior.
8. Defina **Limite de leitura** entre 1–100 e clique **Aplicar requisição DynamoDB gerada**.

A descoberta de recursos também é usada nas demais ações AWS quando existe uma leitura curada
capaz de fornecer o identificador correto. Campos dependentes só são pesquisados depois que seus
pré-requisitos literais forem aplicados (por exemplo, bucket → objeto, cluster ECS → serviço).
Quando aparecer **Carregar detalhes de ...**, a inspeção é uma leitura explícita e limitada:
ela mostra metadados do recurso escolhido, mas não aplica o valor nem altera o rascunho.
Entrada manual continua disponível na Configuração visual quando não houver uma regra segura.

No DynamoDB, **AttributeDefinitions não representa colunas da tabela**: contém apenas atributos
usados por chaves primárias e índices. A interface mostra essas chaves e os GSI/LSI conhecidos;
outros atributos podem variar entre itens e não são apresentados como um schema relacional.

O construtor preserva `_flowops`, projeções, filtros e demais opções não alteradas; aliases
compartilhados que mudariam outra expressão são bloqueados. Sintaxes de chave não reconhecidas
permanecem nos campos/JSON, sem regeneração destrutiva. `Limit` conta itens avaliados por página,
não resultados após filtro; a paginação do FlowOps é independente. GetItem não usa índice e GSI
não aceita leitura consistente. Descoberta e carregamento da estrutura são leituras explícitas.
Aplicar a configuração não executa a consulta e não faz fallback para Scan.

## 5. Transforme a saída em um evento

Na caixa **Preparar evento**, mantenha o modo **Visual**. Em `items`, escolha **Valor de outra origem**
e a lista `nodes.query.output.Items`. Em `template` (Modelo de saída), adicione os campos do evento.
Para cada campo, escolha **Valor de outra origem → item**; informe o campo dentro desse objeto
(por exemplo `paymentId.S`) e confirme **Usar origem**. `item` só está disponível dentro do modelo.
É possível renomear a saída criando outro campo e removendo o antigo; listas permitem mover itens
para cima. Aplique a configuração. O JSON abaixo é referência técnica, não uma etapa obrigatória.

**Prévia fictícia da transformação** usa um pagamento de exemplo com `paymentId`, `status` e `amount`.
Não consulta a AWS e não usa valores reais dos seus parâmetros. Se a configuração pedir um campo
ausente no exemplo, a prévia falha; isso não significa que o dado esteja ausente no ambiente real.
Salvar/publicar fica bloqueado enquanto houver buffers de campos ainda não aplicados, inclusive
JSON inválido. Volte à etapa indicada e aplique ou use **Descartar alterações não aplicadas**
para recuperar explicitamente a configuração atual. Isso descarta somente o buffer dessa etapa.

Query retorna `Items`, uma lista de objetos DynamoDB. A caixa **Preparar evento** é `core.map`:

```json
{
  "items": "{{ nodes.query.output.Items }}",
  "template": {
    "payment_id": "{{ item.paymentId.S }}",
    "status": "{{ item.status.S }}"
  }
}
```

`items` recebe a lista da etapa `query`. `item` representa cada elemento dentro do modelo de transformação.
O resultado de `core.map` é um objeto com a lista `items` transformada. Para o pagamento de demonstração `12345`:

```json
{"items": [{"payment_id": "12345", "status": "PROCESSING"}]}
```

Para filtrar a coleção antes, use `core.filter` com `items`, `path`, `operator` e `value`.
Para dividir em grupos, use `core.batch` com `items` e `size`. Essas etapas trabalham sobre
dados já lidos; não consulte tabelas inteiras quando uma chave puder limitar a leitura.

Em **Estrutura e mapeamento de dados**, escolha **Campo de destino** e **Origem**, confira os tipos e a prévia,
depois clique **Aplicar mapeamento**. Fontes são parâmetros, contexto e saídas ancestrais.
Uma expressão que ocupa todo o valor preserva seu tipo; não envolva objetos em concatenações de texto.

## 6. Envie os dados para a Lambda

No modo **Visual**, escolha a origem do nome da função. Em `Payload`, use o tipo **Objeto (campos)**;
adicione textos, objetos ou listas conforme o evento esperado. Para o campo `payments`, escolha
**Valor de outra origem → nodes.prepare_event.output.items**. Essa origem envia a lista completa,
sem selecionar automaticamente o primeiro item. A aplicação serializa o objeto para a API da Lambda;
não transforme manualmente o objeto em uma string JSON. Aplique antes de salvar o rascunho.

Na caixa **Enviar para Lambda**, configure:

```json
{
  "FunctionName": "{{ params.function_name }}",
  "InvocationType": "RequestResponse",
  "Payload": {
    "source": "flowops",
    "payments": "{{ nodes.prepare_event.output.items }}"
  }
}
```

O adaptador transforma o objeto `Payload` no formato exigido pelo SDK. `RequestResponse` espera
a resposta e permite inspecioná-la. `Event` faz envio assíncrono: aceitar o evento não significa
que a função tenha terminado com sucesso. Nesse caso, acompanhe a função pelos mecanismos AWS.

O modo de demonstração usa `payment-processor`. Em outro contexto, use uma função existente, com estrutura de dados compatível,
permissão de invocação e escopo correto. Nenhuma função é criada automaticamente pelo modelo.

## 7. Valide, salve e publique

Abra **Detalhes do procedimento** para definir descrição, marcadores, ambientes permitidos e parâmetros.
Use **Aplicar detalhes** e **Aplicar parâmetros**, depois **Validar → Salvar rascunho → Publicar versão**.
Corrija erros de tipos, referências, campos obrigatórios e conexões antes de publicar.
Uma versão publicada é imutável; alterações posteriores pertencem a outro rascunho/versão.

## 8. Execute e acompanhe

Em **Executar**, selecione o procedimento e a **Versão**. Para o exemplo de demonstração, preencha:

| Parâmetro | Valor de demonstração | Por quê |
| --- | --- | --- |
| `table_name` | `payments` | Tabela consultada |
| `payment_id` | `12345` | Chave que restringe a consulta |
| `function_name` | `payment-processor` | Destino do evento |
| Motivo / referência da mudança | `Exercício Query → Lambda` | Contexto auditável |

Mantenha **Simulação do FlowOps** marcada na primeira execução e clique **Enviar execução**.
A visualização ao vivo é atualizada a cada 2 segundos: verde indica sucesso, azul animado indica
trabalho em andamento, âmbar indica aprovação e vermelho mostra erro. Ramos não percorridos ficam cinza.
Uma execução muito rápida pode terminar entre duas atualizações; o estado final continua registrado.

## 9. Exercite a aprovação manual

**Em simulação, a aprovação é simulada e não aparece como pendente.** Para praticar uma pausa
manual, execute o exemplo no modo **Demonstração**, desmarcando Simulação do FlowOps. Isso usa apenas dados fictícios.
Abra **Aprovações**, revise a solicitação e preencha **Motivo da decisão** antes de **Aprovar** ou **Rejeitar**.
Aprovar retoma o mesmo registro imutável; rejeitar interrompe o caminho protegido.

Em AWS real, não desmarque simulação apenas para testar. A operação efetiva precisa ser autorizada.
A política padrão exige outra pessoa para decidir. No laboratório pessoal/demo, a política admite o
mesmo operador para exercitar a interface. Produção também mantém motivo, conta e confirmação explícitos.

## 10. Exporte o resultado de cada caixa

Em **Execuções**, selecione **Detalhes da execução** e clique na caixa da visualização ao vivo.
**Inspecionar resultado da etapa → Etapa do resultado** também seleciona o nó por lista.
Use **Baixar resultado em JSON**, **Baixar resultado em CSV** ou **Baixar diagnóstico do nó (JSON)**.
Uma etapa com falha ou sem saída ainda permite baixar seu registro de execução e erro. CSV neutraliza fórmulas
de planilhas; JSON mantém a estrutura. Saídas já foram limitadas e sanitizadas pelo motor de execução.

**Exportar YAML/JSON** em Procedimentos exporta a definição, não os resultados. Cópias de navegador
também não substituem o histórico durável. Executar novamente cria uma nova execução; cancelamento e
compensação não equivalem a desfazer todas as alterações de forma transacional.

## Catálogo AWS e limites

O catálogo mostra ações curadas e modelos de todos os serviços disponíveis no SDK instalado.
As ações curadas têm risco, leitura/mutação, idempotência e permissões explícitos. A cobertura da demonstração
é menor que o catálogo AWS; a interface informa quando uma ação exige outro modo de execução.
Uma operação apenas consultável não está habilitada para execução. A aplicação hospedeira pode habilitar operações
genéricas revisadas por uma lista explícita de permissões; serviços sensíveis continuam bloqueados e operações desconhecidas
recebem classificação conservadora. Credenciais pertencem à aplicação hospedeira, nunca ao JSON do procedimento.

## Idioma e identificadores técnicos

A interface usa português do Brasil. Campos como **Nome da tabela (TableName)** apresentam a explicação
em português e mantêm o nome técnico para facilitar a configuração. Chaves JSON, expressões, nomes de
recursos, valores aceitos pela AWS e a confirmação digitada `PRODUCTION` não são traduzidos.
Conteúdo escrito por usuários, registros históricos e detalhes técnicos originais também são preservados.

Referências: [modelos e operações Boto3](https://docs.aws.amazon.com/boto3/latest/reference/services/index.html),
[Query DynamoDB](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_Query.html),
[Invoke Lambda](https://docs.aws.amazon.com/lambda/latest/api/API_Invoke.html).
