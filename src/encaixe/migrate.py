from importlib import resources

import psycopg

from encaixe.db import sistema

# Chave arbitrária do advisory lock: serializa migrações concorrentes (dois processos subindo).
_CHAVE = 8_421_005


def migrar(conn: psycopg.Connection) -> list[str]:
    """Aplica as migrações que faltam, em ordem. Devolve os nomes aplicados agora."""
    conn.execute("select pg_advisory_xact_lock(%s)", (_CHAVE,))
    conn.execute(
        "create table if not exists schema_migrations ("
        "name text primary key, applied_at timestamptz not null default now())"
    )
    feitas = {r["name"] for r in conn.execute("select name from schema_migrations")}
    arquivos = sorted((resources.files("encaixe") / "migrations").iterdir(), key=lambda p: p.name)
    novas = []
    for arquivo in arquivos:
        if arquivo.name.endswith(".sql") and arquivo.name not in feitas:
            conn.execute(arquivo.read_text(encoding="utf-8"))
            conn.execute("insert into schema_migrations (name) values (%s)", (arquivo.name,))
            novas.append(arquivo.name)
    return novas


if __name__ == "__main__":
    with sistema() as c:
        for nome in migrar(c):
            print("aplicada:", nome)
