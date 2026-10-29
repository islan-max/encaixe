"""Peças comuns das páginas: modelos, cookie de sessão, usuário logado e CSRF."""

from pathlib import Path

import psycopg
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from encaixe import datas, formularios, telefone
from encaixe.assinatura import csrf_confere, token_csrf
from encaixe.config import carregar
from encaixe.contas import conta_da_sessao
from encaixe.db import sistema

PASTA = Path(__file__).parent
modelos = Jinja2Templates(directory=PASTA / "templates")
modelos.env.globals.update(
    data_longa=datas.data_longa,
    data_curta=datas.data_curta,
    hora_curta=datas.hora_curta,
    data_e_hora=datas.data_e_hora,
    dia_da_semana=datas.dia_da_semana,
    dinheiro=formularios.formatar_dinheiro,
    telefone=telefone.formatar,
)


def nome_do_cookie() -> str:
    # `__Host-` obriga Secure, Path=/ e nenhum Domain: o cookie não vaza para subdomínios.
    return "__Host-sessao" if carregar().cookie_seguro else "sessao"


def definir_cookie_sessao(resposta: Response, token: str) -> None:
    resposta.set_cookie(
        nome_do_cookie(),
        token,
        max_age=30 * 24 * 3600,
        httponly=True,
        secure=carregar().cookie_seguro,
        samesite="lax",
        path="/",
    )


def apagar_cookie_sessao(resposta: Response) -> None:
    resposta.delete_cookie(
        nome_do_cookie(), path="/", secure=carregar().cookie_seguro, httponly=True, samesite="lax"
    )


def usuario_atual(request: Request) -> dict | None:
    """A conta da sessão, ou None. Guarda o resultado na requisição (uma consulta só)."""
    if not hasattr(request.state, "usuario"):
        token = request.cookies.get(nome_do_cookie())
        request.state.usuario = None
        if token:  # sem cookie não há o que consultar (e a página abre mesmo com o banco fora)
            try:
                with sistema() as conn:
                    request.state.usuario = conta_da_sessao(conn, token)
            except psycopg.OperationalError:
                request.state.usuario = None
        request.state.sessao_token = token if request.state.usuario else None
    return request.state.usuario


class PrecisaEntrar(Exception):
    pass


def exigir_usuario(request: Request) -> dict:
    usuario = usuario_atual(request)
    if usuario is None:
        raise PrecisaEntrar
    return usuario


def checar_csrf(request: Request, recebido: str) -> None:
    token = getattr(request.state, "sessao_token", None)
    if not token or not csrf_confere(token, recebido):
        raise HTTPException(403, "Formulário vencido. Volte e tente de novo.")


def pagina(request: Request, nome: str, status: int = 200, **contexto) -> HTMLResponse:
    usuario = usuario_atual(request)
    token = getattr(request.state, "sessao_token", None)
    contexto.setdefault("usuario", usuario)
    contexto.setdefault("csrf", token_csrf(token) if token else "")
    return modelos.TemplateResponse(request, nome, contexto, status_code=status)


def ir_para(destino: str) -> RedirectResponse:
    return RedirectResponse(destino, status_code=303)
