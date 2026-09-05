# AWS FlowOps Studio

Runbooks visuais e versionados para operações AWS, com core Python independente do Streamlit.

## Executar

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -e '.[dev]'
streamlit run standalone_app.py
```

O standalone usa demonstração local sem credenciais AWS. Consulte `docs/PROGRESS.md` para o estado validado de cada incremento.

## Integrar

```python
from flowops.domain.models import AWSContext, Identity
from flowops.streamlit import FlowOpsPage

FlowOpsPage(
    user=Identity(id="authenticated-user", roles=["VIEWER"]), aws_context=AWSContext()
).render()
```

O host mantém o controle da autenticação e do servidor. A importação não inicia Streamlit nem cria sessões boto3.

## Testar

```bash
python -m unittest discover -v
pytest --cov=flowops --cov-report=term-missing
ruff check .
ruff format --check .
mypy flowops
```
