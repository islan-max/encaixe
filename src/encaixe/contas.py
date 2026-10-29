"""Contas, sessões e códigos de recuperação. Tudo roda no contexto `sistema`."""

import hashlib
import secrets
from datetime import timedelta

import psycopg

SESSAO_DURA = timedelta(days=30)
QTD_CODIGOS = 8
_ALFABETO = "23456789abcdefghjkmnpqrstuvwxyz"  # sem 0/o, 1/l/i: ninguém erra ao copiar do papel


def _hash(texto: str) -> bytes:
    # Tokens e códigos têm entropia alta e vida curta: SHA-256 basta (não é senha).
    return hashlib.sha256(texto.encode()).digest()


def criar_conta_senha(conn: psycopg.Connection, email: str, senha_hash: str) -> str | None:
    """Id da conta nova, ou None se o e-mail já tem conta."""
    linha = conn.execute(
        "insert into contas (email, senha_hash) values (%s, %s)"
        " on conflict (email) do nothing returning id",
        (email, senha_hash),
    ).fetchone()
    return str(linha["id"]) if linha else None


def conta_por_email(conn: psycopg.Connection, email: str) -> dict | None:
    return conn.execute("select * from contas where email = %s", (email,)).fetchone()


def conta_google(conn: psycopg.Connection, sub: str, email: str | None) -> dict:
    """A conta do Google com este `sub`, criando na primeira vez. O e-mail é só para exibir."""
    conn.execute(
        "insert into contas (google_sub, google_email) values (%s, %s)"
        " on conflict (google_sub) do nothing",
        (sub, email),
    )
    return conn.execute("select * from contas where google_sub = %s", (sub,)).fetchone()


# --- sessões ---------------------------------------------------------------------------------


def criar_sessao(conn: psycopg.Connection, conta_id: str) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute(
        "insert into sessoes (token_hash, conta_id, expira_em) values (%s, %s, now() + %s)",
        (_hash(token), conta_id, SESSAO_DURA),
    )
    return token


def conta_da_sessao(conn: psycopg.Connection, token: str | None) -> dict | None:
    if not token:
        return None
    return conn.execute(
        "select c.id, c.email, c.google_email, c.google_sub is not null as por_google,"
        " c.profissional_id from sessoes s join contas c on c.id = s.conta_id"
        " where s.token_hash = %s and s.expira_em > now()",
        (_hash(token),),
    ).fetchone()


def encerrar_sessao(conn: psycopg.Connection, token: str | None) -> None:
    if token:
        conn.execute("delete from sessoes where token_hash = %s", (_hash(token),))


def encerrar_todas_as_sessoes(conn: psycopg.Connection, conta_id: str) -> None:
    conn.execute("delete from sessoes where conta_id = %s", (conta_id,))


# --- códigos de recuperação --------------------------------------------------------------------


def _normalizar_codigo(texto: str) -> str:
    return "".join(c for c in texto.lower() if c.isalnum())


def gerar_codigos(conn: psycopg.Connection, conta_id: str) -> list[str]:
    """Troca os códigos da conta por 8 novos e devolve os textos (a única vez em que existem)."""
    conn.execute("delete from codigos_recuperacao where conta_id = %s", (conta_id,))
    codigos = []
    for _ in range(QTD_CODIGOS):
        bruto = "".join(secrets.choice(_ALFABETO) for _ in range(10))
        conn.execute(
            "insert into codigos_recuperacao (conta_id, codigo_hash) values (%s, %s)",
            (conta_id, _hash(bruto)),
        )
        codigos.append(f"{bruto[:5]}-{bruto[5:]}")
    return codigos


def usar_codigo(conn: psycopg.Connection, conta_id: str, codigo: str) -> bool:
    """Gasta o código se for válido e ainda não usado. Atômico: dois usos simultâneos, um vence."""
    linha = conn.execute(
        "update codigos_recuperacao set usado_em = now()"
        " where conta_id = %s and codigo_hash = %s and usado_em is null returning 1 as ok",
        (conta_id, _hash(_normalizar_codigo(codigo))),
    ).fetchone()
    return linha is not None


def codigos_restantes(conn: psycopg.Connection, conta_id: str) -> int:
    return conn.execute(
        "select count(*) as n from codigos_recuperacao where conta_id = %s and usado_em is null",
        (conta_id,),
    ).fetchone()["n"]


def trocar_senha(conn: psycopg.Connection, conta_id: str, senha_hash: str) -> None:
    """Nova senha. Derruba todas as sessões: quem tinha a senha antiga sai."""
    conn.execute("update contas set senha_hash = %s where id = %s", (senha_hash, conta_id))
    encerrar_todas_as_sessoes(conn, conta_id)
