import re
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from helpers import SENHA, SP, Sessao

from encaixe import formularios, limite, slugs, telefone
from encaixe.app import create_app
from encaixe.db import painel, publico, sistema
from encaixe.reservas import criar, novo_token


@pytest.fixture(autouse=True)
def zerar_limites():
    for limitador in limite.TODOS:
        limitador.esquecer_tudo()


@pytest.fixture
def rafa(banco):
    s = Sessao("rafa@exemplo.com")
    assert s.criar_perfil().status_code == 303
    return s


def semana_completa(**extra):
    campos = {f"d{d}a_ini": "09:00" for d in range(7)} | {f"d{d}a_fim": "12:00" for d in range(7)}
    return campos | extra


# --- começar -------------------------------------------------------------------------------


def test_sem_perfil_o_painel_leva_para_comecar(banco):
    s = Sessao("rafa@exemplo.com")
    assert "Falta montar sua página" in s.get("/painel").text
    r = s.get("/painel/servicos")
    assert r.status_code == 303 and r.headers["location"] == "/painel/comecar"


@pytest.mark.parametrize(
    ("categoria", "servicos", "discreto"),
    [
        ("beleza", {"Corte", "Barba", "Corte e barba"}, False),
        ("treino", {"Aula em grupo", "Treino individual"}, False),
        ("saude", {"Consulta", "Retorno"}, True),
        ("outro", {"Atendimento"}, False),
    ],
)
def test_categoria_preenche_servicos_horarios_e_discricao(banco, categoria, servicos, discreto):
    s = Sessao("rafa@exemplo.com")
    assert s.criar_perfil(categoria=categoria).status_code == 303
    pro = s.perfil_id()
    with painel(pro) as conn:
        assert {x["nome"] for x in conn.execute("select nome from servicos")} == servicos
        faixas = conn.execute("select count(*) as n from horarios_semanais").fetchone()["n"]
        perfil = conn.execute("select * from profissionais").fetchone()
    assert faixas == 10  # segunda a sexta, dois períodos
    assert perfil["lembrete_discreto"] is discreto
    assert perfil["whatsapp"] == "5511988887777"
    with sistema() as conn:
        assert (
            str(conn.execute("select profissional_id from contas").fetchone()["profissional_id"])
            == pro
        )


def test_aula_do_treino_tem_vagas(banco):
    s = Sessao("rafa@exemplo.com")
    s.criar_perfil(categoria="treino")
    with painel(s.perfil_id()) as conn:
        aula = conn.execute("select vagas from servicos where nome = 'Aula em grupo'").fetchone()
    assert aula["vagas"] == 6


def test_comecar_recusa_dados_ruins_com_mensagens_claras(banco):
    s = Sessao("rafa@exemplo.com")
    r = s.post("/painel/comecar", nome="R", slug="painel", whatsapp="1133334444", categoria="")
    assert r.status_code == 422
    for trecho in ("2 a 80 letras", "reservado", "celular", "combina mais"):
        assert trecho in r.text
    with sistema() as conn:
        assert conn.execute("select count(*) as n from profissionais").fetchone()["n"] == 0


def test_endereco_em_branco_vira_o_nome_e_repetido_e_recusado(banco):
    a, b = Sessao("a@exemplo.com"), Sessao("b@exemplo.com")
    r = a.post(
        "/painel/comecar", nome="Açaí da Ana", slug="", whatsapp="11988887777", categoria="outro"
    )
    assert r.status_code == 303
    with sistema() as conn:
        assert conn.execute("select slug from profissionais").fetchone()["slug"] == "acai-da-ana"
    r = b.post(
        "/painel/comecar",
        nome="Outra",
        slug="acai-da-ana",
        whatsapp="11988887777",
        categoria="outro",
    )
    assert r.status_code == 422 and "já é de outra pessoa" in r.text


def test_todo_formulario_do_painel_exige_csrf(rafa):
    caminhos = [
        "/painel/servicos",
        "/painel/regras",
        "/painel/folgas",
        "/painel/perfil",
        "/painel/horarios",
        "/painel/codigos",
    ]
    for caminho in caminhos:
        r = rafa.http.post(caminho, data={"csrf": "errado"})
        assert r.status_code == 403, caminho


# --- serviços --------------------------------------------------------------------------------


def test_criar_editar_e_desativar_servico(rafa):
    r = rafa.post(
        "/painel/servicos", nome="Sobrancelha", duracao="25", folga="5", vagas="1", preco="R$ 35,5"
    )
    assert r.status_code == 303
    pro = rafa.perfil_id()
    with painel(pro) as conn:
        s = conn.execute("select * from servicos where nome = 'Sobrancelha'").fetchone()
    assert (s["duracao_min"], s["folga_min"], s["vagas"], s["preco_centavos"]) == (25, 5, 1, 3550)
    r = rafa.post(
        f"/painel/servicos/{s['id']}",
        nome="Sobrancelha fina",
        duracao="30",
        folga="0",
        vagas="1",
        preco="",
    )
    assert r.status_code == 303
    r = rafa.post(f"/painel/servicos/{s['id']}/ativo", ativo="0")
    with painel(pro) as conn:
        s = conn.execute("select * from servicos where id = %s", (s["id"],)).fetchone()
    assert (
        s["nome"] == "Sobrancelha fina" and s["duracao_min"] == 30 and s["preco_centavos"] is None
    )
    assert s["ativo"] is False
    assert "desativado" in rafa.get("/painel/servicos").text


@pytest.mark.parametrize(
    "dados",
    [
        {"nome": "X", "duracao": "30"},
        {"nome": "Corte", "duracao": "0"},
        {"nome": "Corte", "duracao": "abc"},
        {"nome": "Corte", "duracao": "30", "vagas": "99"},
        {"nome": "Corte", "duracao": "30", "preco": "caro"},
    ],
)
def test_servico_invalido_e_recusado(rafa, dados):
    r = rafa.post("/painel/servicos", **dados)
    assert r.status_code == 422 and "Confira os campos" in r.text


def test_um_profissional_nao_mexe_no_servico_do_outro(rafa):
    ana = Sessao("ana@exemplo.com")
    ana.criar_perfil(slug="ana-nails", categoria="beleza", nome="Ana")
    with sistema() as conn:
        do_rafa = str(
            conn.execute(
                "select s.id from servicos s join profissionais p on p.id = s.profissional_id"
                " where p.slug = 'rafa-barbeiro' limit 1"
            ).fetchone()["id"]
        )
    assert ana.get(f"/painel/servicos/{do_rafa}").status_code == 404
    assert ana.post(f"/painel/servicos/{do_rafa}", nome="Invadido", duracao="30").status_code == 404
    assert ana.post(f"/painel/servicos/{do_rafa}/ativo", ativo="0").status_code == 404
    assert ana.get("/painel/servicos/nao-e-uuid").status_code == 404
    with sistema() as conn:
        s = conn.execute("select nome, ativo from servicos where id = %s", (do_rafa,)).fetchone()
    assert s["nome"] != "Invadido" and s["ativo"] is True
    assert "Corte" in ana.get("/painel/servicos").text  # os dela, não os do Rafa
    assert "Rafa" not in ana.get("/painel").text


# --- horários e regras -----------------------------------------------------------------------


def test_salvar_horarios_e_ver_de_volta(rafa):
    campos = semana_completa(d6a_ini="", d6a_fim="", d1b_ini="14:00", d1b_fim="18:30")
    r = rafa.post("/painel/horarios", **campos)
    assert r.status_code == 303
    with painel(rafa.perfil_id()) as conn:
        linhas = conn.execute(
            "select dia_semana, inicio, fim from horarios_semanais order by 1, 2"
        ).fetchall()
    assert len(linhas) == 7  # 6 dias de um período + terça com dois
    assert not any(x["dia_semana"] == 6 for x in linhas)
    html = rafa.get("/painel/horarios?salvo=1").text
    assert 'value="18:30"' in html and "Horários salvos" in html


@pytest.mark.parametrize(
    "mudanca",
    [
        {"d0a_ini": "12:00", "d0a_fim": "09:00"},
        {"d0a_ini": "09:00", "d0a_fim": ""},
        {"d0a_ini": "25:00", "d0a_fim": "26:00"},
        {"d0b_ini": "11:00", "d0b_fim": "15:00"},  # cruza com o 1º período (9-12)
    ],
)
def test_horarios_invalidos_nao_apagam_os_que_existem(rafa, mudanca):
    antes = len(_faixas(rafa))
    r = rafa.post("/painel/horarios", **semana_completa(**mudanca))
    assert r.status_code == 422 and "Corrija antes de salvar" in r.text
    assert len(_faixas(rafa)) == antes


def _faixas(sessao):
    with painel(sessao.perfil_id()) as conn:
        return conn.execute("select * from horarios_semanais").fetchall()


def test_regras_convertem_unidades_e_recusam_opcao_invalida(rafa):
    r = rafa.post("/painel/regras", passo="15", antecedencia="4", horizonte="60", cancelar="24")
    assert r.status_code == 303
    with painel(rafa.perfil_id()) as conn:
        p = conn.execute("select * from profissionais").fetchone()
    assert (p["passo_min"], p["antecedencia_min"], p["dias_a_frente"], p["cancelar_ate_min"]) == (
        15,
        240,
        60,
        1440,
    )
    html = rafa.get("/painel/regras").text
    assert re.search(r'<option value="4" selected>', html) and "1 dia antes" in html
    for ruim in ({"passo": "7"}, {"antecedencia": "-1"}, {"horizonte": "0"}, {"cancelar": "x"}):
        base = {"passo": "30", "antecedencia": "2", "horizonte": "30", "cancelar": "2"} | ruim
        assert rafa.post("/painel/regras", **base).status_code == 422


# --- folgas ----------------------------------------------------------------------------------


def test_folga_de_dia_inteiro_vale_no_relogio_do_profissional(rafa):
    r = rafa.post("/painel/folgas", de_dia="2030-03-04", ate_dia="2030-03-05", motivo="viagem")
    assert r.status_code == 303 and "criada=1" in r.headers["location"]
    with painel(rafa.perfil_id()) as conn:
        b = conn.execute("select * from bloqueios").fetchone()
    assert b["inicio"] == datetime(2030, 3, 4, 0, 0, tzinfo=SP).astimezone(UTC)
    assert b["fim"] == datetime(2030, 3, 6, 0, 0, tzinfo=SP).astimezone(UTC)  # inclui o dia 5
    assert "viagem" in rafa.get("/painel/folgas").text


def test_folga_com_horas(rafa):
    rafa.post(
        "/painel/folgas",
        de_dia="2030-03-04",
        de_hora="14:00",
        ate_dia="2030-03-04",
        ate_hora="16:30",
    )
    with painel(rafa.perfil_id()) as conn:
        b = conn.execute("select * from bloqueios").fetchone()
    assert b["inicio"] == datetime(2030, 3, 4, 14, 0, tzinfo=SP).astimezone(UTC)
    assert b["fim"] == datetime(2030, 3, 4, 16, 30, tzinfo=SP).astimezone(UTC)


@pytest.mark.parametrize(
    "dados",
    [
        {"de_dia": ""},
        {"de_dia": "2030-03-05", "ate_dia": "2030-03-04"},
        {"de_dia": "2030-03-04", "de_hora": "16:00", "ate_dia": "2030-03-04", "ate_hora": "15:00"},
        {"de_dia": "30/03/2030"},
    ],
)
def test_folga_invalida_e_recusada(rafa, dados):
    assert rafa.post("/painel/folgas", **dados).status_code == 422
    with painel(rafa.perfil_id()) as conn:
        assert conn.execute("select count(*) as n from bloqueios").fetchone()["n"] == 0


def test_folga_avisa_das_reservas_que_ja_existem(rafa):
    pro = rafa.perfil_id()
    with sistema() as conn:
        servico = str(conn.execute("select id from servicos limit 1").fetchone()["id"])
    inicio = datetime(2030, 3, 4, 10, 0, tzinfo=SP)
    with publico(pro) as conn:
        criar(
            conn,
            profissional_id=pro,
            servico_id=servico,
            inicio=inicio,
            cliente_nome="Dona Maria",
            cliente_whatsapp="5511977776666",
            cliente_email=None,
            token=novo_token(),
        )
    r = rafa.post("/painel/folgas", de_dia="2030-03-04")
    assert r.headers["location"].endswith("cruzam=1")
    html = rafa.get(r.headers["location"]).text
    assert "1 reserva já marcada cai" in html


def test_apagar_folga_so_a_propria(rafa):
    rafa.post("/painel/folgas", de_dia="2030-03-04")
    ana = Sessao("ana@exemplo.com")
    ana.criar_perfil(slug="ana-nails", nome="Ana")
    with sistema() as conn:
        folga = str(conn.execute("select id from bloqueios").fetchone()["id"])
    assert ana.post(f"/painel/folgas/{folga}/apagar").status_code == 404
    with sistema() as conn:
        assert conn.execute("select count(*) as n from bloqueios").fetchone()["n"] == 1
    assert rafa.post(f"/painel/folgas/{folga}/apagar").status_code == 303
    with sistema() as conn:
        assert conn.execute("select count(*) as n from bloqueios").fetchone()["n"] == 0


# --- perfil ----------------------------------------------------------------------------------


def dados_do_perfil(**mudar):
    base = {
        "nome": "Rafa Barbeiro",
        "slug": "rafa-barbeiro",
        "whatsapp": "(11) 98888-7777",
        "fuso": "America/Sao_Paulo",
        "mensagem_lembrete": "Oi, {nome}! Seu horário é {dia} às {hora}. Detalhes: {link}",
        "lembrete_discreto": "1",
    }
    return base | mudar


def test_salvar_perfil(rafa):
    r = rafa.post(
        "/painel/perfil",
        **dados_do_perfil(nome="Rafael", fuso="America/Manaus", lembrete_discreto=""),
    )
    assert r.status_code == 303
    with painel(rafa.perfil_id()) as conn:
        p = conn.execute("select * from profissionais").fetchone()
    assert (p["nome"], p["fuso"], p["lembrete_discreto"]) == ("Rafael", "America/Manaus", False)


@pytest.mark.parametrize(
    ("mudanca", "trecho"),
    [
        ({"slug": "login"}, "reservado"),
        ({"slug": "Rafa Barbeiro"}, "sem acento nem espaço"),
        ({"whatsapp": "123"}, "celular"),
        ({"fuso": "Marte/Olimpo"}, "fusos da lista"),
        ({"mensagem_lembrete": "Oi {nome}, veja {cpf}"}, "{cpf}"),
        ({"mensagem_lembrete": "Oi {nome, tudo bem? Veja {link}"}, "chaves soltas"),
        ({"mensagem_lembrete": "curta"}, "10 a 500"),
    ],
)
def test_perfil_invalido_e_recusado(rafa, mudanca, trecho):
    r = rafa.post("/painel/perfil", **dados_do_perfil(**mudanca))
    assert r.status_code == 422 and trecho in r.text


def test_nao_da_para_pegar_o_endereco_de_outro_profissional(rafa):
    ana = Sessao("ana@exemplo.com")
    ana.criar_perfil(slug="ana-nails", nome="Ana")
    r = ana.post("/painel/perfil", **dados_do_perfil(nome="Ana", slug="rafa-barbeiro"))
    assert r.status_code == 422 and "já é de outra pessoa" in r.text


def test_codigos_novos_pedem_a_senha_e_trocam_os_antigos(rafa):
    antigo = rafa.codigos[0]
    assert rafa.post("/painel/codigos", senha="errada errada").status_code == 403
    r = rafa.post("/painel/codigos", senha=SENHA)
    novos = re.findall(r"<li>([a-z0-9]{5}-[a-z0-9]{5})</li>", r.text)
    assert len(set(novos)) == 8 and antigo not in novos
    de_fora = TestClient(create_app(), follow_redirects=False)
    dados = {"email": "rafa@exemplo.com", "codigo": antigo, "nova_senha": "outra frase boa"}
    assert de_fora.post("/recuperar", data=dados).status_code == 401
    assert de_fora.post("/recuperar", data=dados | {"codigo": novos[0]}).status_code == 303


# --- peças -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("(11) 98888-7777", "5511988887777"),
        ("11988887777", "5511988887777"),
        ("+55 11 98888-7777", "5511988887777"),
        ("5511988887777", "5511988887777"),
        ("0055 11 98888-7777", "5511988887777"),
        ("+351 912 345 678", "351912345678"),
        ("+1 415 555 2671", "14155552671"),
        ("1133334444", None),  # fixo não recebe WhatsApp
        ("(11) 8888-7777", None),
        ("01 98888-7777", None),
        ("abc", None),
        ("", None),
        ("+55 11 12345", None),
    ],
)
def test_normalizar_telefone(entrada, esperado):
    assert telefone.normalizar(entrada) == esperado


def test_formatar_e_link_do_whatsapp():
    assert telefone.formatar("5511988887777") == "(11) 98888-7777"
    assert telefone.formatar("351912345678") == "+351912345678"
    assert telefone.link_whatsapp("5511988887777") == "https://wa.me/5511988887777"
    link = telefone.link_whatsapp(
        "5511988887777", "Oi, Zé! Dia 5 às 14h?\nLink: https://x.y/r?a=1&b=2"
    )
    assert link.startswith("https://wa.me/5511988887777?text=Oi%2C%20Z%C3%A9%21")
    assert "&" not in link.split("?text=")[1] and "\n" not in link


def test_slugs():
    assert slugs.sugerir("  Açaí da Ana & Cia! ") == "acai-da-ana-cia"
    assert slugs.sugerir("Rafa Barbeiro") == "rafa-barbeiro"
    assert slugs.problema("rafa-barbeiro") is None
    for ruim in ("a", "ab-", "-ab", "Ab", "a" * 41, "a--b", "painel", "static", "r", "saude"):
        assert slugs.problema(ruim), ruim


def test_formularios():
    assert formularios.dinheiro("R$ 35,5") == 3550
    assert formularios.dinheiro("35") == 3500
    assert formularios.dinheiro("35.50") == 3550
    assert formularios.dinheiro("-1") is None and formularios.dinheiro("1,234") is None
    assert (
        formularios.formatar_dinheiro(3550) == "R$ 35,50"
        and formularios.formatar_dinheiro(None) == ""
    )
    assert formularios.hora("9:05").hour == 9 and formularios.hora("24:00") is None
    assert formularios.inteiro(" 30 ", 5, 480) == 30 and formularios.inteiro("4", 5, 480) is None
    assert formularios.texto("  oi   mundo \n", 2, 20) == "oi mundo"
    assert formularios.uuid_valido("../x") is None
