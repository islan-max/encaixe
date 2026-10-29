"""Conexões com o Postgres.

Quem conecta é o dono do banco, e o dono ignora o RLS. Por isso cada requisição que fala em nome
de alguém troca de papel (`set local role`) e diz quem é (`set_config(..., true)`, que vale só até
o fim da transação). Os três jeitos de conectar estão no cabeçalho de `migrations/001_agenda.sql`.
"""

import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None


def _pool_aberto() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            os.environ["DATABASE_URL"],
            min_size=0,  # o Neon suspende o banco ocioso e derruba as conexões
            max_size=int(os.environ.get("DB_POOL_MAX", "5")),
            max_idle=240,
            timeout=15,  # espera por uma conexão (o Neon pode estar acordando)
            check=ConnectionPool.check_connection,
            # prepare_threshold=None: o pooler do Neon (PgBouncer em modo transação) troca de
            # conexão a cada transação, e comando preparado não sobrevive a isso.
            kwargs={"row_factory": dict_row, "prepare_threshold": None, "connect_timeout": 10},
            open=True,
        )
    return _pool


def fechar_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def sistema() -> Iterator[psycopg.Connection]:
    """Como dono do banco (ignora o RLS): cadastro, login, limpeza diária. Uma transação."""
    with _pool_aberto().connection() as conn:
        yield conn


@contextmanager
def painel(profissional_id: str) -> Iterator[psycopg.Connection]:
    """Profissional logado: só enxerga o que é dele. Uma transação."""
    with _pool_aberto().connection() as conn:
        conn.execute("set local role encaixe_painel")
        conn.execute(
            "select set_config('encaixe.profissional_id', %s, true)", (str(profissional_id),)
        )
        yield conn


def hash_do_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@contextmanager
def publico(profissional_id: str, token: str | None = None) -> Iterator[psycopg.Connection]:
    """Página pública de um profissional. Com `token`, enxerga também a reserva dona dele."""
    with _pool_aberto().connection() as conn:
        conn.execute("set local role encaixe_publico")
        conn.execute(
            "select set_config('encaixe.profissional_id', %s, true)", (str(profissional_id),)
        )
        if token is not None:
            conn.execute(
                "select set_config('encaixe.token_hash', %s, true)", (hash_do_token(token),)
            )
        yield conn
