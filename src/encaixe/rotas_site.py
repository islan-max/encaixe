"""Páginas soltas do site: início, política, termos, robots, sitemap e a limpeza diária."""

import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response

from encaixe import limpeza, tempo
from encaixe.config import carregar
from encaixe.db import sistema
from encaixe.web import pagina

roteador = APIRouter()


@roteador.get("/")
def inicio(request: Request):
    return pagina(request, "inicio.html")


@roteador.get("/privacidade")
def privacidade(request: Request):
    return pagina(request, "privacidade.html")


@roteador.get("/termos")
def termos(request: Request):
    return pagina(request, "termos.html")


@roteador.get("/robots.txt", response_class=PlainTextResponse)
def robots() -> str:
    base = carregar().base_url
    # Páginas de profissionais e de reservas também levam <meta noindex>: aqui só se pede
    # para os robôs nem passarem pelo que é privado.
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /painel\n"
        "Disallow: /reserva/\n"
        "Disallow: /r/\n"
        "Disallow: /entrar\n"
        "Disallow: /recuperar\n"
        "Disallow: /interno/\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )


@roteador.get("/sitemap.xml")
def sitemap() -> Response:
    base = carregar().base_url
    urls = "".join(
        f"<url><loc>{base}{caminho}</loc></url>" for caminho in ("/", "/privacidade", "/termos")
    )
    corpo = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    )
    return Response(corpo, media_type="application/xml")


@roteador.post("/interno/limpeza")
def limpeza_diaria(request: Request):
    """Chamada uma vez por dia pelo GitHub Actions, com `Authorization: Bearer <CRON_SECRET>`."""
    segredo = carregar().cron_secret
    if not segredo:
        raise HTTPException(404)
    enviado = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not secrets.compare_digest(enviado.encode(), segredo.encode()):
        raise HTTPException(404)  # igual a "não existe": não confirma que a rota existe
    with sistema() as conn:
        return limpeza.executar(conn, tempo.agora())
