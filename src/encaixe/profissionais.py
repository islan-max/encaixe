"""Criar o perfil de um profissional: página, serviços e horários de exemplo, numa transação."""

import psycopg

from encaixe.categorias import CATEGORIAS, HORARIO_PADRAO
from encaixe.divulgacao import ORIGENS_INICIAIS, criar_origem


class SlugEmUso(Exception):
    pass


def excluir_perfil(conn: psycopg.Connection, profissional_id: str) -> None:
    """Apaga o profissional e tudo que é dele, inclusive as reservas com os dados dos clientes.

    Roda no contexto `sistema`. As reservas saem primeiro (referenciam serviços e origens); o resto
    cai em cascata a partir do profissional, e a conta vai junto (com sessões e códigos).
    """
    conn.execute("delete from reservas where profissional_id = %s", (profissional_id,))
    conn.execute("delete from profissionais where id = %s", (profissional_id,))


def criar_perfil(
    conn: psycopg.Connection, conta_id: str, nome: str, slug: str, whatsapp: str, categoria: str
) -> str:
    """Roda no contexto `sistema`. Devolve o id do profissional."""
    cat = CATEGORIAS[categoria]
    try:
        with conn.transaction():
            pro = conn.execute(
                "insert into profissionais (slug, nome, categoria, whatsapp, lembrete_discreto)"
                " values (%s, %s, %s, %s, %s) returning id",
                (slug, nome, categoria, whatsapp, cat.discreto),
            ).fetchone()["id"]
    except psycopg.errors.UniqueViolation:
        raise SlugEmUso from None
    for ordem, (rotulo, duracao, folga, vagas) in enumerate(cat.servicos):
        conn.execute(
            "insert into servicos (profissional_id, nome, duracao_min, folga_min, vagas, ordem)"
            " values (%s, %s, %s, %s, %s, %s)",
            (pro, rotulo, duracao, folga, vagas, ordem),
        )
    for dia, faixas in HORARIO_PADRAO.items():
        for inicio, fim in faixas:
            conn.execute(
                "insert into horarios_semanais (profissional_id, dia_semana, inicio, fim)"
                " values (%s, %s, %s, %s)",
                (pro, dia, inicio, fim),
            )
    for nome_da_origem in ORIGENS_INICIAIS:
        criar_origem(conn, str(pro), nome_da_origem)
    conn.execute("update contas set profissional_id = %s where id = %s", (pro, conta_id))
    return str(pro)
