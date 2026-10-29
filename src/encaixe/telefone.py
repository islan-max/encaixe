"""Número de WhatsApp: só dígitos, com o código do país (é o que o wa.me pede)."""

import re
from urllib.parse import quote


def normalizar(texto: str) -> str | None:
    """Celular brasileiro (com ou sem 55 e +) ou número internacional começando com +.

    Devolve só dígitos com o código do país, ou None se não parece um número que recebe WhatsApp.
    """
    t = texto.strip()
    digitos = re.sub(r"\D", "", t)
    if t.startswith("+") or t.startswith("00"):
        digitos = digitos[2:] if t.startswith("00") else digitos
        if not digitos.startswith("55"):
            return digitos if 8 <= len(digitos) <= 15 and digitos[0] != "0" else None
    elif len(digitos) in (10, 11):
        digitos = "55" + digitos
    # Brasil: 55 + DDD (2) + 9 + 8 dígitos. Fixo (sem o 9) não recebe WhatsApp.
    if re.fullmatch(r"55[1-9][1-9]9\d{8}", digitos):
        return digitos
    return None


def formatar(numero: str) -> str:
    if len(numero) == 13 and numero.startswith("55"):
        return f"({numero[2:4]}) {numero[4:9]}-{numero[9:]}"
    return f"+{numero}"


def link_whatsapp(numero: str, mensagem: str = "") -> str:
    base = f"https://wa.me/{numero}"
    return f"{base}?text={quote(mensagem, safe='')}" if mensagem else base
