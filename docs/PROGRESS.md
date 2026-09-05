# Registro de implementação e evidências

## Etapa 1 — base e persistência

Implementados contratos versionados, migrations, drafts com controle de concorrência,
publicação imutável, arquivo/exclusão lógica, auditoria transacional e fronteira de integração.
UI inicial cria e lista runbooks com submit explícito.

Validação local: unittest (migration idempotente, histórico imutável, concorrência, busca,
arquivo e importação embutida); compileall. Dependências Streamlit/boto3 e ferramentas
externas não estavam instaladas e o download local foi bloqueado pela rede. CI será usada
para verificar as dependências reais. Essa restrição não é evidência de sucesso de UI.

## Plano

Etapa 2: DAG determinístico, rejeição de ciclos/desconexões/edges inválidos, referências
somente a ancestrais, parâmetros tipados e DSL sem execução de código. Canvas encapsulado,
estado estável e contrato defensivo. Testes locais adicionais para ataques por expressão,
tipo booleano versus inteiro, outputs ausentes e payload não confiável do navegador.

1. Base, persistência e interface inicial.
2. DAG, expressões, mapeamento e canvas.
3. Engine, worker e checkpoints.
4. Provider e ações AWS.
5. Políticas, RBAC, aprovações e auditoria.
6. Interface completa, integração e templates.
7. Demonstração E2E, regressão e documentação.

## Etapa 3 — execução

Engine independente, worker em thread pool, fila persistente com claim transacional, token
de submissão e conflito em replay incompatível. Checkpoints por nó, reconstrução após pausa,
branches, execução paralela de leituras, mutações serializadas por conta/região, cancelamento
e simulação explícita. Retry exige idempotência e erro transitório permitido. Manual Approval
é persistida e vinculada ao digest do snapshot/contexto/inputs.

Testes locais: 16 testes cumulativos passando, incluindo corrida entre workers, nenhuma
mutação em simulação, aprovação por outra pessoa, cancelamento e retries. A CI da etapa 2
passou em lint/testes/segurança/dependências/build; os dois erros de tipagem encontrados
foram corrigidos (nomes com tipos distintos e anotação de dicionário).
