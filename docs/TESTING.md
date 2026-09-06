# Estratégia de testes

## Objetivo

A suíte precisa provar não apenas funções isoladas, mas as invariantes operacionais que evitam
mutações incorretas: versionamento, DAG, idempotência, policy, aprovação, persistência,
concorrência, simulação e integração Streamlit.

## Gates da CI

A workflow Quality executa em Python 3.12:

```bash
ruff format --diff .
ruff check .
mypy flowops
pytest --cov=flowops --cov-report=term-missing --cov-report=xml --cov-fail-under=96
bandit -r flowops -ll
pip-audit
python -m build
```

A CI também provisiona PostgreSQL 16 e instala `.[dev,postgres]`.

## Categorias cobertas

### Persistência e versionamento

- migrations idempotentes;
- compare-and-swap de draft;
- publicação imutável e digest;
- arquivo/exclusão lógica;
- tokens de submissão idempotentes;
- SQLite e PostgreSQL.

### Grafo e expressões

- Start/End e alcançabilidade;
- rejeição de ciclos;
- branches válidos;
- referências somente a ancestrais/parâmetros/contexto;
- resolução segura sem `eval`.

### Engine e worker

- checkpoints;
- retomada;
- cancelamento;
- retry de ações idempotentes;
- corrida de workers;
- locks de execução live;
- cleanup de recursos do provider.

### Segurança e governança

- roles aditivas e team scope;
- produção e reason;
- `aws.destructive`;
- limites de impacto;
- preview e decisão de aprovação;
- two-person rule;
- redaction de audit payloads.

### AWS

A suíte valida catálogo/modelos botocore e comportamento do adapter sem depender de uma conta
AWS real. Generic actions precisam de allowlist e serviços bloqueados falham fechados.
Chamadas live AWS não fazem parte da CI porque exigiriam credenciais e recursos externos não
determinísticos.

### Demo E2E

`Fix Stuck Payment` é executado em dry-run e live no backend demo. O dry-run deve chegar a
SUCCESS enquanto a fixture persistente permanece inalterada. O live passa por aprovação e
termina com o pagamento processado.

### PostgreSQL E2E

A CI cria um PostgreSQL real, aplica as migrations e executa:

- fluxo dry-run completo com provider demo, checkpoints e audit;
- execução live core-only para provar aquisição/liberação do resource lock.

### Streamlit

`streamlit.testing.v1.AppTest` inicializa o standalone e percorre todas as páginas principais,
falhando se qualquer rota gerar exception de renderização. Jornadas adicionais exercitam
criação, persistência, publicação, execução, editor, Data Mapper, approvals, histórico,
rerun, auditoria, Resource Explorer, clone, archive e exclusão lógica.

## Testes com AWS real

Faça testes live somente em conta sandbox dedicada e com IAM mínimo. Nunca use production para
provar a suíte. O caminho recomendado é:

1. publicar um runbook read-only;
2. validar conta/região retornadas pelo contexto;
3. executar ações de leitura;
4. executar FlowOps simulation para uma mutação;
5. habilitar uma mutação reversível em staging;
6. conferir CloudTrail e audit events.

## Regressão

O piso global de cobertura de 96% evita quedas silenciosas na cobertura agregada. Ele não
substitui assertions de comportamento: código de segurança, persistência, provider ou engine
deve receber testes específicos mesmo quando a cobertura global já estiver acima do mínimo.
O objetivo é preservar invariantes operacionais, e não perseguir artificialmente 100% por meio
de testes sem valor de regressão.
