from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as ErroHTTP

from encaixe import rotas_contas, rotas_site
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
    app.include_router(rotas_site.roteador)
    app.include_router(rotas_contas.roteador)

    @app.api_route("/saude", methods=["GET", "HEAD"])
    def saude() -> dict[str, str]:
        # Sem tocar no banco: serve de ping para manter o Render acordado sem gastar o Neon.
        return {"estado": "ok"}

    @app.exception_handler(PrecisaEntrar)
    def precisa_entrar(request: Request, _: PrecisaEntrar):
        return RedirectResponse("/entrar", status_code=303)

    @app.exception_handler(ErroHTTP)
    def erro_http(request: Request, erro: ErroHTTP) -> HTMLResponse:
        titulo, ajuda = _TITULOS.get(erro.status_code, ("Algo deu errado", "Tente de novo."))
        return pagina(
            request,
            "erro.html",
            status=erro.status_code,
            titulo=titulo,
            ajuda=ajuda,
            detalhe=erro.detail if erro.status_code == 403 else None,
        )

    return app


app = create_app()
