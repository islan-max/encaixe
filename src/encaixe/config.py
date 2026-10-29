"""Configuração por variáveis de ambiente. Nada de segredo no código nem no Git."""

import os
import secrets
from dataclasses import dataclass

_CHAVE_DE_DESENVOLVIMENTO = secrets.token_urlsafe(32)  # muda a cada subida: só serve para testes


@dataclass(frozen=True)
class Config:
    producao: bool
    secret_key: str
    base_url: str  # endereço público, usado no redirect do Google e nos links
    proxy_hops: int  # quantos proxies confiáveis estão na frente (0 = ninguém)
    client_ip_header: (
        str | None
    )  # cabeçalho que o proxy de confiança sobrescreve (ex.: cf-connecting-ip)
    google_client_id: str | None
    google_client_secret: str | None
    cron_secret: str | None
    contato_email: str | None  # e-mail público da política de privacidade (opcional)

    @property
    def cookie_seguro(self) -> bool:
        return self.producao

    @property
    def google_ativo(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


def carregar() -> Config:
    producao = os.environ.get("ENCAIXE_ENV") == "producao"
    chave = os.environ.get("SECRET_KEY")
    if producao and (not chave or len(chave) < 32):
        raise RuntimeError("SECRET_KEY é obrigatória em produção e precisa ter 32+ caracteres")
    return Config(
        producao=producao,
        secret_key=chave or _CHAVE_DE_DESENVOLVIMENTO,
        base_url=os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/"),
        proxy_hops=int(os.environ.get("PROXY_HOPS", "0")),
        client_ip_header=(os.environ.get("CLIENT_IP_HEADER") or "").strip().lower() or None,
        google_client_id=os.environ.get("GOOGLE_CLIENT_ID") or None,
        google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET") or None,
        cron_secret=os.environ.get("CRON_SECRET") or None,
        contato_email=os.environ.get("CONTATO_EMAIL") or None,
    )
