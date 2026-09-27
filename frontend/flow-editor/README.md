# Editor visual FlowOps

Componente React embutido no Streamlit, com biblioteca/etapas à esquerda, canvas central e inspetor à direita. Inspiração de composição: `references/starter-react-lib/apps/builder/features/workbench/components/layout/`, autorizado pelo proprietário. O código de referência permanece intacto; não há dependência de seus pacotes privados, autenticação ou serviços.

## Desenvolvimento

Na pasta `frontend/flow-editor`, com Node.js 22 ou superior:

```bash
npm ci --ignore-scripts
npm test
npm run build
npm audit
```

No PowerShell, use `npm.cmd` se a política local impedir o shim `npm.ps1`. O build gera os ativos versionados em `flowops/streamlit/flow_editor_assets/`, incluindo os avisos completos de licença das dependências efetivamente empacotadas. Não há CDN, instalação Node ou servidor frontend exigido em tempo de execução do pacote Python. A CI reconstrói e verifica se os ativos estão atualizados.

## Contrato e limites

- Protocolo 1: identidade do procedimento, revisão esperada, digest da base, identificador do evento e operações limitadas. O backend verifica novamente autorização, tipos, caminhos e vínculos; a mensagem do browser nunca é autoridade operacional.
- `draft` mantém alterações pendentes; `apply` altera somente o rascunho da sessão. Salvar/publicar/executar continuam separados e usam os contratos existentes.
- Caixa e inspetor editam até 64 campos escalares existentes, com profundidade máxima 8. Objetos/listas, parâmetros e construtor DynamoDB permanecem em **Configuração completa**, no formulário visual compartilhado. Inteiros além da precisão JavaScript ficam no editor JSON textual, validado pelo Python.
- Portas azuis definem execução. Portas verdes ligam dados; as quatro primeiras de cada lado aparecem na caixa e as demais estão no painel **Conectar**. O painel também permite conectar sem arrastar.
- JSON inválido permanece pendente; a visão visual conserva a última configuração aplicada. Não há autosave em localStorage nem envio a serviços externos.
- Desfazer/refazer pertence à sessão e à revisão atual. Não desfaz publicação, execução ou efeito AWS.

Regressões: `tests/test_react_editor.py`, `tests/test_authoring_presenters.py`, `scripts/browser_authoring.py`. A prova isolada do React usa `python -m scripts.browser_workspace --react-only`; ela **não** certifica a jornada inteira, que usa `--authoring-completion`.
