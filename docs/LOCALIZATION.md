# Interface em português brasileiro

A interface do AWS FlowOps Studio usa pt-BR: navegação, formulários, mensagens,
estados de execução, controles de aprovação, exportações e guia dentro da aplicação.
O menu usa **Procedimentos** para os Runbooks. Recursos AWS e Catálogo de ações
continuam sendo páginas separadas; esta alteração não reorganiza funcionalidades.

## Limites da tradução

- Nomes de serviços, operações e campos AWS continuam tecnicamente corretos:
  `dynamodb.query`, `TableName`, `Payload`, `RequestResponse`, ARNs e URLs não mudam.
  Campos conhecidos recebem um rótulo português junto ao identificador técnico.
- Os nomes/descrições padrão dos modelos são traduzidos ao criar um novo rascunho
  pela interface. Não há migração de procedimentos existentes ou versões publicadas.
- Textos livres do usuário, dados retornados, configurações JSON, expressões,
  arquivos exportados e registros históricos permanecem no idioma/formato original.
- Erros conhecidos têm mensagem em português. Mensagens desconhecidas recebem uma
  orientação em português e conservam a mensagem original, após a remoção de
  segredos, no painel de detalhes técnicos. Não há tradução automática de erros AWS.
- A referência técnica original do SDK continua disponível em um painel separado
  no catálogo. As orientações em português não substituem essa documentação detalhada.
- `PRODUCTION` continua sendo a confirmação obrigatória digitada. A palavra não é
  alterada, assim como os IDs dos perfis, estados, ambientes e permissões persistidos.

## Manutenção

`flowops/streamlit/localization.py` concentra os rótulos de apresentação,
orientações e erros conhecidos. `presentation_rows` é exclusivo das tabelas de
resumo da aplicação: **não aplicar aos resultados AWS**. A visualização de estruturas
de entrada/saída mantém chaves, tipos e enumerações do contrato do SDK.

`flowops/streamlit/component_locale.py` carrega o recurso empacotado `ui_locale.js`.
O adaptador traduz textos fixos dos controles de terceiros, define `lang="pt-BR"`
e acompanha atualizações do DOM e do editor React Flow. Não altera valores de
campos, opções do usuário, configurações do grafo ou respostas do provedor. Os
observadores são liberados quando o componente é desmontado; documentos de quadros
removidos não são retidos. O calendário nativo usa o idioma do documento e os filtros
de data usam `DD/MM/YYYY`.

Essa adaptação depende da estrutura dos componentes instalados. Ao atualizar
Streamlit ou streamlit-flow, repetir os testes no navegador. Um editor servido em
outro domínio não permite traduzir seu interior por esse adaptador; o empacotamento
padrão utiliza a mesma origem. Uma aplicação hospedeira multilíngue deve considerar
que a página FlowOps define o idioma do documento enquanto estiver montada.

## Verificação local

```powershell
.venv/Scripts/python.exe -m pytest --cov=flowops --cov-report=term-missing --cov-fail-under=96
.venv/Scripts/python.exe scripts/browser_acceptance.py
.venv/Scripts/python.exe -m scripts.browser_workspace
```

A segunda jornada verifica aprovação manual, consulta DynamoDB, transformação,
Lambda demonstrativa, resultado JSON/CSV, diagnóstico de falha, dispositivos móveis
e as dez páginas. Testes específicos protegem chaves AWS, enumerações, textos livres,
histórico imutável e remoção de segredos. As jornadas usam bancos temporários e não
fazem chamadas reais à AWS. `--locale-only` executa somente a inspeção dos controles
e páginas em uma instância temporária.

## Operação e reversão

Não há dependência nova, alteração de esquema, migração de banco, mudança nas
políticas de execução ou implantação AWS. Reinicie o processo Streamlit para carregar
todos os módulos atualizados; uma aba antiga pode manter módulos em memória.
Para reverter, desfaça somente as alterações de localização, preservando as outras
alterações da área de trabalho, e reinicie a aplicação. Não restaure bancos nem
versões publicadas para desfazer tradução.

As verificações locais não substituem a auditoria de dependências e a CI da árvore
exata antes de promoção. Os resultados detalhados desta rodada ficam no registro
temporário `.agents/runs/pt-br-interface.json`.

Verificação de 11/09/2026: 244 testes passaram, 196 subtestes passaram e cinco testes
opcionais não foram executados; cobertura global de 96,24%. As duas jornadas Chromium,
formatação, análise estática, tipos, Bandit, validação das instruções do repositório e
empacotamento passaram. A auditoria de dependências foi interrompida por
`ConnectionResetError (10054)`; a CI desta árvore não foi executada. PostgreSQL,
laboratório Docker e instalação completa não foram revalidados nesta rodada de
tradução. Não houve envio para o GitHub ou promoção para `main`.
