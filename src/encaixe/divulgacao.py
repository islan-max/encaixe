"""Links curtos de divulgação, QR code e contagem de acessos por origem, sem dados pessoais."""

import io
import re
import secrets
import string
from datetime import date

import psycopg
import segno

ALFABETO = string.ascii_letters + string.digits  # base62, como o encurtador do laboratório
PADRAO_CODIGO = re.compile(r"^[0-9A-Za-z]{7}$")
ORIGENS_INICIAIS = ("Instagram", "WhatsApp", "Cartão e QR code")

# Quem não é gente: pré-visualizadores de link (o WhatsApp busca a página quando alguém cola o
# link numa conversa), robôs de busca e ferramentas. Sem user agent também não conta.
_ROBOS = re.compile(
    r"bot|crawl|spider|preview|facebookexternalhit|whatsapp|telegram|slack|discord|curl|wget"
    r"|python|httpx|headless|monitor|uptime|lighthouse",
    re.IGNORECASE,
)


def parece_robo(user_agent: str | None) -> bool:
    return not user_agent or bool(_ROBOS.search(user_agent))


def novo_codigo() -> str:
    return "".join(secrets.choice(ALFABETO) for _ in range(7))


def criar_origem(conn: psycopg.Connection, profissional_id: str, nome: str) -> str:
    """Cria a origem com um código curto livre. Funciona em `sistema` e em `painel`."""
    for _ in range(10):
        try:
            with conn.transaction():
                return str(
                    conn.execute(
                        "insert into origens (profissional_id, nome, codigo) values (%s, %s, %s)"
                        " returning id",
                        (profissional_id, nome, novo_codigo()),
                    ).fetchone()["id"]
                )
        except psycopg.errors.UniqueViolation:
            continue  # 62^7 combinações: colidir é raro, e tentar de novo resolve
    raise RuntimeError("não foi possível gerar um código livre")


def contar_acesso(conn: psycopg.Connection, origem_id: str, dia: date) -> None:
    conn.execute(
        "insert into cliques_dia (origem_id, dia, n) values (%s, %s, 1)"
        " on conflict (origem_id, dia) do update set n = cliques_dia.n + 1",
        (origem_id, dia),
    )


def qr_inline(url: str, titulo: str) -> str:
    """SVG para a página: escala pelo CSS (tem viewBox) e leva fundo branco, para o tema escuro
    não inverter as cores e atrapalhar a leitura."""
    codigo = segno.make(url, error="q")
    return codigo.svg_inline(
        border=2,
        dark="#000000",
        light="#ffffff",
        omitsize=True,
        title=titulo,
        svgclass=None,
        lineclass=None,
        scale=1,
    )


def qr_arquivo(url: str, formato: str) -> bytes:
    """O QR para baixar e imprimir: SVG (nítido em qualquer tamanho) ou PNG grande."""
    codigo = segno.make(url, error="q")
    saida = io.BytesIO()
    if formato == "svg":
        codigo.save(
            saida, kind="svg", scale=10, border=4, dark="#000000", light="#ffffff", xmldecl=True
        )
    else:
        codigo.save(saida, kind="png", scale=20, border=4, dark="#000000", light="#ffffff")
    return saida.getvalue()
