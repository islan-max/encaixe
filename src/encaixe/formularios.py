"""Leitura dos campos de formulário: devolve o valor limpo ou None. Nunca confia no que veio."""

import re
import uuid
from datetime import date, time
from urllib.parse import urlencode


def texto(valor: str, minimo: int, maximo: int) -> str | None:
    limpo = " ".join(valor.split())  # tira espaços das pontas e repetidos, inclusive quebras
    return limpo if minimo <= len(limpo) <= maximo else None


def inteiro(valor: str, minimo: int, maximo: int) -> int | None:
    try:
        numero = int(valor.strip())
    except ValueError:
        return None
    return numero if minimo <= numero <= maximo else None


def hora(valor: str) -> time | None:
    achado = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", valor)
    if not achado:
        return None
    h, m = int(achado.group(1)), int(achado.group(2))
    return time(h, m) if h < 24 and m < 60 else None


def data(valor: str) -> date | None:
    try:
        return date.fromisoformat(valor.strip())
    except ValueError:
        return None


def dinheiro(valor: str) -> int | None:
    """'35', '35,5', 'R$ 35,00' -> centavos. Vazio não é erro: quem chama decide."""
    achado = re.fullmatch(r"(?:R\$)?\s*(\d{1,6})(?:[,.](\d{1,2}))?", valor.strip())
    if not achado:
        return None
    return int(achado.group(1)) * 100 + int((achado.group(2) or "0").ljust(2, "0"))


def formatar_dinheiro(centavos: int | None) -> str:
    if centavos is None:
        return ""
    return f"R$ {centavos // 100},{centavos % 100:02d}"


def uuid_valido(valor: str) -> str | None:
    try:
        return str(uuid.UUID(valor))
    except ValueError:
        return None


def consulta(**partes) -> str:
    """?a=1&b=2, sem os valores vazios; vazio se não sobrou nada. Serve para montar links."""
    limpas = {k: v for k, v in partes.items() if v not in (None, "")}
    return "?" + urlencode(limpas) if limpas else ""
