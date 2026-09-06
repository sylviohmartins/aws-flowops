# Development

## Environment

AWS FlowOps Studio targets Python 3.12+ and keeps business logic outside Streamlit.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -e '.[dev,postgres]'
streamlit run standalone_app.py
```

The standalone application uses the deterministic demo provider by default and does not require AWS credentials.

## Architecture boundaries

- `flowops/domain/`: versioned data contracts.
- `flowops/core/`: DAG validation, safe expressions, mapping, policy and execution.
- `flowops/providers/aws/`: boto3/botocore adapter and Action implementations.
- `flowops/persistence/`: transactional repositories and migrations.
- `flowops/streamlit/`: presentation and embedding boundary only.
- `flowops/observability.py`: sanitized JSON logging and metric snapshots.

Do not import Streamlit from domain/core/provider modules. Do not place boto3 calls in the UI.

## Development loop

Run the same gates as CI before promotion:

```bash
ruff format --check .
ruff check .
mypy flowops
pytest --cov=flowops --cov-report=term-missing --cov-fail-under=60
bandit -r flowops -ll
pip-audit
python -m build
```

The GitHub Actions workflow also starts PostgreSQL 16 and sets `FLOWOPS_TEST_POSTGRES_DSN` so persistence is exercised against both supported engines.

## Adding an Action

Prefer a curated `Spec` in `flowops/providers/aws/catalog.py` when an operation deserves explicit risk/idempotency/IAM metadata. `AWSAction` derives input/output schemas from botocore, which powers validation and the Streamlit schema browser/Data Mapper.

A new Action must define or derive:

- provider/service/operation;
- risk and read-only classification;
- idempotency;
- required IAM permissions;
- input/output schemas;
- preview behavior when mutation simulation is meaningful.

Generic actions remain deny-by-default and require a host allowlist.

## Data Mapper and expressions

Mappings are stored as the existing safe expression DSL, for example:

```text
{{ nodes.lookup.output.Item.paymentId.S }}
```

The mapper only proposes parameters, execution context and outputs from ancestor nodes. When both source and target schemas are known, `validate_graph` rejects incompatible full-expression mappings before publishing/executing.

## Node/schema versioning

`Runbook.schema_version` and `Node.node_version` are persisted in YAML/JSON. Existing version `1` definitions are immutable once published. When a node contract changes incompatibly, add a new node version and an explicit deterministic migration during import; never silently reinterpret an old published snapshot. Keep the old executor compatible until retained execution history no longer depends on it.

## Persistence changes

Add numbered SQL files under `flowops/persistence/migrations/`. SQL must remain portable across SQLite and PostgreSQL unless the adapter explicitly handles the difference. Every migration must be tested through repository initialization and PostgreSQL CI.

## Streamlit safety

Rendering must not trigger mutating APIs. Mutations belong behind explicit buttons/forms and become durable execution requests before worker execution. `st.session_state` is UI state only; it is never authoritative for runbooks, executions, approvals or audit.

## Logging

Set `FLOWOPS_LOG_LEVEL` (`DEBUG`, `INFO`, `WARNING`, etc.) to control structured FlowOps logs. Audit events are emitted as sanitized JSON using the same central redaction used for persisted outputs.
