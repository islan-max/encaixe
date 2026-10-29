import re
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from helpers import SP, Sessao

from encaixe import divulgacao, limite
from encaixe.app import create_app
from encaixe.db import painel, sistema

AGORA = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)
CELULAR = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Instagram 300.0.0.0"


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


def cliente():
    return TestClient(create_app(), follow_redirects=False)


def origens(sessao=None) -> dict[str, str]:
    with sistema() as conn:
        return {r["nome"]: r["codigo"] for r in conn.execute("select nome, codigo from origens")}


def acessos(codigo: str) -> int:
    with sistema() as conn:
        return conn.execute(
            "select coalesce(sum(n), 0) as n from cliques_dia c"
            " join origens o on o.id = c.origem_id where o.codigo = %s",
            (codigo,),
        ).fetchone()["n"]


def epoch(h, m=0):
    return int(datetime(2030, 3, 4, h, m, tzinfo=SP).timestamp())


def servico_id():
    with sistema() as conn:
        return str(conn.execute("select id from servicos where nome = 'Corte'").fetchone()["id"])


# --- o redirecionador ------------------------------------------------------------------------


def test_perfil_nasce_com_tres_links_de_divulgacao(rafa):
    achadas = origens()
    assert set(achadas) == {"Instagram", "WhatsApp", "Cartão e QR code"}
    assert all(divulgacao.PADRAO_CODIGO.match(c) for c in achadas.values())
    assert len(set(achadas.values())) == 3


def test_link_curto_leva_a_pagina_e_conta_um_acesso_no_dia_do_profissional(rafa):
    codigo = origens()["Instagram"]
    r = cliente().get(f"/r/{codigo}", headers={"User-Agent": CELULAR})
    assert r.status_code == 302 and r.headers["location"] == f"/rafa-barbeiro?v={codigo}"
    assert r.headers["cache-control"] == "no-store"
    cliente().get(f"/r/{codigo}", headers={"User-Agent": CELULAR})
    with sistema() as conn:
        linhas = conn.execute("select dia, n from cliques_dia").fetchall()
    assert linhas == [{"dia": date(2030, 3, 1), "n": 2}]  # 09:00 em SP: dia 1


def test_dia_da_contagem_segue_o_relogio_do_profissional(rafa, monkeypatch):
    monkeypatch.setattr("encaixe.tempo.agora", lambda: datetime(2030, 3, 2, 1, 30, tzinfo=UTC))
    cliente().get(f"/r/{origens()['Instagram']}", headers={"User-Agent": CELULAR})
    with sistema() as conn:
        assert conn.execute("select dia from cliques_dia").fetchone()["dia"] == date(2030, 3, 1)


@pytest.mark.parametrize(
    "agente",
    [
        "WhatsApp/2.23.20 A",
        "facebookexternalhit/1.1",
        "Mozilla/5.0 (compatible; Googlebot/2.1)",
        "curl/8.4.0",
        "python-httpx/0.27",
        "Mozilla/5.0 Chrome-Lighthouse",
        "",
    ],
)
def test_robos_e_previas_de_link_seguem_o_redirecionamento_mas_nao_contam(rafa, agente):
    codigo = origens()["WhatsApp"]
    r = cliente().get(f"/r/{codigo}", headers={"User-Agent": agente})
    assert r.status_code == 302
    assert acessos(codigo) == 0


def test_muitas_aberturas_do_mesmo_endereco_deixam_de_contar(rafa):
    codigo = origens()["Instagram"]
    c = cliente()
    for _ in range(130):
        assert c.get(f"/r/{codigo}", headers={"User-Agent": CELULAR}).status_code == 302
    assert acessos(codigo) == 120  # o resto redireciona, mas não infla o número


def test_codigo_que_nao_existe_ou_mal_formado_da_404(rafa):
    c = cliente()
    for codigo in ("Zzzzzzz", "abc", "abcdefgh", "abc-def", "..%2f..%2fx"):
        assert c.get(f"/r/{codigo}", headers={"User-Agent": CELULAR}).status_code == 404, codigo


def test_nenhuma_tabela_guarda_ip_nem_user_agent(rafa):
    with sistema() as conn:
        colunas = conn.execute(
            "select table_name, column_name from information_schema.columns"
            " where table_schema = 'public'"
        ).fetchall()
    suspeitas = [
        c
        for c in colunas
        if re.search(r"(^|_)(ip|agent|ua|cookie|referer|referrer)(_|$)", c["column_name"])
    ]
    assert suspeitas == []
    por_tabela = {c["column_name"] for c in colunas if c["table_name"] == "cliques_dia"}
    assert por_tabela == {"origem_id", "dia", "n"}


# --- de onde veio a reserva ------------------------------------------------------------------


def reservar(codigo_v, nome="Dona Maria", slug="rafa-barbeiro", servico=None, h=None):
    return cliente().post(
        f"/{slug}/reservar",
        data={
            "s": servico or servico_id(),
            "h": h or epoch(9),
            "nome": nome,
            "whatsapp": "11977776666",
            "v": codigo_v,
        },
    )


def test_reserva_guarda_a_origem_do_link(rafa):
    codigos = origens()
    assert reservar(codigos["Instagram"], "Maria", h=epoch(9)).status_code == 303
    assert reservar("", "Direta", h=epoch(10)).status_code == 303
    assert reservar("lixo123", "Lixo", h=epoch(11)).status_code == 303
    with sistema() as conn:
        linhas = {
            r["cliente_nome"]: r["nome"]
            for r in conn.execute(
                "select r.cliente_nome, o.nome from reservas r left join origens o"
                " on o.id = r.origem_id"
            )
        }
    assert linhas == {"Maria": "Instagram", "Direta": None, "Lixo": None}


def test_codigo_de_outro_profissional_nao_vira_origem(rafa):
    ana = Sessao("ana@exemplo.com")
    ana.criar_perfil(slug="ana-nails", nome="Ana")
    with sistema() as conn:
        da_ana = conn.execute(
            "select o.codigo from origens o join profissionais p on p.id = o.profissional_id"
            " where p.slug = 'ana-nails' limit 1"
        ).fetchone()["codigo"]
    assert reservar(da_ana).status_code == 303
    with sistema() as conn:
        assert conn.execute("select origem_id from reservas").fetchone()["origem_id"] is None


def test_remarcar_mantem_a_origem(rafa):
    codigos = origens()
    r = reservar(codigos["Cartão e QR code"])
    token = r.headers["location"].split("?")[0].removeprefix("/reserva/")
    novo = cliente().post(f"/reserva/{token}/remarcar", data={"h": epoch(14)})
    assert novo.status_code == 303
    with sistema() as conn:
        ativa = conn.execute(
            "select origem_id from reservas where status = 'confirmada'"
        ).fetchone()
        assert ativa["origem_id"] is not None


# --- a tela ----------------------------------------------------------------------------------


def numeros(html: str, nome: str) -> dict[str, int]:
    bloco = html[html.index(f"<h2>{nome}</h2>") :]
    bloco = bloco[: bloco.index("</li>")]
    return {
        rotulo: int(valor) for rotulo, valor in re.findall(r"<dt>([^<]+)</dt><dd>(\d+)</dd>", bloco)
    }


def test_tela_mostra_acessos_e_reservas_por_origem(rafa):
    codigos = origens()
    for _ in range(3):
        cliente().get(f"/r/{codigos['Instagram']}", headers={"User-Agent": CELULAR})
    cliente().get(f"/r/{codigos['WhatsApp']}", headers={"User-Agent": CELULAR})
    for codigo, nome, h in (
        (codigos["Instagram"], "Ana", 9),
        (codigos["Instagram"], "Beto", 10),
        ("", "Caio", 11),
    ):
        r = reservar(codigo, nome, h=epoch(h))
        assert r.status_code == 303, r.text[:200]
    html = rafa.get("/painel/divulgacao").text
    assert numeros(html, "Instagram") == {
        "Aberturas em 30 dias": 3,
        "Aberturas no total": 3,
        "Reservas feitas": 2,
    }
    assert numeros(html, "WhatsApp")["Aberturas no total"] == 1
    assert "sem origem: 1" in html.replace(
        "(ou por links que não são os de cima): ", "sem origem: "
    )
    assert f"/r/{codigos['Instagram']}" in html
    assert 'viewBox="0 0' in html and "QR code do link Instagram" in html


def test_criar_e_esconder_um_link_sem_quebrar_o_que_ja_foi_impresso(rafa):
    assert rafa.post("/painel/divulgacao", nome="Panfleto do bairro").status_code == 303
    novo = origens()["Panfleto do bairro"]
    assert "Panfleto do bairro" in rafa.get("/painel/divulgacao").text
    with sistema() as conn:
        oid = str(
            conn.execute("select id from origens where codigo = %s", (novo,)).fetchone()["id"]
        )
    assert rafa.post(f"/painel/divulgacao/{oid}/arquivar").status_code == 303
    assert "Panfleto do bairro" not in rafa.get("/painel/divulgacao").text
    r = cliente().get(f"/r/{novo}", headers={"User-Agent": CELULAR})
    assert r.status_code == 302 and acessos(novo) == 1  # o cartão impresso continua valendo
    assert rafa.post(f"/painel/divulgacao/{oid}/arquivar").status_code == 404  # já escondido


@pytest.mark.parametrize("nome", ["", "A", "x" * 41])
def test_nome_invalido_de_link_e_recusado(rafa, nome):
    r = rafa.post("/painel/divulgacao", nome=nome)
    assert r.status_code == 422 and "2 a 40 letras" in r.text
    assert len(origens()) == 3


def test_qr_para_baixar_em_svg_e_png(rafa):
    with sistema() as conn:
        oid, codigo = (lambda r: (str(r["id"]), r["codigo"]))(
            conn.execute("select id, codigo from origens where nome = 'Instagram'").fetchone()
        )
    svg = rafa.get(f"/painel/divulgacao/{oid}/qr.svg")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    assert f'filename="encaixe-qr-{codigo}.svg"' in svg.headers["content-disposition"]
    assert svg.text.startswith("<?xml") and "<svg" in svg.text
    png = rafa.get(f"/painel/divulgacao/{oid}/qr.png")
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert rafa.get(f"/painel/divulgacao/{oid}/qr.gif").status_code == 404
    assert rafa.get("/painel/divulgacao/lixo/qr.svg").status_code == 404


def test_um_profissional_nao_mexe_nos_links_do_outro(rafa):
    ana = Sessao("ana@exemplo.com")
    ana.criar_perfil(slug="ana-nails", nome="Ana")
    with sistema() as conn:
        do_rafa = str(
            conn.execute(
                "select o.id from origens o join profissionais p on p.id = o.profissional_id"
                " where p.slug = 'rafa-barbeiro' limit 1"
            ).fetchone()["id"]
        )
    assert ana.post(f"/painel/divulgacao/{do_rafa}/arquivar").status_code == 404
    assert ana.get(f"/painel/divulgacao/{do_rafa}/qr.svg").status_code == 404
    assert "rafa-barbeiro" not in ana.get("/painel/divulgacao").text
    assert (
        rafa.http.post(f"/painel/divulgacao/{do_rafa}/arquivar", data={"csrf": "x"}).status_code
        == 403
    )
    with painel(ana.perfil_id()) as conn:
        assert conn.execute("select count(*) as n from origens").fetchone()["n"] == 3


def test_codigos_sao_curtos_e_variados():
    sorteados = {divulgacao.novo_codigo() for _ in range(2000)}
    assert len(sorteados) == 2000
    assert all(divulgacao.PADRAO_CODIGO.match(c) for c in sorteados)
