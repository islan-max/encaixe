"""Criar reserva. Quem decide se cabe é o gatilho do banco; aqui só se traduz a recusa."""

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime

import psycopg

from encaixe.config import carregar
from encaixe.db import hash_do_token


class ReservaRecusada(Exception):
    """O banco recusou: `motivo` é ocupado, lotado, bloqueado ou servico_invalido."""

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


_MOTIVOS = {
    "EN001": "ocupado",
    "EN002": "lotado",
    "EN003": "bloqueado",
    "EN004": "servico_invalido",
}


def novo_token() -> str:
    """Um token aleatório de 192 bits (usado em testes; as reservas de verdade usam o derivado)."""
    return secrets.token_urlsafe(24)


def token_da_reserva(reserva_id: str) -> str:
    """O link secreto da reserva, derivado do id com HMAC (192 bits).

    O banco guarda só o hash. Derivar em vez de sortear deixa o profissional montar o link no
    lembrete sem que ele precise ficar salvo; quem vê só o banco não consegue calcular os links.
    Trocar a SECRET_KEY invalida os links já enviados.
    """
    mac = hmac.new(
        carregar().secret_key.encode(), f"reserva:{reserva_id}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(mac[:24]).decode()


def criar(
    conn: psycopg.Connection,
    *,
    profissional_id: str,
    servico_id: str,
    inicio: datetime,
    cliente_nome: str,
    cliente_whatsapp: str,
    cliente_email: str | None,
    token: str,
    origem_id: str | None = None,
    id: str | None = None,
) -> dict:
    """Insere a reserva. Nunca recebe estado, fim nem duração: o gatilho calcula."""
    try:
        with conn.transaction():  # ponto de salvamento: quem chamou pode seguir após a recusa
            # Sem o token no contexto, o RLS não deixa o papel público ler de volta a própria linha.
            conn.execute(
                "select set_config('encaixe.token_hash', %s, true)", (hash_do_token(token),)
            )
            return conn.execute(
                "insert into reservas (id, profissional_id, servico_id, inicio, cliente_nome,"
                " cliente_whatsapp, cliente_email, token_hash, origem_id)"
                " values (%s, %s, %s, %s, %s, %s, %s, decode(%s, 'hex'), %s)"
                " returning id, inicio, fim",
                (
                    id or str(uuid.uuid4()),
                    profissional_id,
                    servico_id,
                    inicio,
                    cliente_nome,
                    cliente_whatsapp,
                    cliente_email,
                    hash_do_token(token),
                    origem_id,
                ),
            ).fetchone()
    except psycopg.DatabaseError as erro:
        if erro.sqlstate in _MOTIVOS:
            raise ReservaRecusada(_MOTIVOS[erro.sqlstate]) from None
        raise
