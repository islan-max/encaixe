"""Entrar com Google (OpenID Connect, fluxo de código com PKCE, `state` e `nonce`).

Endereços conferidos em https://accounts.google.com/.well-known/openid-configuration. Só pedimos
os escopos `openid email`: o `sub` identifica a conta, o e-mail serve para exibir.
"""

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx2 as httpx
import jwt
from jwt import PyJWKClient

from encaixe.config import Config

AUTORIZAR = "https://accounts.google.com/o/oauth2/v2/auth"
TROCAR_CODIGO = "https://oauth2.googleapis.com/token"
CHAVES = "https://www.googleapis.com/oauth2/v3/certs"
EMISSORES = ["https://accounts.google.com", "accounts.google.com"]


class LoginGoogleFalhou(Exception):
    pass


def novo_desafio() -> dict:
    """Valores que vão no cookie assinado e voltam conferidos no retorno."""
    return {
        "state": secrets.token_urlsafe(24),
        "nonce": secrets.token_urlsafe(24),
        "verifier": secrets.token_urlsafe(48),
    }


def url_de_autorizacao(config: Config, desafio: dict) -> str:
    desafio_pkce = base64.urlsafe_b64encode(
        hashlib.sha256(desafio["verifier"].encode()).digest()
    ).rstrip(b"=")
    return (
        AUTORIZAR
        + "?"
        + urlencode(
            {
                "client_id": config.google_client_id,
                "redirect_uri": f"{config.base_url}/entrar/google/retorno",
                "response_type": "code",
                "scope": "openid email",
                "state": desafio["state"],
                "nonce": desafio["nonce"],
                "code_challenge": desafio_pkce.decode(),
                "code_challenge_method": "S256",
                "prompt": "select_account",
            }
        )
    )


def verificar_id_token(id_token: str, chave, client_id: str, nonce: str) -> dict:
    """Confere assinatura, emissor, público, validade e nonce. Devolve as claims."""
    try:
        claims = jwt.decode(
            id_token,
            chave,
            algorithms=["RS256"],
            audience=client_id,
            issuer=EMISSORES,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError:
        raise LoginGoogleFalhou("token inválido") from None
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise LoginGoogleFalhou("nonce diferente")
    return claims


class ClienteGoogle:
    """A parte que fala com a rede. Os testes trocam esta classe por uma falsa."""

    def __init__(self) -> None:
        self._chaves = PyJWKClient(CHAVES, cache_keys=True, lifespan=3600)

    def identificar(self, config: Config, codigo: str, desafio: dict) -> dict:
        try:
            resposta = httpx.post(
                TROCAR_CODIGO,
                data={
                    "code": codigo,
                    "client_id": config.google_client_id,
                    "client_secret": config.google_client_secret,
                    "redirect_uri": f"{config.base_url}/entrar/google/retorno",
                    "grant_type": "authorization_code",
                    "code_verifier": desafio["verifier"],
                },
                timeout=10,
            )
            resposta.raise_for_status()
            id_token = resposta.json()["id_token"]
            chave = self._chaves.get_signing_key_from_jwt(id_token).key
        except (httpx.HTTPError, KeyError, ValueError, jwt.PyJWTError):
            raise LoginGoogleFalhou("falha ao falar com o Google") from None
        return verificar_id_token(id_token, chave, config.google_client_id, desafio["nonce"])
