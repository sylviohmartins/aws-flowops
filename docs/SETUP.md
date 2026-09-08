# Setup e execução local

> Para validar efeitos entre serviços sem conta AWS, use `--local`: [laboratório completo](LOCAL_LAB.md). O modo demo abaixo permanece disponível sem Docker.

## Início rápido

Pré-requisitos: checkout deste repositório, Python 3.12+ com `venv`/`pip` e acesso ao índice de
pacotes configurado no pip para a instalação. Não é necessário ativar um ambiente virtual.

Na pasta do repositório, execute **um** dos comandos:

| Terminal | Instalar e iniciar |
| --- | --- |
| Windows PowerShell ou CMD | `.\setup.cmd` |
| Git Bash, Linux ou macOS | `bash setup.sh` |
| Qualquer sistema com Python 3.12+ no PATH | `python scripts/setup.py` |
| Windows com Python Launcher | `py -3.12 scripts/setup.py` |

O setup cria/reutiliza `.venv`, instala o projeto e suas dependências, verifica `pip check` e
imports e inicia `standalone_app.py`. Abra **http://127.0.0.1:8501**; encerre com **Ctrl+C**.
A instalação fica isolada do Python global. O servidor fica vinculado ao loopback local.

O padrão é **demo + SQLite**. Runbooks, histórico e fixtures ficam em `flowops.db`, na raiz do
checkout, mesmo se o setup for invocado de outro diretório. A aplicação cria o banco e aplica
suas migrations existentes ao iniciar; o setup não remove bancos nem reinicializa fixtures.
`FLOWOPS_DATABASE_URL`, se definida, tem precedência e direciona a aplicação para PostgreSQL.

No modo `--local`, o catálogo de runbooks usa DynamoDB on-demand no Moto Server e cria a tabela
sob demanda. Uma falha temporária sincroniza uma cópia limitada no `localStorage` por conta e
usuário; esse fallback não substitui o Repository/PostgreSQL, que continua guardando execução,
aprovação e auditoria.

## Opções

Todos os atalhos encaminham os mesmos argumentos para `scripts/setup.py`:

```bash
python scripts/setup.py --install-only
python scripts/setup.py --run-only
python scripts/setup.py --dev --postgres --install-only
python scripts/setup.py --run-only --port 8502 --no-browser
python scripts/setup.py --venv "../ambiente flowops"
python scripts/setup.py --help
```

- Sem opções: instala e inicia; repetir reutiliza o ambiente e satisfaz as dependências sem
  solicitar upgrade global ou apagar dados.
- `--install-only`: instala sem iniciar Streamlit ou abrir o banco.
- `--run-only`: verifica o ambiente existente e inicia sem instalar pacotes; se ainda não foi
  preparado, informa o erro. Não combine com opções de instalação `--dev`/`--postgres`.
- `--dev`: adiciona ferramentas de testes, lint, tipos, auditoria e build. Os binários de
  navegador do Playwright continuam sendo instalados separadamente, conforme [Testes](TESTING.md).
- `--postgres`: adiciona o driver; também é instalado automaticamente quando
  `FLOWOPS_DATABASE_URL` está definida durante a instalação. O setup não provisiona um servidor
  PostgreSQL. Para configuração do banco, consulte [Operações](OPERATIONS.md).
- `--venv`: ambiente alternativo. Caminhos relativos são resolvidos a partir do terminal; use
  o mesmo caminho em execuções posteriores. Um diretório ocupado que não seja ambiente virtual
  é recusado, sem apagar seu conteúdo.
- `--app`: bootstrap Streamlit alternativo, por exemplo a aplicação host já integrada com AWS.
  O caminho deve existir. O diretório de trabalho da aplicação continua sendo a raiz deste repo.

Em ambiente Python incompleto ou incompatível, escolha outro `--venv` com Python 3.12+.
Em Debian/Ubuntu, a instalação do Python pode exigir também o pacote `python3.12-venv` da
distribuição. Falhas de pip/proxy/certificado encerram o setup com código diferente de zero,
preservando os arquivos; corrija o acesso ao índice configurado e execute novamente.

## Docker e LocalStack

| Cenário | Docker necessário para FlowOps? | Backend |
| --- | --- | --- |
| Avaliar a app localmente | Não | DemoBackend + SQLite |
| Operar recursos reais AWS | Não | BotoBackend + APIs oficiais AWS |
| Usar PostgreSQL externo | Não; container é uma opção de provisionamento | PostgreSQL configurado pelo host |
| Emular AWS com LocalStack | Integração ainda não implementada | Exigiria um modo específico e testes próprios |

**FlowOps não usa LocalStack atualmente.** DemoBackend é uma implementação interna com dados
determinísticos; não é um servidor que emula todas as APIs AWS. Os testes AWS usam fakes/Stubber;
a CI usa PostgreSQL em container e Chromium real, sem LocalStack.

O caminho de instalação documentado pelo LocalStack usa Docker em funcionamento (Docker
Desktop não é a única forma de disponibilizar o engine). Consulte a
[instalação oficial](https://docs.localstack.cloud/aws/getting-started/installation/) para seus
requisitos atuais de runtime e autenticação.

O provider FlowOps configura `ignore_configured_endpoint_urls=True` em STS e nos clientes de
serviço. Portanto, definir `AWS_ENDPOINT_URL=http://localhost:4566` **não conecta a app ao
LocalStack**. Um futuro modo emulador precisa separar endpoints e credenciais de teste sem
remover essa proteção do modo AWS real.

## Como a integração AWS funciona

O `standalone_app.py` entregue é um bootstrap **demo**, com identidade demo estática. Definir
somente `AWS_PROFILE` não troca seu modo. Para AWS real, use a fronteira pública no Streamlit
host conforme [Integração](INTEGRATION.md):

```python
from flowops.domain.models import AWSContext
from flowops.streamlit import FlowOpsPage

context = AWSContext(
    mode="aws",
    environment="dev",
    account_id="123456789012",  # conta esperada, configurada no servidor
    region="sa-east-1",
    profile="flowops-dev",
)
FlowOpsPage(user=identity_from_authenticated_host, aws_context=context).render()
```

`identity_from_authenticated_host` deve ser a identidade real construída pelo host; o trecho
acima não implementa autenticação. Para iniciar esse bootstrap já existente pelo setup:

```bash
python scripts/setup.py --app caminho/host_app.py
```

Se sua organização usa IAM Identity Center, configure e autentique um profile com AWS CLI v2
(instalado separadamente):

```bash
aws configure sso --profile flowops-dev
aws sso login --profile flowops-dev
aws sts get-caller-identity --profile flowops-dev
```

O backend cria uma sessão boto3 com o profile/região, assume a role opcionalmente configurada
em `AWSContext.role_arn`, confere a conta com STS `GetCallerIdentity` e chama o cliente de
DynamoDB/SQS/SNS/Lambda/S3 conforme cada Action. Sem profile explícito, usa a provider chain
da plataforma. Permissões IAM e conectividade de rede continuam necessárias.

Credenciais não ficam em runbooks nem são criadas pelo setup. O motor reaplica RBAC, escopo,
limites e aprovações antes das operações. `dry_run=True` impede mutações; no backend AWS,
leituras ainda podem consultar os recursos reais. Para simular sem chamadas AWS, use demo.

Referências: [credenciais boto3](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html),
[configuração botocore](https://docs.aws.amazon.com/botocore/latest/reference/config.html),
[IAM do projeto](IAM.md) e [Segurança](SECURITY.md).

## Validação e impacto

`tests/test_setup.py` verifica isolamento/reutilização do venv, preservação de arquivos,
interrupção após falha de instalação e argumentos inválidos. A CI executa instalação real e
reutilização pelos atalhos em Linux/Windows, com espaços nos caminhos e outro diretório de
trabalho, renderiza o bootstrap por AppTest e inicia o servidor pelo `--run-only` até HTTP 200.
macOS compartilha o launcher Bash/Python, mas não tem um runner específico nesta matriz.

Para repetir esse smoke com acesso ao índice de pacotes:

```bash
FLOWOPS_TEST_SETUP=1 python -m unittest tests.test_setup -v
```

No PowerShell, defina primeiro `$env:FLOWOPS_TEST_SETUP="1"` e depois execute o comando Python.
Essa mudança adiciona somente setup, documentação e validação; não altera APIs, schema do
banco, credenciais ou políticas AWS. O procedimento manual do README permanece válido para
rollback do launcher, sem modificar os dados persistidos.
