"""Monta o que a página mostra a partir do banco: regras do profissional, dias e horários livres."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import psycopg

from encaixe.horarios import Horario, Intervalo, Ocupada, Regras, Servico, horarios_do_dia

DIAS_POR_PAGINA = 14


@dataclass(frozen=True)
class DiaLivre:
    dia: date
    livres: int  # horários que dá para marcar
    cheios: int  # horários de aula sem vaga (admitem lista de espera)
    vagas: int  # soma das vagas livres (só faz diferença em aula)


def regras_do_profissional(conn: psycopg.Connection, perfil: dict) -> Regras:
    semana: dict[int, list[tuple[time, time]]] = {}
    for h in conn.execute(
        "select dia_semana, inicio, fim from horarios_semanais order by dia_semana, inicio"
    ):
        semana.setdefault(h["dia_semana"], []).append((h["inicio"], h["fim"]))
    return Regras(
        fuso=perfil["fuso"],
        passo_min=perfil["passo_min"],
        antecedencia_min=perfil["antecedencia_min"],
        dias_a_frente=perfil["dias_a_frente"],
        cancelar_ate_min=perfil["cancelar_ate_min"],
        semana={d: tuple(f) for d, f in semana.items()},
    )


def servico_de(linha: dict) -> Servico:
    return Servico(
        id=str(linha["id"]),
        duracao_min=linha["duracao_min"],
        folga_min=linha["folga_min"],
        vagas=linha["vagas"],
    )


def ocupacoes(
    conn: psycopg.Connection, de: datetime, ate: datetime
) -> tuple[list[Ocupada], list[Intervalo]]:
    """O que já ocupa a agenda entre `de` e `ate`, sem nenhum dado pessoal (views públicas)."""
    ocupadas = [
        Ocupada(str(o["servico_id"]), o["inicio"], o["ocupa_ate"])
        for o in conn.execute(
            "select servico_id, inicio, ocupa_ate from ocupacoes_publicas"
            " where inicio < %s and ocupa_ate > %s",
            (ate, de),
        )
    ]
    bloqueios = [
        Intervalo(b["inicio"], b["fim"])
        for b in conn.execute(
            "select inicio, fim from bloqueios_publicos where inicio < %s and fim > %s", (ate, de)
        )
    ]
    return ocupadas, bloqueios


def limites_do_dia(regras: Regras, dia: date) -> tuple[datetime, datetime]:
    return limites_no_fuso(regras.tz, dia)


def limites_no_fuso(tz: ZoneInfo, dia: date) -> tuple[datetime, datetime]:
    """Do começo ao fim do dia `dia` no relógio de `tz`, em UTC."""
    inicio = datetime.combine(dia, time(0), tzinfo=tz).astimezone(UTC)
    fim = datetime.combine(dia + timedelta(days=1), time(0), tzinfo=tz).astimezone(UTC)
    return inicio, fim


def _sem(ocupadas: list[Ocupada], ignorar: Ocupada | None) -> list[Ocupada]:
    """Tira a reserva que está sendo trocada: ela não pode atrapalhar o próprio horário novo."""
    if ignorar is None or ignorar not in ocupadas:
        return ocupadas
    sobra = list(ocupadas)
    sobra.remove(ignorar)
    return sobra


def horarios_no_dia(
    conn: psycopg.Connection,
    regras: Regras,
    servico: Servico,
    dia: date,
    agora: datetime,
    ignorar: Ocupada | None = None,
) -> list[Horario]:
    inicio, fim = limites_do_dia(regras, dia)
    # Folga e duração podem entrar no dia seguinte: busca com sobra.
    ocupadas, bloqueios = ocupacoes(conn, inicio - timedelta(hours=12), fim + timedelta(hours=12))
    return horarios_do_dia(regras, servico, dia, agora, _sem(ocupadas, ignorar), bloqueios)


def dias_livres(
    conn: psycopg.Connection,
    regras: Regras,
    servico: Servico,
    agora: datetime,
    pagina: int,
    ignorar: Ocupada | None = None,
) -> tuple[list[DiaLivre], bool]:
    """Os dias com algo a oferecer, `DIAS_POR_PAGINA` dias de calendário por página.

    Devolve (dias, tem_mais). Dia fechado ou sem nada livre nem cheio não aparece.
    """
    hoje = agora.astimezone(regras.tz).date()
    primeiro = hoje + timedelta(days=pagina * DIAS_POR_PAGINA)
    ultimo_do_horizonte = hoje + timedelta(days=regras.dias_a_frente)
    ultimo = min(primeiro + timedelta(days=DIAS_POR_PAGINA - 1), ultimo_do_horizonte)
    if primeiro > ultimo_do_horizonte:
        return [], False
    de, _ = limites_do_dia(regras, primeiro)
    _, ate = limites_do_dia(regras, ultimo)
    ocupadas, bloqueios = ocupacoes(conn, de - timedelta(hours=12), ate + timedelta(hours=12))
    ocupadas = _sem(ocupadas, ignorar)
    achados = []
    dia = primeiro
    while dia <= ultimo:
        horarios = horarios_do_dia(regras, servico, dia, agora, ocupadas, bloqueios)
        livres = [h for h in horarios if h.reservavel]
        cheios = [h for h in horarios if h.motivo == "lotado"]
        if livres or cheios:
            achados.append(
                DiaLivre(dia, len(livres), len(cheios), sum(h.vagas_livres for h in livres))
            )
        dia += timedelta(days=1)
    return achados, ultimo < ultimo_do_horizonte
