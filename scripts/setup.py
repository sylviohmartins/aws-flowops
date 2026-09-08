"""Install and launch FlowOps locally with only Python's standard library."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def port_number(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("A porta deve estar entre 1 e 65535.")
    return port


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Configura o ambiente virtual e inicia o AWS FlowOps Studio em modo demo."
    )
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--install-only", action="store_true", help="Somente instalar/configurar.")
    mode.add_argument("--run-only", action="store_true", help="Executar sem instalar pacotes.")
    result.add_argument(
        "--dev", action="store_true", help="Instalar ferramentas de desenvolvimento."
    )
    result.add_argument("--postgres", action="store_true", help="Instalar o driver PostgreSQL.")
    result.add_argument(
        "--local",
        action="store_true",
        help="Iniciar laboratorio AWS em Docker, dados ficticios e PostgreSQL.",
    )
    result.add_argument(
        "--stop-local",
        action="store_true",
        help="Parar containers locais preservando o volume PostgreSQL.",
    )
    result.add_argument(
        "--venv", type=Path, default=ROOT / ".venv", help="Diretorio do ambiente virtual."
    )
    result.add_argument(
        "--port", type=port_number, default=8501, help="Porta local (padrao: 8501)."
    )
    result.add_argument("--no-browser", action="store_true", help="Nao abrir o navegador.")
    result.add_argument(
        "--app",
        type=Path,
        default=None,
        help="Bootstrap Streamlit alternativo.",
    )
    return result


def local_services(*, stop: bool = False) -> None:
    print("Verificando Docker e Compose v2...", flush=True)
    subprocess.run(["docker", "info"], check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
    compose = ["docker", "compose", "-f", str(ROOT / "compose.local.yml")]
    subprocess.run([*compose, "version"], check=True, cwd=ROOT)
    if stop:
        subprocess.run([*compose, "stop"], check=True, cwd=ROOT)
        print(
            "Containers parados. Dados AWS emulados serao recriados no proximo inicio; PostgreSQL preservado.",
            flush=True,
        )
        return
    print("Baixando runtime da Lambda (primeira execucao pode demorar)...", flush=True)
    subprocess.run(
        ["docker", "pull", "ghcr.io/shogo82148/lambda-python:3.12"],
        check=True,
        cwd=ROOT,
    )
    subprocess.run([*compose, "up", "-d", "--wait", "--wait-timeout", "120"], check=True, cwd=ROOT)


def prepare_environment(directory: Path, *, install: bool) -> Path:
    python = directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not (directory / "pyvenv.cfg").is_file():
        if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
            raise ValueError("Destino ocupado e sem pyvenv.cfg. Escolha outro caminho com --venv.")
        if not install:
            raise ValueError("Ambiente virtual ausente. Execute o setup sem --run-only primeiro.")
        print(f"Criando ambiente virtual: {directory}", flush=True)
        venv.EnvBuilder(with_pip=True).create(directory)
    if not python.is_file():
        raise ValueError("Ambiente virtual incompleto. Escolha outro caminho com --venv.")
    subprocess.run(
        [
            str(python),
            "-c",
            "import sys; sys.exit(0 if sys.version_info >= (3, 12) "
            "and sys.prefix != sys.base_prefix else "
            "'O ambiente deve usar Python 3.12+ isolado. Escolha outro caminho com --venv.')",
        ],
        check=True,
        cwd=ROOT,
    )
    return python


def main(argv: list[str] | None = None) -> int:
    cli = parser()
    args = cli.parse_args(argv)
    # Unlike installed package code, this bootstrap runs before requires-python is enforced.
    if sys.version_info < (3, 12):  # noqa: UP036
        cli.error("Instale Python 3.12+ e execute novamente com esse interpretador.")
    if args.run_only and (args.dev or args.postgres):
        cli.error("--dev e --postgres sao opcoes de instalacao; remova --run-only.")
    if args.local and args.app:
        cli.error("--local usa local_app.py; nao combine com --app.")
    app = (
        (args.app or ROOT / ("local_app.py" if args.local else "standalone_app.py"))
        .expanduser()
        .resolve()
    )
    if not app.is_file() or app.suffix != ".py":
        cli.error("--app deve apontar para um arquivo Python existente.")
    try:
        if args.stop_local:
            local_services(stop=True)
            return 0
        if args.local:
            local_services()
        python = prepare_environment(args.venv.expanduser().resolve(), install=not args.run_only)
        if not args.run_only:
            extras = []
            if args.dev:
                extras.append("dev")
            if args.local or args.postgres or os.getenv("FLOWOPS_DATABASE_URL"):
                extras.append("postgres")
            target = str(ROOT) + (f"[{','.join(extras)}]" if extras else "")
            print("Instalando dependencias do projeto...", flush=True)
            subprocess.run(
                [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-e", target],
                check=True,
                cwd=ROOT,
            )
        subprocess.run([str(python), "-m", "pip", "check"], check=True, cwd=ROOT)
        subprocess.run(
            [
                str(python),
                "-c",
                "from importlib.metadata import version; version('aws-flowops'); "
                "import streamlit, streamlit_flow, boto3, flowops",
            ],
            check=True,
            cwd=ROOT,
        )
        if args.local:
            print(
                "Criando recursos e fluxos ausentes, preservando alteracoes existentes...",
                flush=True,
            )
            subprocess.run([str(python), "-m", "flowops.providers.aws.lab"], check=True, cwd=ROOT)
        if args.install_only:
            suffix = " --local" if args.local else ""
            print(
                f"Setup concluido. Para iniciar: execute este script com --run-only{suffix}.",
                flush=True,
            )
            return 0
        print(
            f"Iniciando {app.name}: http://127.0.0.1:{args.port} (Ctrl+C para encerrar).",
            flush=True,
        )
        subprocess.run(
            [
                str(python),
                "-m",
                "streamlit",
                "run",
                str(app),
                "--server.address=127.0.0.1",
                f"--server.port={args.port}",
                f"--server.headless={'true' if args.no_browser else 'false'}",
                "--browser.gatherUsageStats=false",
            ],
            check=True,
            cwd=ROOT,
        )
        return 0
    except KeyboardInterrupt:
        return 130
    except subprocess.CalledProcessError as error:
        print(
            "Setup/execucao interrompido: um comando falhou. Consulte o erro acima; "
            "o ambiente e os dados foram preservados.",
            file=sys.stderr,
        )
        return error.returncode if error.returncode > 0 else 1
    except (OSError, ValueError) as error:
        print(f"Setup nao concluido: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
