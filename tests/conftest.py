import os
import uuid

import pytest

from encaixe.db import fechar_pool, sistema
from encaixe.migrate import migrar

TABELAS = "reservas, bloqueios, horarios_semanais, servicos, profissionais"


@pytest.fixture(scope="session")
def database_url(tmp_path_factory):
    # O CI aponta TEST_DATABASE_URL para um Postgres de serviço; local sobe um embutido (pgserver).
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return
    import pgserver

    servidor = pgserver.get_server(tmp_path_factory.mktemp("pg"))
    yield servidor.get_uri()
    servidor.cleanup()


@pytest.fixture
def banco(database_url, monkeypatch):
    """Banco migrado e vazio, com um pool que comporta os testes de concorrência."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("DB_POOL_MAX", "16")
    fechar_pool()
    with sistema() as conn:
        migrar(conn)
        conn.execute(f"truncate {TABELAS} cascade")
    yield
    fechar_pool()


@pytest.fixture
def novo_profissional(banco):
    def criar(slug: str | None = None, **campos) -> str:
        slug = slug or f"pro-{uuid.uuid4().hex[:10]}"
        dados = {"nome": "Rafa Barbeiro", "categoria": "beleza", "whatsapp": "5511999998888"}
        dados.update(campos)
        with sistema() as conn:
            return str(
                conn.execute(
                    "insert into profissionais (slug, nome, categoria, whatsapp) values"
                    " (%s, %s, %s, %s) returning id",
                    (slug, dados["nome"], dados["categoria"], dados["whatsapp"]),
                ).fetchone()["id"]
            )

    return criar


@pytest.fixture
def novo_servico(banco):
    def criar(profissional_id: str, nome="Corte", duracao=30, folga=0, vagas=1, ativo=True) -> str:
        with sistema() as conn:
            return str(
                conn.execute(
                    "insert into servicos (profissional_id, nome, duracao_min, folga_min, vagas,"
                    " ativo) values (%s, %s, %s, %s, %s, %s) returning id",
                    (profissional_id, nome, duracao, folga, vagas, ativo),
                ).fetchone()["id"]
            )

    return criar
