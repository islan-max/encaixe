"""Limite de tentativas em memória, por processo.

Nada vai para o banco: o endereço de quem acessa só existe na memória, por minutos. Vale para UMA
instância (é o caso do Render free). Com várias instâncias o limite se multiplica; aí troque por um
contador compartilhado. Documentado em docs/VERIFICACAO.md (S08).
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from encaixe.config import carregar


class Limitador:
    def __init__(self, maximo: int, janela_s: float):
        self.maximo = maximo
        self.janela_s = janela_s
        self._eventos: dict[str, deque[float]] = defaultdict(deque)
        self._trava = threading.Lock()

    def _limpar(self, chave: str, agora: float) -> deque[float]:
        fila = self._eventos[chave]
        while fila and fila[0] <= agora - self.janela_s:
            fila.popleft()
        if not fila:
            self._eventos.pop(chave, None)
            return self._eventos[chave]
        return fila

    def registrar(self, chave: str, agora: float | None = None) -> int | None:
        """Conta uma tentativa. Devolve None se passou, ou os segundos de espera se estourou."""
        agora = time.monotonic() if agora is None else agora
        with self._trava:
            fila = self._limpar(chave, agora)
            if len(fila) >= self.maximo:
                return max(1, int(fila[0] + self.janela_s - agora) + 1)
            fila.append(agora)
            return None

    def esta_bloqueado(self, chave: str, agora: float | None = None) -> int | None:
        """Segundos de espera se a chave já estourou, sem contar uma tentativa nova."""
        agora = time.monotonic() if agora is None else agora
        with self._trava:
            fila = self._limpar(chave, agora)
            if len(fila) >= self.maximo:
                return max(1, int(fila[0] + self.janela_s - agora) + 1)
            return None

    def zerar(self, chave: str) -> None:
        with self._trava:
            self._eventos.pop(chave, None)

    def esquecer_tudo(self) -> None:
        with self._trava:
            self._eventos.clear()


def ip_do_cliente(request: Request) -> str:
    """Endereço de quem acessa. `X-Forwarded-For` é forjável: só vale o que os proxies de
    confiança acrescentaram, contados da direita para a esquerda (`PROXY_HOPS`)."""
    saltos = carregar().proxy_hops
    if saltos > 0:
        cadeia = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p]
        if len(cadeia) >= saltos:
            return cadeia[-saltos]
    return request.client.host if request.client else "desconhecido"


# Limites por operação. Todos por janela deslizante; ver docs/VERIFICACAO.md (S08).
LOGIN_POR_EMAIL = Limitador(maximo=5, janela_s=15 * 60)
LOGIN_POR_IP = Limitador(maximo=30, janela_s=15 * 60)
CADASTRO_POR_IP = Limitador(maximo=10, janela_s=60 * 60)
RECUPERAR_POR_IP = Limitador(maximo=10, janela_s=60 * 60)
RESERVA_POR_IP = Limitador(maximo=20, janela_s=60 * 60)
CANCELAR_POR_IP = Limitador(maximo=30, janela_s=60 * 60)
REDIRECT_POR_IP = Limitador(maximo=120, janela_s=60)

TODOS = (
    LOGIN_POR_EMAIL,
    LOGIN_POR_IP,
    CADASTRO_POR_IP,
    RECUPERAR_POR_IP,
    RESERVA_POR_IP,
    CANCELAR_POR_IP,
    REDIRECT_POR_IP,
)
