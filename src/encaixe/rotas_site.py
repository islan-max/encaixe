"""Páginas soltas: início e o painel (que cresce nas próximas fatias)."""

from fastapi import APIRouter, Request

from encaixe import contas
from encaixe.db import sistema
from encaixe.web import exigir_usuario, pagina

roteador = APIRouter()


@roteador.get("/")
def inicio(request: Request):
    return pagina(request, "inicio.html")


@roteador.get("/painel")
def painel(request: Request):
    usuario = exigir_usuario(request)
    restantes = None
    if usuario.get("email"):
        with sistema() as conn:
            restantes = contas.codigos_restantes(conn, usuario["id"])
    return pagina(request, "painel.html", codigos_restantes=restantes)
