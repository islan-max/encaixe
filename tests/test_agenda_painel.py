import re
from datetime import UTC, datetime
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from helpers import SP, Sessao

from encaixe import limite, mensagens
from encaixe.app import create_app
from encaixe.db import hash_do_token, painel, sistema
from encaixe.horarios import carregar_fuso
from encaixe.reservas import token_da_reserva

AGORA = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)  # sexta, 09:00 em São Paulo
DIA = "2030-03-04"  # segunda


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


def epoch(h, m=0, dia=(2030, 3, 4)):
    return int(datetime(*dia, h, m, tzinfo=SP).timestamp())


def servico_id(nome="Corte"):
    with sistema() as conn:
        return str(
            conn.execute("select id from servicos where nome = %s", (nome,)).fetchone()["id"]
        )


def cliente_reserva(
    h, nome="Dona Maria", slug="rafa-barbeiro", servico=None, whatsapp="11977776666"
):
    c = TestClient(create_app(), follow_redirects=False)
    r = c.post(
        f"/{slug}/reservar",
        data={"s": servico or servico_id(), "h": h, "nome": nome, "whatsapp": whatsapp},
    )
    assert r.status_code == 303, r.text[:300]
    return c, r.headers["location"].split("?")[0].removeprefix("/reserva/")


def reserva_id(nome="Dona Maria") -> str:
    with sistema() as conn:
        return str(
            conn.execute("select id from reservas where cliente_nome = %s", (nome,)).fetchone()[
                "id"
            ]
        )


def destino_whatsapp(resposta) -> tuple[str, str]:
    assert resposta.status_code == 303
    base, _, texto = resposta.headers["location"].partition("?text=")
    return base, unquote(texto)


# --- a agenda --------------------------------------------------------------------------------


def test_agenda_mostra_o_dia_com_quem_vem_e_a_semana(rafa):
    cliente_reserva(epoch(9), "Dona Maria")
    cliente_reserva(epoch(10), "Seu João", whatsapp="11966665555")
    html = rafa.get(f"/painel?dia={DIA}").text
    assert "segunda-feira, 4 de março" in html
    assert "Dona Maria" in html and "Seu João" in html
    assert "(11) 97777-6666" in html and "Corte" in html and "Marcado" in html
    assert html.index("Dona Maria") < html.index("Seu João")  # em ordem de horário
    hoje = rafa.get("/painel").text
    assert "Hoje, sexta-feira, 1 de março" in hoje and "Nenhum horário marcado" in hoje
    assert "seg 04/03" in hoje and "2 marcados" in hoje


def test_dia_vale_no_relogio_do_profissional(rafa):
    cliente_reserva(epoch(17, 30), "Seu Fim de Tarde")  # 17:30 em SP = 20:30 UTC, mesmo dia
    with painel(rafa.perfil_id()) as conn:
        conn.execute("update horarios_semanais set fim = '23:59' where dia_semana = 0")
    cliente_reserva(epoch(23, 0), "Dona Coruja")  # 23:00 em SP = 02:00 UTC do dia seguinte
    assert "Dona Coruja" in rafa.get(f"/painel?dia={DIA}").text
    assert "Dona Coruja" not in rafa.get("/painel?dia=2030-03-05").text


def test_agenda_de_um_profissional_nao_mostra_a_do_outro(rafa):
    cliente_reserva(epoch(9), "Dona Maria")
    ana = Sessao("ana@exemplo.com")
    ana.criar_perfil(slug="ana-nails", nome="Ana")
    assert "Dona Maria" not in ana.get(f"/painel?dia={DIA}").text
    rid = reserva_id()
    assert ana.post(f"/painel/reservas/{rid}/lembrar").status_code == 404
    assert ana.post(f"/painel/reservas/{rid}/estado", novo="faltou").status_code == 404
    assert ana.get(f"/painel/reservas/{rid}/cancelar").status_code == 404
    assert ana.post(f"/painel/reservas/{rid}/cancelar").status_code == 404
    assert ana.get("/painel/reservas/lixo/cancelar").status_code == 404
    with sistema() as conn:
        assert conn.execute("select status, lembrete_em from reservas").fetchone() == {
            "status": "confirmada",
            "lembrete_em": None,
        }


def test_parametro_de_dia_invalido_cai_em_hoje(rafa):
    assert "Hoje" in rafa.get("/painel?dia=lixo").text


# --- lembrete com um toque -------------------------------------------------------------------


def test_lembrar_abre_o_whatsapp_com_a_mensagem_pronta_e_registra(rafa):
    c, token = cliente_reserva(epoch(9), "Dona Maria Silva")
    rid = reserva_id("Dona Maria Silva")
    base, texto = destino_whatsapp(rafa.post(f"/painel/reservas/{rid}/lembrar"))
    assert base == "https://wa.me/5511977776666"
    assert texto.startswith("Oi, Dona!")  # só o primeiro nome
    assert "segunda-feira, 4 de março" in texto and "09:00" in texto
    link = re.search(r"(http\S+/reserva/\S+)", texto).group(1)
    assert link.endswith(token_da_reserva(rid))  # o link do lembrete abre a reserva do cliente
    assert c.get(link.replace("http://localhost:8000", "")).status_code == 200
    with painel(rafa.perfil_id()) as conn:
        assert (
            conn.execute("select lembrete_em from reservas").fetchone()["lembrete_em"] is not None
        )
    assert "lembrete enviado às" in rafa.get(f"/painel?dia={DIA}").text


def test_o_token_derivado_bate_com_o_hash_guardado_e_nao_se_repete(rafa):
    _, token = cliente_reserva(epoch(9))
    rid = reserva_id()
    assert token == token_da_reserva(rid)
    with sistema() as conn:
        assert bytes(conn.execute("select token_hash from reservas").fetchone()["token_hash"]) == (
            bytes.fromhex(hash_do_token(token))
        )
    assert token_da_reserva(rid) != token_da_reserva("00000000-0000-0000-0000-000000000000")
    assert len(token) == 32


def test_lembrete_discreto_troca_o_nome_do_servico(rafa):
    with painel(rafa.perfil_id()) as conn:
        conn.execute(
            "update profissionais set lembrete_discreto = true,"
            " mensagem_lembrete = 'Oi, {nome}! {servico} dia {dia} às {hora}. {link}'"
        )
    cliente_reserva(epoch(9))
    _, texto = destino_whatsapp(rafa.post(f"/painel/reservas/{reserva_id()}/lembrar"))
    assert "atendimento dia" in texto and "Corte" not in texto


def test_nao_lembra_reserva_cancelada_nem_sem_whatsapp(rafa):
    cliente_reserva(epoch(9))
    rid = reserva_id()
    with painel(rafa.perfil_id()) as conn:
        conn.execute("update reservas set status = 'cancelada_profissional'")
    assert rafa.post(f"/painel/reservas/{rid}/lembrar").status_code == 409
    assert "Lembrar no WhatsApp" not in rafa.get(f"/painel?dia={DIA}").text


def test_lembrar_exige_csrf(rafa):
    cliente_reserva(epoch(9))
    r = rafa.http.post(f"/painel/reservas/{reserva_id()}/lembrar", data={"csrf": "errado"})
    assert r.status_code == 403


# --- atendeu, faltou, cancelar ---------------------------------------------------------------


def test_marcar_atendeu_e_faltou_so_depois_que_o_horario_comecou(rafa, monkeypatch):
    c, token = cliente_reserva(epoch(9))
    rid = reserva_id()
    assert rafa.post(f"/painel/reservas/{rid}/estado", novo="atendida").status_code == 409
    monkeypatch.setattr("encaixe.tempo.agora", lambda: datetime(2030, 3, 4, 10, 0, tzinfo=SP))
    assert "Já começou" in rafa.get(f"/painel?dia={DIA}").text
    assert rafa.post(f"/painel/reservas/{rid}/estado", novo="x").status_code == 422
    r = rafa.post(f"/painel/reservas/{rid}/estado", novo="atendida", dia=DIA)
    assert r.status_code == 303 and r.headers["location"] == f"/painel?dia={DIA}"
    assert "Atendimento concluído" in c.get(f"/reserva/{token}").text
    assert rafa.post(f"/painel/reservas/{rid}/estado", novo="faltou").status_code == 303
    assert "Marcada como falta" in c.get(f"/reserva/{token}").text
    assert "Corrigir para atendeu" in rafa.get(f"/painel?dia={DIA}").text


def test_profissional_cancela_e_avisa_o_cliente_pelo_whatsapp(rafa):
    c, token = cliente_reserva(epoch(9), "Dona Maria Silva")
    rid = reserva_id("Dona Maria Silva")
    confirmar = rafa.get(f"/painel/reservas/{rid}/cancelar?dia={DIA}")
    assert "Cancelar este horário?" in confirmar.text and "Dona Maria Silva" in confirmar.text
    r = rafa.post(f"/painel/reservas/{rid}/cancelar", dia=DIA)
    assert r.status_code == 200 and "Horário cancelado" in r.text
    aviso = re.search(r'href="(https://wa\.me/[^"]+)"', r.text).group(1)
    assert aviso.startswith("https://wa.me/5511977776666?text=")
    assert "Preciso%20cancelar" in aviso or "Preciso cancelar" in unquote(aviso)
    assert "cancelou este horário" in c.get(f"/reserva/{token}").text
    assert rafa.post(f"/painel/reservas/{rid}/cancelar").status_code == 409
    # O horário voltou a ficar livre.
    outro, _ = cliente_reserva(epoch(9), "Quem pegou a vaga")
    assert outro


# --- lista de espera -------------------------------------------------------------------------


def test_chamar_quem_esta_na_espera(rafa):
    TestClient(create_app(), follow_redirects=False).post(
        "/rafa-barbeiro/espera",
        data={"s": servico_id(), "dia": DIA, "nome": "Tia Ana Lima", "whatsapp": "(11) 95555-4444"},
    )
    html = rafa.get(f"/painel?dia={DIA}").text
    assert "Lista de espera deste dia" in html and "Tia Ana Lima" in html
    assert "Lista de espera deste dia" not in rafa.get("/painel?dia=2030-03-05").text
    with sistema() as conn:
        eid = str(conn.execute("select id from espera").fetchone()["id"])
    base, texto = destino_whatsapp(rafa.post(f"/painel/espera/{eid}/chamar"))
    assert base == "https://wa.me/5511955554444"
    assert texto.startswith("Oi, Tia!") and "segunda-feira, 4 de março" in texto
    assert "/rafa-barbeiro" in texto
    with sistema() as conn:
        assert conn.execute("select avisada_em from espera").fetchone()["avisada_em"] is not None
    assert "chamada às" in rafa.get(f"/painel?dia={DIA}").text
    ana = Sessao("ana@exemplo.com")
    ana.criar_perfil(slug="ana-nails", nome="Ana")
    assert ana.post(f"/painel/espera/{eid}/chamar").status_code == 404
    assert ana.post(f"/painel/espera/{eid}/apagar").status_code == 404
    assert rafa.post(f"/painel/espera/{eid}/apagar", dia=DIA).status_code == 303
    with sistema() as conn:
        assert conn.execute("select count(*) as n from espera").fetchone()["n"] == 0


# --- mensagens -------------------------------------------------------------------------------


def test_mensagens():
    assert mensagens.primeiro_nome("Maria da Silva") == "Maria"
    assert mensagens.primeiro_nome("") == ""
    assert mensagens.preencher("Oi {nome} {x}", nome="Ana") == "Oi Ana {x}"
    perfil = {
        "nome": "Rafa",
        "mensagem_lembrete": "{nome}|{servico}|{dia}|{hora}|{link}|{profissional}",
        "lembrete_discreto": False,
    }
    reserva = {"cliente_nome": "Maria Souza", "inicio": datetime(2030, 3, 4, 12, 30, tzinfo=UTC)}
    tz = carregar_fuso("America/Sao_Paulo")
    texto = mensagens.lembrete(perfil, reserva, "Corte", tz, "https://x.y/r/1")
    assert texto == "Maria|Corte|segunda-feira, 4 de março|09:30|https://x.y/r/1|Rafa"
    perfil["lembrete_discreto"] = True
    assert mensagens.lembrete(perfil, reserva, "Corte", tz, "l").split("|")[1] == "atendimento"
