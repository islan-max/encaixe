"""Valores assinados com HMAC-SHA256 (estado do login com Google, token CSRF). Sem biblioteca."""

import base64
import hashlib
import hmac
import json
import time

from encaixe.config import carregar


def _mac(chave: str, dados: bytes) -> bytes:
    return hmac.new(chave.encode(), dados, hashlib.sha256).digest()


def assinar(valor: dict, validade_s: int) -> str:
    corpo = json.dumps({**valor, "exp": int(time.time()) + validade_s}, separators=(",", ":"))
    bruto = base64.urlsafe_b64encode(corpo.encode()).rstrip(b"=")
    mac = base64.urlsafe_b64encode(_mac(carregar().secret_key, bruto)).rstrip(b"=")
    return f"{bruto.decode()}.{mac.decode()}"


def ler(texto: str | None) -> dict | None:
    """O valor, se a assinatura confere e não venceu; senão None."""
    if not texto or texto.count(".") != 1:
        return None
    bruto, mac = texto.split(".")
    esperado = base64.urlsafe_b64encode(_mac(carregar().secret_key, bruto.encode())).rstrip(b"=")
    if not hmac.compare_digest(esperado, mac.encode()):
        return None
    try:
        valor = json.loads(base64.urlsafe_b64decode(bruto + "=" * (-len(bruto) % 4)))
    except ValueError:
        return None
    if not isinstance(valor, dict) or valor.get("exp", 0) < time.time():
        return None
    return valor


def token_csrf(sessao_token: str) -> str:
    """Token por sessão: quem não tem o cookie de sessão não sabe calcular."""
    return hmac.new(
        carregar().secret_key.encode(), b"csrf:" + sessao_token.encode(), hashlib.sha256
    ).hexdigest()


def csrf_confere(sessao_token: str, recebido: str) -> bool:
    return hmac.compare_digest(token_csrf(sessao_token), recebido or "")
