"""Sobe o Encaixe na sua máquina com um Postgres embutido (pgserver), sem instalar nada.

    uv run python scripts/dev.py            # http://localhost:8000, banco vazio
    uv run python scripts/dev.py --manter   # reaproveita os dados da última vez

Os dados ficam em `.dev-db/` (ignorado pelo Git). Com `DATABASE_URL` definida, usa esse banco.
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def main() -> None:
    args = argparse.ArgumentParser()
    args.add_argument("--porta", type=int, default=8000)
    args.add_argument("--manter", action="store_true", help="não apaga o banco local ao subir")
    opcoes = args.parse_args()

    if not os.environ.get("DATABASE_URL"):
        import pgserver

        pasta = RAIZ / ".dev-db"
        if not opcoes.manter and pasta.exists():
            shutil.rmtree(pasta, ignore_errors=True)
        os.environ["DATABASE_URL"] = pgserver.get_server(pasta, cleanup_mode="stop").get_uri()
    os.environ.setdefault("BASE_URL", f"http://localhost:{opcoes.porta}")

    sys.path.insert(0, str(RAIZ / "src"))
    from encaixe.db import sistema
    from encaixe.migrate import migrar

    with sistema() as conn:
        for nome in migrar(conn):
            print("migração aplicada:", nome)

    import uvicorn

    uvicorn.run("encaixe.app:app", port=opcoes.porta, reload=False)


if __name__ == "__main__":
    main()
