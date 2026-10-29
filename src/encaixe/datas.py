"""Datas e horas em português, sem depender do idioma do computador."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

DIAS = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)
MESES = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


def dia_da_semana(d: date) -> str:
    return DIAS[d.weekday()]


def data_longa(d: date) -> str:
    """quinta-feira, 5 de novembro"""
    return f"{DIAS[d.weekday()]}, {d.day} de {MESES[d.month - 1]}"


def data_curta(d: date) -> str:
    return f"{d.day:02d}/{d.month:02d}"


def hora_curta(momento: datetime, fuso: ZoneInfo) -> str:
    local = momento.astimezone(fuso)
    return f"{local.hour:02d}:{local.minute:02d}"


def data_e_hora(momento: datetime, fuso: ZoneInfo) -> str:
    """qui, 05/11 às 14:30"""
    local = momento.astimezone(fuso)
    return f"{DIAS[local.weekday()][:3]}, {data_curta(local.date())} às {hora_curta(local, fuso)}"
