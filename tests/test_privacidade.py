from datetime import UTC, datetime

import psycopg
import pytest
from fastapi.testclient import TestClient
from helpers import SP, Sessao

from encaixe import config, limite
from encaixe.app import create_app
from encaixe.db import sistema

AGORA = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)
SEGREDO = "segredo-do-cron-com-tamanho-bom-para-o-teste"


@pytest.fixture(autouse=True)
def relogio(monkeypatch):
    monkeypatch.setattr("encaixe.tempo.agora", lambda: AGORA)
    for limitador in limite.TODOS:
        limitador.esquecer_tudo()


@pytest.fixture
def rafa(banco):
    s = Sessao("rafa@exemplo.com")
    assert s.criar_perfil().status_code == 303
    return s


def cliente(**args):
    return TestClient(create_app(), follow_redirects=False, **args)


def epoch(h, dia=(2030, 3, 4)):
    return int(datetime(*dia, h, 0, tzinfo=SP).timestamp())


def reservar(h, nome, dia=(2030, 3, 4)):
    with sistema() as conn:
        servico = str(conn.execute("select id from servicos where nome = 'Corte'").fetchone()["id"])
    r = cliente().post(
        "/rafa-barbeiro/reservar",
        data={"s": servico, "h": epoch(h, dia), "nome": nome, "whatsapp": "11977776666"},
    )
    assert r.status_code == 303, r.text[:200]
    return r.headers["location"].split("?")[0].removeprefix("/reserva/")


# --- páginas legais, robots e sitemap --------------------------------------------------------


def test_politica_e_termos_existem_e_dizem_o_que_o_programa_faz(banco):
    c = cliente()
    politica = c.get("/privacidade")
    assert politica.status_code == 200
    for trecho in (
        "Nome</strong> e <strong>WhatsApp",
        "90 dias",
        "não guarda o seu endereço de internet",
    ):
        assert trecho in politica.text
    assert "cookie" in politica.text and "Excluir minha conta" in politica.text
    termos = c.get("/termos")
    assert termos.status_code == 200 and "sem garantia de disponibilidade" in termos.text
    assert "Não manda mensagens" in termos.text
    assert "<script" not in politica.text.lower()


def test_contato_por_email_so_aparece_se_configurado(banco, monkeypatch):
    assert "mailto:" not in cliente().get("/privacidade").text
    monkeypatch.setenv("CONTATO_EMAIL", "contato@exemplo.com")
    assert 'href="mailto:contato@exemplo.com"' in cliente().get("/privacidade").text


def test_rodape_leva_a_politica_e_aos_termos(banco):
    html = cliente().get("/").text
    assert 'href="/privacidade"' in html and 'href="/termos"' in html


def test_robots_e_sitemap(banco, monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://encaixe.exemplo")
    robots = cliente().get("/robots.txt")
    assert robots.status_code == 200 and robots.headers["content-type"].startswith("text/plain")
    for linha in (
        "Disallow: /painel",
        "Disallow: /reserva/",
        "Disallow: /r/",
        "Disallow: /interno/",
    ):
        assert linha in robots.text
    assert "Sitemap: https://encaixe.exemplo/sitemap.xml" in robots.text
    mapa = cliente().get("/sitemap.xml")
    assert mapa.headers["content-type"].startswith("application/xml")
    assert "<loc>https://encaixe.exemplo/privacidade</loc>" in mapa.text
    assert "/painel" not in mapa.text and "/reserva" not in mapa.text


def test_paginas_privadas_pedem_para_ficar_fora_das_buscas(rafa):
    token = reservar(9, "Dona Maria")
    c = cliente()
    for caminho in ("/rafa-barbeiro", f"/reserva/{token}", "/entrar", "/cadastrar"):
        assert 'name="robots" content="noindex"' in c.get(caminho).text, caminho
    assert 'name="robots" content="noindex"' in rafa.get("/painel").text
    assert 'name="robots"' not in c.get("/").text  # a vitrine pode ser indexada


def test_previa_de_compartilhamento(rafa, monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://encaixe.exemplo")
    pagina = cliente().get("/rafa-barbeiro").text
    assert 'property="og:title" content="Marque seu horário com Rafa Barbeiro"' in pagina
    assert 'property="og:image" content="https://encaixe.exemplo/static/og.png"' in pagina
    imagem = cliente().get("/static/og.png")
    assert imagem.status_code == 200 and imagem.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert imagem.headers["cache-control"] == "public, max-age=3600"
    assert cliente().get("/static/apple-touch-icon.png").status_code == 200
    assert cliente().get("/static/favicon.svg").status_code == 200


# --- limpeza diária --------------------------------------------------------------------------


def chamar_limpeza(token=SEGREDO):
    cabecalhos = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return cliente().post("/interno/limpeza", headers=cabecalhos)


def test_limpeza_so_com_o_segredo_certo(rafa, monkeypatch):
    assert chamar_limpeza().status_code == 404  # sem CRON_SECRET configurada a rota não existe
    monkeypatch.setenv("CRON_SECRET", SEGREDO)
    for ruim in (None, "", "errado", SEGREDO + "x", SEGREDO[:-1]):
        assert chamar_limpeza(ruim).status_code == 404, ruim
    assert cliente().get("/interno/limpeza").status_code in (404, 405)
    assert chamar_limpeza().status_code == 200


def test_limpeza_anonimiza_depois_de_90_dias_e_apaga_o_que_venceu(rafa, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", SEGREDO)
    with sistema() as conn:
        conn.execute("update profissionais set dias_a_frente = 180")
    antiga = reservar(9, "Dona Maria")  # 04/03/2030
    cancelada = reservar(10, "Seu João")
    cliente().post(f"/reserva/{cancelada}/cancelar")
    recente = reservar(9, "Dona Recente", dia=(2030, 5, 20))
    with sistema() as conn:
        servico = conn.execute("select id, profissional_id from servicos limit 1").fetchone()
        conn.execute(
            "insert into espera (profissional_id, servico_id, dia, nome, whatsapp)"
            " values (%s, %s, '2030-03-04', 'Tia Ana', '5511955554444'),"
            " (%s, %s, '2030-06-08', 'Tio Beto', '5511955553333')",
            (servico["profissional_id"], servico["id"]) * 2,
        )
    with sistema() as conn:  # o relógio do teste é 2030: a sessão precisa valer nele
        conn.execute("update sessoes set expira_em = '2031-01-01'")
    assert chamar_limpeza().json() == {
        "reservas_anonimizadas": 0,
        "espera_apagada": 0,
        "sessoes_apagadas": 0,
        "cliques_apagados": 0,
    }  # em 01/03/2030 nada venceu ainda
    monkeypatch.setattr("encaixe.tempo.agora", lambda: datetime(2030, 6, 10, 12, 0, tzinfo=UTC))
    with sistema() as conn:
        conn.execute("update sessoes set expira_em = '2030-06-01'")
    resultado = chamar_limpeza().json()
    assert resultado == {
        "reservas_anonimizadas": 2,
        "espera_apagada": 1,
        "sessoes_apagadas": 1,
        "cliques_apagados": 0,
    }
    with sistema() as conn:
        por_nome = {
            r["cliente_nome"]: r
            for r in conn.execute(
                "select cliente_nome, cliente_whatsapp, cliente_email from reservas"
            )
        }
        restante = conn.execute("select nome from espera").fetchall()
    assert set(por_nome) == {"Cliente removido", "Dona Recente"}
    assert por_nome["Dona Recente"]["cliente_whatsapp"] == "5511977776666"
    assert all(
        r["cliente_whatsapp"] is None for n, r in por_nome.items() if n == "Cliente removido"
    )
    assert [r["nome"] for r in restante] == ["Tio Beto"]
    assert chamar_limpeza().json() == {
        "reservas_anonimizadas": 0,
        "espera_apagada": 0,
        "sessoes_apagadas": 0,
        "cliques_apagados": 0,
    }  # rodar de novo não muda nada
    assert "Dona Maria" not in cliente().get(f"/reserva/{antiga}").text
    assert "Dona Recente" in cliente().get(f"/reserva/{recente}").text


# --- excluir a conta -------------------------------------------------------------------------


def test_excluir_conta_apaga_tudo_do_profissional_e_so_dele(rafa):
    ana = Sessao("ana@exemplo.com")
    ana.criar_perfil(slug="ana-nails", nome="Ana")
    reservar(9, "Dona Maria")
    with sistema() as conn:
        codigo = conn.execute("select codigo from origens limit 1").fetchone()["codigo"]
    assert "Excluir minha conta" in rafa.get("/painel/perfil").text
    pagina = rafa.get("/painel/excluir-conta")
    assert pagina.status_code == 200 and "rafa-barbeiro" in pagina.text
    assert rafa.post("/painel/excluir-conta", confirmacao="outro-nome").status_code == 422
    assert (
        rafa.http.post("/painel/excluir-conta", data={"confirmacao": "rafa-barbeiro"}).status_code
        == 403
    )
    r = rafa.post("/painel/excluir-conta", confirmacao=" Rafa-Barbeiro ")
    assert r.status_code == 303 and r.headers["location"] == "/?excluida=1"
    assert "sessao" in r.headers["set-cookie"] and "Max-Age=0" in r.headers["set-cookie"]
    with sistema() as conn:
        assert conn.execute("select count(*) as n from reservas").fetchone()["n"] == 0
        assert [p["slug"] for p in conn.execute("select slug from profissionais")] == ["ana-nails"]
        assert [c["email"] for c in conn.execute("select email from contas")] == ["ana@exemplo.com"]
        assert conn.execute("select count(*) as n from sessoes").fetchone()["n"] == 1
        assert conn.execute("select count(*) as n from origens").fetchone()["n"] == 3  # só da Ana
    assert cliente().get("/rafa-barbeiro").status_code == 404
    assert cliente().get(f"/r/{codigo}", headers={"User-Agent": "Mozilla/5.0"}).status_code == 404
    assert rafa.get("/painel").status_code == 303  # a sessão foi embora
    assert "Sua conta foi excluída" in cliente().get("/?excluida=1").text
    assert ana.get("/painel").status_code == 200


# --- produção, erros e falhas ----------------------------------------------------------------


def test_em_producao_cookie_seguro_com_prefixo_host_e_hsts(banco, monkeypatch):
    monkeypatch.setenv("ENCAIXE_ENV", "producao")
    monkeypatch.setenv("SECRET_KEY", "k" * 40)
    c = TestClient(create_app(), follow_redirects=False, base_url="https://testserver")
    r = c.post("/cadastrar", data={"email": "rafa@exemplo.com", "senha": "uma frase longa e boa"})
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("__Host-sessao=") and "Secure" in cookie and "HttpOnly" in cookie
    assert "SameSite=lax" in cookie and "Path=/" in cookie and "Domain" not in cookie
    assert r.headers["strict-transport-security"] == "max-age=31536000"
    assert c.get("/painel/comecar").status_code == 200


def test_producao_exige_uma_chave_secreta_boa(monkeypatch):
    monkeypatch.setenv("ENCAIXE_ENV", "producao")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        config.carregar()
    monkeypatch.setenv("SECRET_KEY", "curta")
    with pytest.raises(RuntimeError):
        config.carregar()


def test_erro_inesperado_mostra_pagina_amiga_sem_detalhes(banco, monkeypatch):
    def quebrar(slug):
        raise RuntimeError("segredo interno: senha=1234")

    monkeypatch.setattr("encaixe.rotas_publicas._pro_ou_404", quebrar)
    c = TestClient(create_app(), follow_redirects=False, raise_server_exceptions=False)
    r = c.get("/alguem")
    assert r.status_code == 500 and "Algo deu errado do nosso lado" in r.text
    assert "segredo interno" not in r.text and "Traceback" not in r.text


def test_banco_fora_do_ar_pede_para_tentar_de_novo(banco, monkeypatch):
    def fora(slug):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr("encaixe.rotas_publicas._pro_ou_404", fora)
    c = TestClient(create_app(), follow_redirects=False, raise_server_exceptions=False)
    r = c.get("/alguem")
    assert r.status_code == 503 and r.headers["retry-after"] == "5"
    assert "Estamos acordando" in r.text and "connection refused" not in r.text


def test_o_ping_de_saude_nao_depende_do_banco(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nao-existe:1/nada")
    assert cliente().get("/saude").json() == {"estado": "ok"}
    assert cliente().head("/saude").status_code == 200
