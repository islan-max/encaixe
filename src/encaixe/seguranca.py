"""Cabeçalhos de segurança e conferência de origem das requisições que alteram dados."""

from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware

from encaixe.config import carregar

# Sem script e sem estilo inline, sem nada de fora. `form-action` inclui o wa.me porque o botão
# "Lembrar" responde 303 para o WhatsApp e o Chrome aplica o form-action também ao redirecionamento.
CSP = (
    "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; form-action 'self' https://wa.me; "
    "base-uri 'none'; frame-ancestors 'none'"
)
_METODOS_QUE_ALTERAM = {"POST", "PUT", "PATCH", "DELETE"}


class Seguranca(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in _METODOS_QUE_ALTERAM and not _origem_confere(request):
            return PlainTextResponse("Requisição de outra origem recusada.", status_code=403)
        resposta = await call_next(request)
        cabecalhos = resposta.headers
        cabecalhos["Content-Security-Policy"] = CSP
        cabecalhos["X-Content-Type-Options"] = "nosniff"
        cabecalhos["X-Frame-Options"] = "DENY"
        # O link da reserva é um segredo na URL: nunca sai no Referer para outro site (o WhatsApp).
        # Não é `no-referrer` porque aí o Chrome manda `Origin: null` em todo formulário.
        cabecalhos["Referrer-Policy"] = "same-origin"
        cabecalhos["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        cabecalhos["Cross-Origin-Opener-Policy"] = "same-origin"
        if carregar().producao:
            cabecalhos["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path.startswith("/static/"):
            cabecalhos.setdefault("Cache-Control", "public, max-age=3600")
        else:
            cabecalhos.setdefault("Cache-Control", "no-store")
        return resposta


def _origem_confere(request: Request) -> bool:
    # `Sec-Fetch-Site` é posto pelo navegador e o JavaScript de uma página não consegue forjar.
    # Vem antes do `Origin`, que o Chrome troca por "null" em formulários quando o
    # Referrer-Policy é `no-referrer`.
    de_onde = request.headers.get("sec-fetch-site")
    if de_onde is not None:
        return de_onde in ("same-origin", "none")
    origem = request.headers.get("origin")
    if origem is None:
        return True  # curl, testes: sem navegador não há cookie "de carona" para abusar
    return urlsplit(origem).netloc == request.headers.get("host", "")
