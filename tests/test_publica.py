from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from helpers import SP, Sessao

from encaixe import limite
from encaixe.app import create_app
from encaixe.db import hash_do_token, painel, sistema

# Sexta-feira, 09:00 em São Paulo. Antecedência de 2 h e cancelamento até 2 h antes (padrões).
AGORA = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)
SEGUNDA = (2030, 3, 4)


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


def epoch(h, m=0, dia=SEGUNDA):
    return int(datetime(*dia, h, m, tzinfo=SP).timestamp())


def servico_id(nome="Corte"):
    with sistema() as conn:
        return str(
            conn.execute("select id from servicos where nome = %s", (nome,)).fetchone()["id"]
        )


def reservar(c, h, nome="Dona Maria", whatsapp="(11) 97777-6666", email="", s=None, **extra):
    return c.post(
        "/rafa-barbeiro/reservar",
        data={
            "s": s or servico_id(),
            "h": str(h),
            "nome": nome,
            "whatsapp": whatsapp,
            "email": email,
        }
        | extra,
    )


def token_de(resposta) -> str:
    return resposta.headers["location"].split("?")[0].removeprefix("/reserva/")


def reservas():
    with sistema() as conn:
        return conn.execute("select * from reservas order by criada_em").fetchall()


# --- a página e o caminho feliz --------------------------------------------------------------


def test_pagina_lista_os_servicos_do_profissional(rafa):
    r = cliente().get("/rafa-barbeiro")
    assert r.status_code == 200
    for nome in ("Corte", "Barba", "Corte e barba"):
        assert nome in r.text
    assert "Rafa Barbeiro" in r.text and 'content="noindex"' in r.text
    assert "<script" not in r.text.lower()
    assert "Entrar" not in r.text  # o cliente não vê o menu do profissional


def test_endereco_que_nao_existe_ou_e_reservado_da_404(rafa):
    c = cliente()
    for caminho in ("/ninguem", "/wp-admin", "/a", "/UPPER", "/favicon.ico"):
        assert c.get(caminho).status_code == 404, caminho
    assert "Página não encontrada" in c.get("/ninguem").text


def test_dias_e_horarios_respeitam_a_agenda_do_profissional(rafa):
    c = cliente()
    s = servico_id()
    dias = c.get(f"/rafa-barbeiro?s={s}").text
    assert "sexta-feira, 1 de março" in dias and "segunda-feira, 4 de março" in dias
    assert "sábado" not in dias and "domingo" not in dias  # fechados
    horarios = c.get(f"/rafa-barbeiro?s={s}&dia=2030-03-04").text
    for h in ("09:00", "11:30", "14:00", "17:30"):
        assert h in horarios
    assert "12:00<" not in horarios and "13:00<" not in horarios  # almoço
    hoje = c.get(f"/rafa-barbeiro?s={s}&dia=2030-03-01").text
    assert "09:00<" not in hoje and "10:30<" not in hoje  # passou ou falta antecedência (2 h)
    assert "11:00" in hoje


def test_reservar_sem_conta_e_ver_a_reserva(rafa):
    c = cliente()
    r = reservar(c, epoch(9), email="Maria@Exemplo.com")
    assert r.status_code == 303
    assert "Maria" not in r.headers["location"] and "9777" not in r.headers["location"]
    token = token_de(r)
    pagina = c.get(f"/reserva/{token}?nova=1")
    assert pagina.status_code == 200
    assert "Horário confirmado" in pagina.text and "segunda-feira, 4 de março, 09:00" in pagina.text
    assert "Dona Maria" in pagina.text and "Corte" in pagina.text
    assert "https://wa.me/5511988887777?text=" in pagina.text
    assert pagina.headers["referrer-policy"] == "same-origin"
    assert 'content="noindex"' in pagina.text
    (linha,) = reservas()
    assert linha["inicio"] == datetime(2030, 3, 4, 9, 0, tzinfo=SP)
    assert linha["cliente_email"] == "maria@exemplo.com"
    assert linha["cliente_whatsapp"] == "5511977776666"
    assert linha["token_hash"] == bytes.fromhex(hash_do_token(token))


def test_o_link_secreto_e_a_unica_forma_de_ver_a_reserva(rafa):
    c = cliente()
    token = token_de(reservar(c, epoch(9)))
    assert c.get("/reserva/errado").status_code == 404
    assert c.get("/reserva/" + "a" * 32).status_code == 404
    assert c.get("/reserva/" + token[:-1] + ("a" if token[-1] != "a" else "b")).status_code == 404
    # O painel não lista nem expõe o link: só guardamos o hash.
    assert token not in rafa.get("/painel").text


# --- validação e abuso -----------------------------------------------------------------------


def test_dados_ruins_voltam_com_mensagem_e_sem_perder_o_que_foi_digitado(rafa):
    r = reservar(cliente(), epoch(9), nome="M", whatsapp="123", email="x")
    assert r.status_code == 422
    for trecho in ("pelo menos 2 letras", "celular", "e-mail não parece"):
        assert trecho in r.text
    assert 'value="123"' in r.text and "Quase lá" in r.text
    assert reservas() == []


def test_isca_de_robo_e_limite_de_tentativas(rafa):
    assert reservar(cliente(), epoch(9), site="http://spam.example").status_code == 400
    assert reservas() == []
    c = cliente()
    codigos = [reservar(c, epoch(9, 0), nome="Xis").status_code for _ in range(21)]
    assert codigos[0] == 303 and codigos.count(409) == 19 and codigos[-1] == 429


@pytest.mark.parametrize(
    ("h", "esperado"),
    [
        (epoch(9, 7), 404),  # fora da grade
        (epoch(12, 30), 404),  # no almoço
        (epoch(9, dia=(2030, 3, 2)), 404),  # sábado
        (epoch(9, dia=(2030, 3, 1)), 409),  # já passou
        (epoch(10, 30, dia=(2030, 3, 1)), 409),  # falta antecedência
        (epoch(9, dia=(2030, 6, 3)), 409),  # além de 30 dias
        ("abc", 404),
        ("-5", 404),
    ],
)
def test_horario_inventado_ou_fora_das_regras_e_recusado(rafa, h, esperado):
    r = reservar(cliente(), h)
    assert r.status_code == esperado
    assert reservas() == []


def test_servico_de_outro_profissional_ou_inexistente(rafa):
    ana = Sessao("ana@exemplo.com")
    ana.criar_perfil(slug="ana-nails", nome="Ana")
    with sistema() as conn:
        da_ana = str(
            conn.execute(
                "select s.id from servicos s join profissionais p on p.id = s.profissional_id"
                " where p.slug = 'ana-nails' limit 1"
            ).fetchone()["id"]
        )
    r = reservar(cliente(), epoch(9), s=da_ana)
    assert r.status_code == 404 and reservas() == []
    assert cliente().get(f"/rafa-barbeiro?s={da_ana}").text.count("Quase lá") == 0


def test_parametros_estranhos_nao_quebram_a_pagina(rafa):
    c = cliente()
    for consulta in ("?s=lixo", "?dia=lixo", "?pg=abc", "?pg=-1", "?pg=999", "?h=1&dia=2030-03-04"):
        assert c.get("/rafa-barbeiro" + consulta).status_code == 200, consulta


# --- conflito: a última vaga ----------------------------------------------------------------


def test_quem_perde_a_vaga_ve_outros_horarios_sem_redigitar(rafa):
    primeiro, segundo = cliente(), cliente()
    assert reservar(primeiro, epoch(9)).status_code == 303
    r = reservar(segundo, epoch(9), nome="Seu João", whatsapp="(11) 96666-5555")
    assert r.status_code == 409
    assert "acabou de ser ocupado" in r.text
    # Os dados vão em campos escondidos, não na URL, e um toque no novo horário confirma.
    assert 'name="nome" value="Seu João"' in r.text and "(11) 96666-5555" in r.text
    assert 'name="h" value="' + str(epoch(9, 30)) in r.text
    assert 'name="h" value="' + str(epoch(9)) not in r.text
    assert len(reservas()) == 1
    de_novo = reservar(segundo, epoch(9, 30), nome="Seu João", whatsapp="(11) 96666-5555")
    assert de_novo.status_code == 303 and len(reservas()) == 2


def test_horario_ocupado_some_da_lista_e_folga_tambem(rafa):
    reservar(cliente(), epoch(9))
    with painel(rafa.perfil_id()) as conn:
        conn.execute(
            "insert into bloqueios (profissional_id, inicio, fim) values (%s, %s, %s)",
            (
                rafa.perfil_id(),
                datetime(2030, 3, 4, 14, 0, tzinfo=SP),
                datetime(2030, 3, 4, 16, 0, tzinfo=SP),
            ),
        )
    html = cliente().get(f"/rafa-barbeiro?s={servico_id()}&dia=2030-03-04").text
    assert "09:00<" not in html and "09:30" in html
    assert "14:00<" not in html and "15:30<" not in html and "16:00" in html


# --- aula com vagas e lista de espera ---------------------------------------------------------


def test_aula_conta_vagas_e_oferece_lista_de_espera(banco):
    s = Sessao("lu@exemplo.com")
    s.criar_perfil(slug="lu-fit", categoria="treino", nome="Lu Fit")
    aula = servico_id("Aula em grupo")
    with painel(s.perfil_id()) as conn:
        conn.execute("update servicos set vagas = 2 where id = %s", (aula,))
    h = epoch(9)
    for i in range(2):
        r = cliente().post(
            "/lu-fit/reservar",
            data={"s": aula, "h": h, "nome": f"Aluno {i}", "whatsapp": "11977776666"},
        )
        assert r.status_code == 303
    cheia = cliente().post(
        "/lu-fit/reservar", data={"s": aula, "h": h, "nome": "Aluno 3", "whatsapp": "11977776666"}
    )
    assert cheia.status_code == 409
    dia = cliente().get(f"/lu-fit?s={aula}&dia=2030-03-04").text
    assert "09:00 · cheio" in dia and "lista de espera" in dia.lower()
    um_horario = cliente().get(f"/lu-fit?s={aula}&dia=2030-03-04").text
    assert "vaga" in um_horario  # os outros horários mostram quantas vagas restam

    espera = cliente().post(
        "/lu-fit/espera",
        data={"s": aula, "dia": "2030-03-04", "nome": "Tia Ana", "whatsapp": "(11) 95555-4444"},
    )
    assert espera.status_code == 200 and "lista de espera" in espera.text
    repetida = cliente().post(
        "/lu-fit/espera",
        data={"s": aula, "dia": "2030-03-04", "nome": "Tia Ana", "whatsapp": "11955554444"},
    )
    assert repetida.status_code == 200
    with painel(s.perfil_id()) as conn:
        linhas = conn.execute("select * from espera").fetchall()
    assert len(linhas) == 1 and linhas[0]["whatsapp"] == "5511955554444"


def test_espera_valida_dados_dia_e_isca(rafa):
    c = cliente()
    s = servico_id()
    ruim = c.post(
        "/rafa-barbeiro/espera", data={"s": s, "dia": "2030-03-04", "nome": "A", "whatsapp": "1"}
    )
    assert ruim.status_code == 422 and "celular" in ruim.text
    for dia in ("2030-06-01", "2020-01-01", "lixo"):
        r = c.post(
            "/rafa-barbeiro/espera",
            data={"s": s, "dia": dia, "nome": "Ana", "whatsapp": "11955554444"},
        )
        assert r.status_code == 404, dia
    isca = c.post(
        "/rafa-barbeiro/espera",
        data={"s": s, "dia": "2030-03-04", "nome": "Ana", "whatsapp": "11955554444", "site": "x"},
    )
    assert isca.status_code == 400
    with sistema() as conn:
        assert conn.execute("select count(*) as n from espera").fetchone()["n"] == 0


def test_publico_nao_le_a_lista_de_espera(rafa):
    cliente().post(
        "/rafa-barbeiro/espera",
        data={"s": servico_id(), "dia": "2030-03-04", "nome": "Ana", "whatsapp": "11955554444"},
    )
    import psycopg

    from encaixe.db import publico

    with pytest.raises(psycopg.errors.InsufficientPrivilege), publico(rafa.perfil_id()) as conn:
        conn.execute("select * from espera")


# --- cancelar --------------------------------------------------------------------------------


def test_cancelar_libera_o_horario_e_so_vale_uma_vez(rafa):
    c = cliente()
    token = token_de(reservar(c, epoch(9)))
    assert "Cancelar este horário?" in c.get(f"/reserva/{token}/cancelar").text
    r = c.post(f"/reserva/{token}/cancelar")
    assert r.status_code == 303 and r.headers["location"].endswith("cancelada=1")
    pagina = c.get(r.headers["location"]).text
    assert "Você cancelou esta reserva" in pagina and "Reserva cancelada" in pagina
    assert reservas()[0]["status"] == "cancelada_cliente"
    assert c.post(f"/reserva/{token}/cancelar").status_code == 409
    assert reservar(cliente(), epoch(9), nome="Outra pessoa").status_code == 303


def test_depois_do_prazo_o_cancelamento_manda_para_o_whatsapp(rafa, monkeypatch):
    c = cliente()
    token = token_de(reservar(c, epoch(9)))
    # Segunda, 07:30 em SP: falta 1h30 para as 09:00 e o prazo é de 2 h.
    monkeypatch.setattr("encaixe.tempo.agora", lambda: datetime(2030, 3, 4, 7, 30, tzinfo=SP))
    pagina = c.get(f"/reserva/{token}").text
    assert "prazo para cancelar" in pagina and "/cancelar" not in pagina
    confirmar = c.get(f"/reserva/{token}/cancelar")
    assert confirmar.status_code == 200 and "Não dá para cancelar por aqui" in confirmar.text
    assert c.post(f"/reserva/{token}/cancelar").status_code == 409
    assert c.post(f"/reserva/{token}/remarcar", data={"h": epoch(10)}).status_code == 409
    assert reservas()[0]["status"] == "confirmada"


def test_prazo_de_cancelamento_e_inclusivo(rafa, monkeypatch):
    c = cliente()
    token = token_de(reservar(c, epoch(9)))
    monkeypatch.setattr("encaixe.tempo.agora", lambda: datetime(2030, 3, 4, 7, 0, tzinfo=SP))
    assert c.post(f"/reserva/{token}/cancelar").status_code == 303


def test_estados_da_reserva_aparecem_em_texto(rafa, monkeypatch):
    c = cliente()
    casos = {
        "cancelada_profissional": "cancelou este horário",
        "atendida": "Atendimento concluído",
        "faltou": "Marcada como falta",
    }
    for status, texto in casos.items():
        with sistema() as conn:
            conn.execute("truncate reservas cascade")
        token = token_de(reservar(c, epoch(9)))
        with painel(rafa.perfil_id()) as conn:
            conn.execute("update reservas set status = %s", (status,))
        assert texto in c.get(f"/reserva/{token}").text
    with sistema() as conn:
        conn.execute("truncate reservas cascade")
    token = token_de(reservar(c, epoch(9)))
    monkeypatch.setattr("encaixe.tempo.agora", lambda: datetime(2030, 3, 5, 12, 0, tzinfo=SP))
    assert "Este horário já passou" in c.get(f"/reserva/{token}").text


# --- remarcar --------------------------------------------------------------------------------


def test_remarcar_troca_o_horario_e_libera_o_antigo(rafa):
    c = cliente()
    antigo = token_de(reservar(c, epoch(9)))
    assert "Trocar o horário" in c.get(f"/reserva/{antigo}/remarcar").text
    horarios = c.get(f"/reserva/{antigo}/remarcar?dia=2030-03-05").text
    assert "09:00" in horarios
    escolhido = c.get(f"/reserva/{antigo}/remarcar?dia=2030-03-05&h={epoch(10, dia=(2030, 3, 5))}")
    assert "Confirmar o novo horário" in escolhido.text
    r = c.post(f"/reserva/{antigo}/remarcar", data={"h": epoch(10, dia=(2030, 3, 5))})
    assert r.status_code == 303 and r.headers["location"].endswith("remarcada=1")
    novo = r.headers["location"].split("?")[0].removeprefix("/reserva/")
    assert novo != antigo
    assert "terça-feira, 5 de março, 10:00" in c.get(f"/reserva/{novo}").text
    velho = c.get(f"/reserva/{antigo}").text
    assert "trocada por outro horário" in velho and "terça-feira, 5 de março, 10:00" in velho
    status = {str(r_["inicio"].day): r_["status"] for r_ in reservas()}
    assert status == {"4": "remarcada", "5": "confirmada"}
    assert reservar(cliente(), epoch(9), nome="Quem pegou a vaga").status_code == 303


def test_remarcar_para_um_horario_que_cruza_com_o_proprio_funciona(rafa):
    with painel(rafa.perfil_id()) as conn:
        conn.execute("update servicos set duracao_min = 60 where nome = 'Corte'")
    c = cliente()
    antigo = token_de(reservar(c, epoch(9)))
    r = c.post(
        f"/reserva/{antigo}/remarcar", data={"h": epoch(9, 30)}
    )  # 9:30-10:30 cruza 9:00-10:00
    assert r.status_code == 303 and r.headers["location"].endswith("remarcada=1")


def test_remarcar_para_horario_ocupado_nao_muda_nada(rafa):
    c = cliente()
    antigo = token_de(reservar(c, epoch(9)))
    reservar(cliente(), epoch(10), nome="Outro")
    r = c.post(f"/reserva/{antigo}/remarcar", data={"h": epoch(10)})
    assert r.status_code == 303 and "/remarcar" in r.headers["location"]
    assert [x["status"] for x in reservas()] == ["confirmada", "confirmada"]
    mesmo = c.post(f"/reserva/{antigo}/remarcar", data={"h": epoch(9)})
    assert mesmo.status_code == 409


def test_reserva_trocada_ou_cancelada_nao_remarca_de_novo(rafa):
    c = cliente()
    antigo = token_de(reservar(c, epoch(9)))
    c.post(f"/reserva/{antigo}/remarcar", data={"h": epoch(11)})
    assert c.post(f"/reserva/{antigo}/remarcar", data={"h": epoch(14)}).status_code == 409
    assert c.get(f"/reserva/{antigo}/remarcar").status_code == 409


# --- apagar os dados -------------------------------------------------------------------------


def test_apagar_dados_so_depois_de_cancelar_ou_do_atendimento(rafa):
    c = cliente()
    token = token_de(reservar(c, epoch(9), email="m@exemplo.com"))
    assert c.post(f"/reserva/{token}/apagar").status_code == 409
    assert "Apagar meus dados" not in c.get(f"/reserva/{token}").text
    c.post(f"/reserva/{token}/cancelar")
    assert "Apagar meus dados" in c.get(f"/reserva/{token}").text
    r = c.post(f"/reserva/{token}/apagar")
    assert r.status_code == 303
    (linha,) = reservas()
    assert linha["cliente_whatsapp"] is None and linha["cliente_email"] is None
    assert linha["cliente_nome"] == "Cliente removido" and linha["anonimizada_em"] is not None
    pagina = c.get(f"/reserva/{token}").text
    assert "Dona Maria" not in pagina and "Apagar meus dados" not in pagina
    assert c.post(f"/reserva/{token}/apagar").status_code == 409


# --- detalhes de produto ---------------------------------------------------------------------


def test_reserva_continua_legivel_se_o_servico_for_desativado(rafa):
    c = cliente()
    token = token_de(reservar(c, epoch(9)))
    with painel(rafa.perfil_id()) as conn:
        conn.execute("update servicos set ativo = false")
    assert "Corte" in c.get(f"/reserva/{token}").text
    assert (
        "Ainda não dá para marcar" in c.get("/rafa-barbeiro").text
        or "O que você quer" in c.get("/rafa-barbeiro").text
    )


def test_fuso_do_profissional_vale_na_tela(rafa):
    with painel(rafa.perfil_id()) as conn:
        conn.execute("update profissionais set fuso = 'America/Manaus'")
    manaus = datetime(2030, 3, 4, 9, 0, tzinfo=UTC) + timedelta(hours=4)
    h = int(manaus.timestamp())
    html = cliente().get(f"/rafa-barbeiro?s={servico_id()}&dia=2030-03-04").text
    assert f"h={h}" in html and "09:00" in html and "fuso de Amazonas" in html


def test_um_servico_so_pula_a_escolha_do_servico(banco):
    s = Sessao("zeca@exemplo.com")
    s.criar_perfil(slug="zeca", categoria="outro", nome="Zeca")
    html = cliente().get("/zeca").text
    assert "Escolha o dia" in html and "Trocar serviço" not in html


def test_reserva_de_um_profissional_nao_aparece_no_outro(rafa):
    ana = Sessao("ana@exemplo.com")
    ana.criar_perfil(slug="ana-nails", nome="Ana")
    reservar(cliente(), epoch(9))
    html = cliente().get(f"/ana-nails?s={servico_id()}").text  # serviço do Rafa na página da Ana
    assert "Quase lá" not in html
    horarios = cliente().get("/ana-nails").text
    assert "Dona Maria" not in horarios
    token = token_de(reservar(cliente(), epoch(10)))
    parsed = parse_qs(urlsplit("/x?a=1").query)
    assert parsed and token
