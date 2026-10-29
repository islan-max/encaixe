import logging

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import PoolTimeout
from starlette.exceptions import HTTPException as ErroHTTP

from encaixe import (
    rotas_agenda,
    rotas_contas,
    rotas_divulgacao,
    rotas_painel,
    rotas_publicas,
    rotas_site,
)
from encaixe.google import ClienteGoogle
from encaixe.seguranca import Seguranca
from encaixe.web import PASTA, PrecisaEntrar, pagina

_TITULOS = {
    403: ("Isso não foi liberado", "Volte e tente de novo. Se continuar, entre outra vez."),
    404: ("Página não encontrada", "O endereço pode ter mudado ou estar escrito diferente."),
    405: ("Isso não funciona assim", "Volte para a página anterior e tente de novo."),
    429: ("Muitas tentativas", "Espere um pouco e tente de novo."),
}


def create_app() -> FastAPI:
    app = FastAPI(title="Encaixe", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.google = ClienteGoogle()
    app.add_middleware(Seguranca)
    app.mount("/static", StaticFiles(directory=PASTA / "static"), name="static")

    @app.api_route("/saude", methods=["GET", "HEAD"])
    def saude() -> dict[str, str]:
        # Sem tocar no banco: serve de ping para manter o Render acordado sem gastar o Neon.
        return {"estado": "ok"}

    app.include_router(rotas_site.roteador)
    app.include_router(rotas_contas.roteador)
    app.include_router(rotas_painel.roteador)
    app.include_router(rotas_agenda.roteador)
    app.include_router(rotas_divulgacao.roteador)
    app.include_router(rotas_publicas.roteador)  # por último: /{slug} pega tudo que sobrar

    @app.exception_handler(PrecisaEntrar)
    def precisa_entrar(request: Request, _: PrecisaEntrar):
        return RedirectResponse("/entrar", status_code=303)

    @app.exception_handler(rotas_painel.ComecarPerfil)
    def comecar_perfil(request: Request, _: rotas_painel.ComecarPerfil):
        return RedirectResponse("/painel/comecar", status_code=303)

    @app.exception_handler(ErroHTTP)
    def erro_http(request: Request, erro: ErroHTTP) -> HTMLResponse:
        titulo, ajuda = _TITULOS.get(erro.status_code, ("Algo deu errado", "Tente de novo."))
        return pagina(
            request,
            "erro.html",
            status=erro.status_code,
            titulo=titulo,
            ajuda=ajuda,
            detalhe=erro.detail if erro.status_code in (403, 422) else None,
        )

    @app.exception_handler(psycopg.OperationalError)
    @app.exception_handler(PoolTimeout)
    def banco_fora(request: Request, erro: Exception) -> HTMLResponse:
        # Banco acordando (Neon) ou fora do ar: pede para tentar de novo, sem mostrar o motivo.
        logging.getLogger("encaixe").warning("banco indisponível: %s", type(erro).__name__)
        resposta = pagina(
            request,
            "erro.html",
            status=503,
            titulo="Estamos acordando por aqui",
            ajuda="O serviço ficou um tempo parado e está voltando. Tente de novo em instantes.",
        )
        resposta.headers["Retry-After"] = "5"
        return resposta

    @app.exception_handler(Exception)
    def erro_inesperado(request: Request, erro: Exception) -> HTMLResponse:
        logging.getLogger("encaixe").exception("erro inesperado em %s", request.url.path)
        return pagina(
            request,
            "erro.html",
            status=500,
            titulo="Algo deu errado do nosso lado",
            ajuda="Não foi culpa sua. Tente de novo; se continuar, avise pelo GitHub do projeto.",
        )

    return app


app = create_app()
