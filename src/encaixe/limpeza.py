"""Limpeza diária: anonimiza dados pessoais vencidos e apaga o que não serve mais."""

from datetime import datetime, timedelta

import psycopg

RETENCAO_CLIENTE_DIAS = 90  # nome, WhatsApp e e-mail do cliente, depois do horário
RETENCAO_ESPERA_DIAS = 7  # lista de espera, depois do dia desejado
RETENCAO_CLIQUES_DIAS = 400  # contagem de aberturas (já sem dado pessoal)


def executar(conn: psycopg.Connection, agora: datetime) -> dict[str, int]:
    """Roda no contexto `sistema`. Idempotente: rodar duas vezes seguidas não muda nada."""
    anonimizadas = conn.execute(
        "update reservas set cliente_nome = 'Cliente removido', cliente_whatsapp = null,"
        " cliente_email = null, anonimizada_em = %s"
        " where anonimizada_em is null and fim < %s",
        (agora, agora - timedelta(days=RETENCAO_CLIENTE_DIAS)),
    ).rowcount
    espera = conn.execute(
        "delete from espera where dia < %s",
        ((agora - timedelta(days=RETENCAO_ESPERA_DIAS)).date(),),
    ).rowcount
    sessoes = conn.execute("delete from sessoes where expira_em < %s", (agora,)).rowcount
    cliques = conn.execute(
        "delete from cliques_dia where dia < %s",
        ((agora - timedelta(days=RETENCAO_CLIQUES_DIAS)).date(),),
    ).rowcount
    return {
        "reservas_anonimizadas": anonimizadas,
        "espera_apagada": espera,
        "sessoes_apagadas": sessoes,
        "cliques_apagados": cliques,
    }
