"""O relógio do app. Os testes trocam `agora` para um instante fixo."""

from datetime import UTC, datetime


def agora() -> datetime:
    return datetime.now(UTC)
