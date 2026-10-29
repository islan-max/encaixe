"""Textos que o profissional manda pelo WhatsApp. O Encaixe só monta: quem envia é ele."""

from datetime import datetime
from zoneinfo import ZoneInfo

from encaixe.datas import data_longa, hora_curta


def primeiro_nome(nome: str) -> str:
    partes = nome.split()
    return partes[0] if partes else nome


def preencher(modelo: str, **valores: str) -> str:
    """Troca {ficha} por valor. Ficha que não conhecemos fica como está (o perfil já recusa)."""
    for ficha, valor in valores.items():
        modelo = modelo.replace("{" + ficha + "}", valor)
    return modelo


def lembrete(perfil: dict, reserva: dict, servico_nome: str, tz: ZoneInfo, link: str) -> str:
    inicio: datetime = reserva["inicio"].astimezone(tz)
    return preencher(
        perfil["mensagem_lembrete"],
        nome=primeiro_nome(reserva["cliente_nome"]),
        servico="atendimento" if perfil["lembrete_discreto"] else servico_nome,
        dia=data_longa(inicio.date()),
        hora=hora_curta(inicio, tz),
        link=link,
        profissional=perfil["nome"],
    )


def aviso_de_cancelamento(perfil: dict, reserva: dict, tz: ZoneInfo) -> str:
    inicio = reserva["inicio"].astimezone(tz)
    return (
        f"Oi, {primeiro_nome(reserva['cliente_nome'])}! Preciso cancelar o seu horário de "
        f"{data_longa(inicio.date())} às {hora_curta(inicio, tz)}. Desculpe o transtorno! "
        "Vamos marcar outro?"
    )


def chamada_da_espera(perfil: dict, espera: dict, link_da_pagina: str, tz: ZoneInfo) -> str:
    return (
        f"Oi, {primeiro_nome(espera['nome'])}! Aqui é {perfil['nome']}. Abriu uma vaga em "
        f"{data_longa(espera['dia'])}. Se ainda quiser, marque por aqui: {link_da_pagina}"
    )
