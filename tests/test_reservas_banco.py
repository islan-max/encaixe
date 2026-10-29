"""O banco é quem garante: sem reserva dupla, aula com vagas, reserva imutável e RLS."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta

import psycopg
import pytest

from encaixe.db import hash_do_token, painel, publico, sistema
from encaixe.horarios import Intervalo, Ocupada, Regras, Servico, horarios_do_dia
from encaixe.reservas import ReservaRecusada, criar, novo_token

DIA = datetime(2030, 3, 4, 12, 0, tzinfo=UTC)  # 09:00 em São Paulo


def hora(h, m=0):
    return DIA.replace(hour=12 + (h - 9), minute=m)


def reservar(pro, servico, inicio, nome="Cliente", **extra):
    with publico(pro) as conn:
        return criar(
            conn,
            profissional_id=pro,
            servico_id=servico,
            inicio=inicio,
            cliente_nome=nome,
            cliente_whatsapp="5511988887777",
            cliente_email=None,
            token=novo_token(),
            **extra,
        )


def test_reserva_recebe_fim_e_estado_do_banco_e_nao_do_cliente(novo_profissional, novo_servico):
    pro = novo_profissional()
    corte = novo_servico(pro, duracao=45, folga=15)
    reservar(pro, corte, hora(9))
    with painel(pro) as conn:
        r = conn.execute("select * from reservas").fetchone()
    assert r["fim"] == hora(9, 45)
    assert r["ocupa_ate"] == hora(10)
    assert r["status"] == "confirmada"


def test_painel_nao_consegue_inserir_reserva_ja_atendida(novo_profissional, novo_servico):
    pro = novo_profissional()
    corte = novo_servico(pro)
    with painel(pro) as conn:
        conn.execute(
            "insert into reservas (profissional_id, servico_id, inicio, fim, ocupa_ate, status,"
            " cliente_nome, cliente_whatsapp, token_hash) values (%s, %s, %s, %s, %s, 'atendida',"
            " 'X', '5511988887777', decode(%s, 'hex'))",
            (pro, corte, hora(9), hora(15), hora(15), "ab" * 32),
        )
        r = conn.execute("select status, fim from reservas").fetchone()
    assert r["status"] == "confirmada" and r["fim"] == hora(9, 30)


def test_mesmo_horario_e_recusado(novo_profissional, novo_servico):
    pro = novo_profissional()
    corte = novo_servico(pro)
    reservar(pro, corte, hora(9))
    with pytest.raises(ReservaRecusada) as erro:
        reservar(pro, corte, hora(9))
    assert erro.value.motivo == "ocupado"


def test_horario_que_cruza_e_recusado_e_o_colado_passa(novo_profissional, novo_servico):
    pro = novo_profissional()
    corte = novo_servico(pro)
    reservar(pro, corte, hora(9))
    with pytest.raises(ReservaRecusada):
        reservar(pro, corte, hora(9, 15))
    reservar(pro, corte, hora(9, 30))


def test_folga_conta_como_ocupada(novo_profissional, novo_servico):
    pro = novo_profissional()
    com_folga = novo_servico(pro, duracao=30, folga=15)
    reservar(pro, com_folga, hora(9))
    with pytest.raises(ReservaRecusada):
        reservar(pro, com_folga, hora(9, 30))
    reservar(pro, com_folga, hora(10))


def test_servicos_diferentes_do_mesmo_profissional_tambem_se_excluem(
    novo_profissional, novo_servico
):
    pro = novo_profissional()
    corte = novo_servico(pro, nome="Corte")
    barba = novo_servico(pro, nome="Barba", duracao=20)
    reservar(pro, corte, hora(9))
    with pytest.raises(ReservaRecusada):
        reservar(pro, barba, hora(9, 15))


def test_profissionais_diferentes_nao_se_atrapalham(novo_profissional, novo_servico):
    a, b = novo_profissional(), novo_profissional()
    reservar(a, novo_servico(a), hora(9))
    reservar(b, novo_servico(b), hora(9))


def test_cancelar_libera_o_horario(novo_profissional, novo_servico):
    pro = novo_profissional()
    corte = novo_servico(pro)
    primeira = reservar(pro, corte, hora(9))
    with painel(pro) as conn:
        conn.execute(
            "update reservas set status = 'cancelada_profissional' where id = %s", (primeira["id"],)
        )
    reservar(pro, corte, hora(9))


def test_bloqueio_recusa_reserva(novo_profissional, novo_servico):
    pro = novo_profissional()
    corte = novo_servico(pro)
    with painel(pro) as conn:
        conn.execute(
            "insert into bloqueios (profissional_id, inicio, fim, motivo)"
            " values (%s, %s, %s, 'médico')",
            (pro, hora(10), hora(12)),
        )
    with pytest.raises(ReservaRecusada) as erro:
        reservar(pro, corte, hora(11))
    assert erro.value.motivo == "bloqueado"
    reservar(pro, corte, hora(9, 30))  # termina às 10:00, colado no bloqueio


def test_servico_inativo_ou_de_outro_profissional_e_recusado(novo_profissional, novo_servico):
    a, b = novo_profissional(), novo_profissional()
    inativo = novo_servico(a, ativo=False)
    de_b = novo_servico(b)
    for servico in (inativo, de_b, str(uuid.uuid4())):
        with pytest.raises(ReservaRecusada) as erro:
            reservar(a, servico, hora(9))
        assert erro.value.motivo == "servico_invalido"


def test_aula_aceita_ate_o_limite_de_vagas(novo_profissional, novo_servico):
    pro = novo_profissional()
    aula = novo_servico(pro, nome="Funcional", duracao=60, vagas=3)
    for i in range(3):
        reservar(pro, aula, hora(9), nome=f"Aluno {i}")
    with pytest.raises(ReservaRecusada) as erro:
        reservar(pro, aula, hora(9), nome="Aluno 4")
    assert erro.value.motivo == "lotado"


def test_aula_nao_divide_horario_com_atendimento_nem_com_outro_inicio(
    novo_profissional, novo_servico
):
    pro = novo_profissional()
    aula = novo_servico(pro, nome="Funcional", duracao=60, vagas=3)
    avaliacao = novo_servico(pro, nome="Avaliação", duracao=30)
    reservar(pro, aula, hora(9))
    with pytest.raises(ReservaRecusada) as erro:
        reservar(pro, avaliacao, hora(9, 30))
    assert erro.value.motivo == "ocupado"
    with pytest.raises(ReservaRecusada) as erro:
        reservar(pro, aula, hora(9, 30))  # outra aula começando no meio desta
    assert erro.value.motivo == "ocupado"


def test_corrida_pela_ultima_vaga_de_atendimento_tem_um_vencedor(novo_profissional, novo_servico):
    pro = novo_profissional()
    corte = novo_servico(pro)

    def tentar(i):
        try:
            reservar(pro, corte, hora(9), nome=f"Cliente {i}")
            return "ok"
        except ReservaRecusada as erro:
            return erro.motivo

    with ThreadPoolExecutor(max_workers=12) as pool:
        resultados = list(pool.map(tentar, range(12)))
    assert resultados.count("ok") == 1
    assert resultados.count("ocupado") == 11
    with sistema() as conn:
        assert conn.execute("select count(*) as n from reservas").fetchone()["n"] == 1


def test_corrida_por_vagas_de_aula_nunca_passa_do_limite(novo_profissional, novo_servico):
    pro = novo_profissional()
    aula = novo_servico(pro, nome="Funcional", duracao=60, vagas=3)

    def tentar(i):
        try:
            reservar(pro, aula, hora(9), nome=f"Aluno {i}")
            return "ok"
        except ReservaRecusada as erro:
            return erro.motivo

    with ThreadPoolExecutor(max_workers=12) as pool:
        resultados = list(pool.map(tentar, range(12)))
    assert resultados.count("ok") == 3
    assert resultados.count("lotado") == 9


def test_reserva_nao_pode_ser_alterada(novo_profissional, novo_servico):
    pro = novo_profissional()
    r = reservar(pro, novo_servico(pro), hora(9))
    for sql in (
        "update reservas set inicio = inicio + interval '1 hour'",
        "update reservas set servico_id = servico_id, token_hash = decode('00', 'hex')",
        "update reservas set cliente_nome = 'Outro nome'",
    ):
        with pytest.raises(psycopg.DatabaseError) as erro, painel(pro) as conn:
            conn.execute(sql)
        assert erro.value.sqlstate in ("EN010", "EN012")
    assert r["id"]


def test_estados_so_andam_para_frente(novo_profissional, novo_servico):
    pro = novo_profissional()
    r = reservar(pro, novo_servico(pro), hora(9))
    with painel(pro) as conn:
        conn.execute(
            "update reservas set status = 'cancelada_profissional' where id = %s", (r["id"],)
        )
    with pytest.raises(psycopg.DatabaseError) as erro, painel(pro) as conn:
        conn.execute("update reservas set status = 'confirmada' where id = %s", (r["id"],))
    assert erro.value.sqlstate == "EN011"


def test_dados_do_cliente_so_mudam_para_serem_apagados(novo_profissional, novo_servico):
    pro = novo_profissional()
    r = reservar(pro, novo_servico(pro), hora(9))
    with painel(pro) as conn:
        conn.execute(
            "update reservas set cliente_nome = 'Cliente removido', cliente_whatsapp = null,"
            " anonimizada_em = now() where id = %s",
            (r["id"],),
        )
        linha = conn.execute("select * from reservas").fetchone()
    assert linha["cliente_whatsapp"] is None and linha["anonimizada_em"] is not None


# --- RLS: o caminho proibido ---------------------------------------------------------------


def test_painel_de_um_profissional_nao_ve_o_do_outro(novo_profissional, novo_servico):
    a, b = novo_profissional(), novo_profissional()
    sa, sb = novo_servico(a), novo_servico(b)
    ra = reservar(a, sa, hora(9))
    reservar(b, sb, hora(9))
    with painel(a) as conn:
        assert [str(r["id"]) for r in conn.execute("select id from reservas")] == [str(ra["id"])]
        assert [str(r["id"]) for r in conn.execute("select id from servicos")] == [sa]
        assert [str(r["id"]) for r in conn.execute("select id from profissionais")] == [a]
        alterou = conn.execute("update servicos set nome = 'Invadido' where id = %s", (sb,))
        assert alterou.rowcount == 0
        apagou = conn.execute("delete from servicos where id = %s", (sb,))
        assert apagou.rowcount == 0


def test_painel_nao_cria_dado_em_nome_de_outro_profissional(novo_profissional):
    a, b = novo_profissional(), novo_profissional()
    with pytest.raises(psycopg.errors.InsufficientPrivilege), painel(a) as conn:
        conn.execute(
            "insert into servicos (profissional_id, nome, duracao_min) values (%s, 'Falso', 30)",
            (b,),
        )


def test_publico_nao_le_reservas_sem_o_link_secreto(novo_profissional, novo_servico):
    pro = novo_profissional()
    token = novo_token()
    with publico(pro) as conn:
        criar(
            conn,
            profissional_id=pro,
            servico_id=novo_servico(pro),
            inicio=hora(9),
            cliente_nome="Dona Maria",
            cliente_whatsapp="5511988887777",
            cliente_email=None,
            token=token,
        )
    with publico(pro) as conn:
        assert conn.execute("select * from reservas").fetchall() == []
    with publico(pro, token="token-errado") as conn:
        assert conn.execute("select * from reservas").fetchall() == []
    with publico(pro, token=token) as conn:
        assert [r["cliente_nome"] for r in conn.execute("select * from reservas")] == ["Dona Maria"]


def test_achar_o_profissional_pelo_slug_ou_pelo_link_secreto(novo_profissional, novo_servico):
    pro = novo_profissional("rafa-barbeiro")
    token = novo_token()
    with publico(pro) as conn:
        criar(
            conn,
            profissional_id=pro,
            servico_id=novo_servico(pro),
            inicio=hora(9),
            cliente_nome="Cliente",
            cliente_whatsapp="5511988887777",
            cliente_email=None,
            token=token,
        )
    with sistema() as conn:
        por_slug = "select profissional_id_por_slug(%s) as id"
        por_token = "select profissional_id_da_reserva(decode(%s, 'hex')) as id"
        assert str(conn.execute(por_slug, ("rafa-barbeiro",)).fetchone()["id"]) == pro
        assert conn.execute(por_slug, ("nao-existe",)).fetchone()["id"] is None
        assert str(conn.execute(por_token, (hash_do_token(token),)).fetchone()["id"]) == pro
        assert conn.execute(por_token, (hash_do_token("errado"),)).fetchone()["id"] is None
    # Quem não é o dono do banco não pode usar essas buscas para sondar slugs ou links.
    with pytest.raises(psycopg.errors.InsufficientPrivilege), publico(pro) as conn:
        conn.execute("select profissional_id_por_slug('rafa-barbeiro')")


def test_publico_ve_ocupacao_mas_nao_dados_pessoais(novo_profissional, novo_servico):
    pro = novo_profissional()
    reservar(pro, novo_servico(pro), hora(9), nome="Dona Maria")
    with publico(pro) as conn:
        linhas = conn.execute("select * from ocupacoes_publicas").fetchall()
        assert len(linhas) == 1 and "cliente_nome" not in linhas[0]
    with pytest.raises(psycopg.errors.UndefinedColumn), publico(pro) as conn:
        conn.execute("select cliente_nome from ocupacoes_publicas")


def test_publico_nao_cria_reserva_em_nome_de_outro_profissional(novo_profissional, novo_servico):
    a, b = novo_profissional(), novo_profissional()
    servico_b = novo_servico(b)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), publico(a) as conn:
        conn.execute(
            "insert into reservas (profissional_id, servico_id, inicio, cliente_nome,"
            " cliente_whatsapp, token_hash) values (%s, %s, %s, 'X', '5511988887777',"
            " decode(%s, 'hex'))",
            (b, servico_b, hora(9), "cd" * 32),
        )


def test_publico_so_cancela_pela_funcao_e_nunca_atualiza_direto(novo_profissional, novo_servico):
    pro = novo_profissional()
    token = novo_token()
    with publico(pro) as conn:
        r = criar(
            conn,
            profissional_id=pro,
            servico_id=novo_servico(pro),
            inicio=hora(9),
            cliente_nome="Cliente",
            cliente_whatsapp="5511988887777",
            cliente_email=None,
            token=token,
        )
    # O papel público não atualiza nada direto: nem o estado, nem o horário, nem os dados.
    for sql in (
        "update reservas set status = 'atendida'",
        "update reservas set inicio = inicio + interval '1 day'",
        "update reservas set cliente_nome = 'Outro'",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege), publico(pro, token) as conn:
            conn.execute(sql)
    # O que ele pode é pedir as transições certas, e só da reserva de quem tem o link.
    with publico(pro, token) as conn:
        assert (
            conn.execute(
                "select cancelar_pelo_cliente(decode(%s, 'hex')) as ok", (hash_do_token("errado"),)
            ).fetchone()["ok"]
            is False
        )
        assert (
            conn.execute(
                "select cancelar_pelo_cliente(decode(%s, 'hex')) as ok", (hash_do_token(token),)
            ).fetchone()["ok"]
            is True
        )
        assert (
            conn.execute(
                "select cancelar_pelo_cliente(decode(%s, 'hex')) as ok", (hash_do_token(token),)
            ).fetchone()["ok"]
            is False
        )
        assert (
            conn.execute("select status from reservas where id = %s", (r["id"],)).fetchone()[
                "status"
            ]
            == "cancelada_cliente"
        )


def test_publico_nao_le_servico_inativo_nem_dados_de_outro_profissional(
    novo_profissional, novo_servico
):
    a, b = novo_profissional(), novo_profissional()
    novo_servico(a, nome="Ativo")
    novo_servico(a, nome="Escondido", ativo=False)
    novo_servico(b, nome="De outro")
    with publico(a) as conn:
        assert [s["nome"] for s in conn.execute("select nome from servicos")] == ["Ativo"]


def test_slug_invalido_e_recusado(banco):
    for slug in ("a", "-ab", "ab-", "Ab", "a b", "a" * 41, "admin/x"):
        with pytest.raises(psycopg.errors.CheckViolation), sistema() as conn:
            conn.execute(
                "insert into profissionais (slug, nome, categoria, whatsapp) values"
                " (%s, 'Nome', 'outro', '5511999998888')",
                (slug,),
            )


# --- O que a tela mostra tem de bater com o que o banco aceita --------------------------------


def test_grade_do_python_e_o_gatilho_do_banco_concordam(novo_profissional, novo_servico):
    pro = novo_profissional()
    corte = novo_servico(pro, nome="Corte", duracao=30, folga=15)
    aula = novo_servico(pro, nome="Aula", duracao=60, vagas=2)
    reservar(pro, corte, hora(9))
    reservar(pro, aula, hora(11))
    with painel(pro) as conn:
        conn.execute(
            "insert into bloqueios (profissional_id, inicio, fim) values (%s, %s, %s)",
            (pro, hora(14), hora(15)),
        )
    regras = Regras(
        fuso="UTC",
        passo_min=15,
        antecedencia_min=0,
        dias_a_frente=3650,
        cancelar_ate_min=0,
        semana={d: ((time(12), time(20)),) for d in range(7)},  # 09:00-17:00 em São Paulo
    )
    agora = DIA - timedelta(days=30)
    with publico(pro) as conn:
        ocupadas = [
            Ocupada(str(o["servico_id"]), o["inicio"], o["ocupa_ate"])
            for o in conn.execute("select * from ocupacoes_publicas")
        ]
        bloqueios = [
            Intervalo(b["inicio"], b["fim"])
            for b in conn.execute("select * from bloqueios_publicos")
        ]
    for sid, duracao, folga, vagas in ((corte, 30, 15, 1), (aula, 60, 0, 2)):
        servico = Servico(sid, duracao, folga, vagas)
        for h in horarios_do_dia(regras, servico, date(2030, 3, 4), agora, ocupadas, bloqueios):
            esperado = {
                None: None,
                "ocupado": "ocupado",
                "bloqueado": "bloqueado",
                "lotado": "lotado",
            }[h.motivo]
            with publico(pro) as conn:
                try:
                    with conn.transaction(force_rollback=True):
                        criar(
                            conn,
                            profissional_id=pro,
                            servico_id=sid,
                            inicio=h.inicio,
                            cliente_nome="Teste",
                            cliente_whatsapp="5511988887777",
                            cliente_email=None,
                            token=novo_token(),
                        )
                    obtido = None
                except ReservaRecusada as erro:
                    obtido = erro.motivo
            assert obtido == esperado, (sid, h)
