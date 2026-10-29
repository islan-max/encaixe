"""Páginas soltas do site."""

from fastapi import APIRouter, Request

from encaixe.web import pagina

roteador = APIRouter()


@roteador.get("/")
def inicio(request: Request):
    return pagina(request, "inicio.html")
