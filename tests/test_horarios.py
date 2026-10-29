from datetime import UTC, date, datetime, time, timedelta

import pytest

from encaixe.horarios import (
    Intervalo,
    Ocupada,
    Regras,
    Servico,
    carregar_fuso,
    horarios_do_dia,
    inicios_do_dia,
    pode_cancelar,
)

SEG = date(2030, 3, 4)  # segunda-feira
AGORA = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)
CORTE = Servico("corte", duracao_min=30, folga_min=0, vagas=1)


def regras(fuso="America/Sao_Paulo", passo=30, faixas=((time(9), time(12)),), **extra):
    base = dict(
        fuso=fuso,
        passo_min=passo,
        antecedencia_min=120,
        dias_a_frente=30,
        cancelar_ate_min=120,
        semana={d: tuple(faixas) for d in range(7)},
    )
    base.update(extra)
    return Regras(**base)


def utc(dia, hora, minuto=0, fuso="America/Sao_Paulo"):
    return datetime.combine(dia, time(hora, minuto), tzinfo=carregar_fuso(fuso)).astimezone(UTC)


def test_grade_simples_no_relogio_do_profissional():
    inicios = inicios_do_dia(regras(), CORTE, SEG)
    assert len(inicios) == 6
    assert inicios[0] == utc(SEG, 9)
    assert inicios[-1] == utc(SEG, 11, 30)


def test_ultimo_horario_precisa_terminar_dentro_da_faixa():
    corte_longo = Servico("longo", duracao_min=45, folga_min=0, vagas=1)
    inicios = inicios_do_dia(regras(), corte_longo, SEG)
    assert inicios[-1] == utc(SEG, 11, 0)  # 11:30 + 45 min passaria do meio-dia


def test_almoco_e_a_lacuna_entre_faixas():
    r = regras(faixas=((time(9), time(12)), (time(14), time(16))))
    horas = [
        i.astimezone(carregar_fuso(r.fuso)).strftime("%H:%M") for i in inicios_do_dia(r, CORTE, SEG)
    ]
    assert "12:00" not in horas and "13:30" not in horas
    assert horas[6] == "14:00"


def test_faixas_que_se_sobrepoem_nao_duplicam_horario():
    r = regras(faixas=((time(9), time(11)), (time(10), time(12))))
    assert len(inicios_do_dia(r, CORTE, SEG)) == 6


def test_dia_sem_faixa_nao_tem_horario():
    r = regras()
    r = Regras(**{**r.__dict__, "semana": {}})
    assert inicios_do_dia(r, CORTE, SEG) == []


def test_horario_de_verao_nos_eua_tira_uma_hora_da_grade():
    # 10/03/2024: em Nova York o relógio pulou de 02:00 para 03:00.
    r = regras("America/New_York", passo=60, faixas=((time(0), time(6)),))
    hora = Servico("h", 60, 0, 1)
    assert len(inicios_do_dia(r, hora, date(2024, 3, 9))) == 6  # dia normal
    assert len(inicios_do_dia(r, hora, date(2024, 3, 10))) == 5  # salto


def test_fim_do_horario_de_verao_nos_eua_poe_uma_hora_a_mais():
    # 03/11/2024: o relógio voltou de 02:00 para 01:00, a hora 01:00 acontece duas vezes.
    r = regras("America/New_York", passo=60, faixas=((time(0), time(6)),))
    hora = Servico("h", 60, 0, 1)
    assert len(inicios_do_dia(r, hora, date(2024, 11, 3))) == 7


def test_ultimo_horario_de_verao_do_brasil_2018():
    # 04/11/2018: à meia-noite o relógio de São Paulo foi para 01:00 (00:00 não existiu).
    r = regras("America/Sao_Paulo", passo=60, faixas=((time(0), time(3)),))
    hora = Servico("h", 60, 0, 1)
    inicios = inicios_do_dia(r, hora, date(2018, 11, 4))
    assert len(inicios) == 2
    assert all(i.astimezone(carregar_fuso(r.fuso)).hour >= 1 for i in inicios)


def test_fuso_desconhecido_e_recusado():
    for nome in ("", "Marte/Olimpo", "../etc/passwd"):
        with pytest.raises(ValueError):
            carregar_fuso(nome)


def por_inicio(horarios):
    return {h.inicio: h for h in horarios}


def test_antecedencia_passado_e_horizonte():
    r = regras()
    agora = utc(SEG, 10, 30)  # 10h30 no relógio de lá
    h = por_inicio(horarios_do_dia(r, CORTE, SEG, agora))
    assert h[utc(SEG, 9)].motivo == "passou"
    assert h[utc(SEG, 10, 30)].motivo == "passou"  # começa agora: já foi
    assert h[utc(SEG, 11)].motivo == "antecedencia"  # menos de 2 h
    longe = date(2030, 6, 3)
    assert {x.motivo for x in horarios_do_dia(r, CORTE, longe, AGORA)} == {"alem_do_horizonte"}
    assert horarios_do_dia(r, CORTE, SEG, AGORA)[0].motivo is None


def test_reserva_ocupa_o_horario_e_a_folga_tambem():
    r = regras()
    com_folga = Servico("corte", 30, 15, 1)
    ocupada = Ocupada("corte", utc(SEG, 9), utc(SEG, 9, 45))  # 9:00-9:30 + 15 min de folga
    h = por_inicio(horarios_do_dia(r, com_folga, SEG, AGORA, [ocupada]))
    assert h[utc(SEG, 9)].motivo == "ocupado"
    assert h[utc(SEG, 9, 30)].motivo == "ocupado"  # a folga da anterior vai até 9:45
    assert h[utc(SEG, 10)].motivo is None


def test_horario_colado_na_reserva_sem_folga_e_livre():
    ocupada = Ocupada("corte", utc(SEG, 9), utc(SEG, 9, 30))
    h = por_inicio(horarios_do_dia(regras(), CORTE, SEG, AGORA, [ocupada]))
    assert h[utc(SEG, 9, 30)].motivo is None


def test_bloqueio_tira_o_horario():
    folga = Intervalo(utc(SEG, 10), utc(SEG, 11))
    h = por_inicio(horarios_do_dia(regras(), CORTE, SEG, AGORA, bloqueios=[folga]))
    assert h[utc(SEG, 10)].motivo == "bloqueado"
    assert h[utc(SEG, 10, 30)].motivo == "bloqueado"
    assert h[utc(SEG, 11)].motivo is None
    assert h[utc(SEG, 9, 30)].motivo is None


def test_aula_conta_vagas_e_lota():
    aula = Servico("aula", 60, 0, 3)
    r = regras(passo=60)
    ocupadas = [Ocupada("aula", utc(SEG, 9), utc(SEG, 10)) for _ in range(2)]
    h = por_inicio(horarios_do_dia(r, aula, SEG, AGORA, ocupadas))
    assert h[utc(SEG, 9)].vagas_livres == 1 and h[utc(SEG, 9)].motivo is None
    ocupadas.append(Ocupada("aula", utc(SEG, 9), utc(SEG, 10)))
    h = por_inicio(horarios_do_dia(r, aula, SEG, AGORA, ocupadas))
    assert h[utc(SEG, 9)].vagas_livres == 0 and h[utc(SEG, 9)].motivo == "lotado"


def test_aula_nao_divide_horario_com_outro_servico_nem_com_outro_inicio():
    aula = Servico("aula", 60, 0, 3)
    r = regras(passo=30)
    do_corte = Ocupada("corte", utc(SEG, 9), utc(SEG, 9, 30))
    h = por_inicio(horarios_do_dia(r, aula, SEG, AGORA, [do_corte]))
    assert h[utc(SEG, 9)].motivo == "ocupado"
    assert h[utc(SEG, 9, 30)].motivo is None
    outra_aula = Ocupada("aula", utc(SEG, 9, 30), utc(SEG, 10, 30))
    h = por_inicio(horarios_do_dia(r, aula, SEG, AGORA, [outra_aula]))
    assert h[utc(SEG, 9)].motivo == "ocupado"  # 9:00-10:00 cruza a aula das 9:30


def test_cancelar_vale_ate_o_limite_exato():
    r = regras()  # cancelar até 120 min antes
    inicio = utc(SEG, 12)
    assert pode_cancelar(r, inicio, inicio - timedelta(minutes=120))
    assert not pode_cancelar(r, inicio, inicio - timedelta(minutes=119))
