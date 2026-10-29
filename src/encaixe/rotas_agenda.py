"""A agenda do dia: ver quem vem, lembrar com um toque, marcar atendimento e chamar a espera."""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from encaixe import contas, mensagens, telefone, tempo
from encaixe.agenda import limites_no_fuso
from encaixe.config import carregar
from encaixe.db import painel, sistema
from encaixe.formularios import data, uuid_valido
from encaixe.horarios import carregar_fuso
from encaixe.reservas import token_da_reserva
from encaixe.rotas_painel import Protegido, exigir_perfil
from encaixe.web import exigir_usuario, ir_para, pagina

roteador = APIRouter(prefix="/painel")
Campo = Annotated[str, Form(max_length=300)]
DIAS_NA_FAIXA = 7


def _volta(dia: str, extra: str = "") -> str:
    return "/painel" + (f"?dia={dia}" if data(dia) else "") + extra


def _link_da_reserva(reserva_id) -> str:
    return f"{carregar().base_url}/reserva/{token_da_reserva(str(reserva_id))}"


def _whatsapp(numero: str, texto: str) -> RedirectResponse:
    return RedirectResponse(telefone.link_whatsapp(numero, texto), status_code=303)


@roteador.get("")
def agenda(request: Request, dia: str = ""):
    usuario = exigir_usuario(request)
    restantes = None
    if usuario.get("email"):
        with sistema() as conn:
            restantes = contas.codigos_restantes(conn, usuario["id"])
    if not usuario["profissional_id"]:
        return pagina(request, "painel_vazio.html", codigos_restantes=restantes)
    agora = tempo.agora()
    with painel(str(usuario["profissional_id"])) as conn:
        perfil = conn.execute("select * from profissionais").fetchone()
        tz = carregar_fuso(perfil["fuso"])
        hoje = agora.astimezone(tz).date()
        escolhido = data(dia) or hoje
        inicio, fim = limites_no_fuso(tz, escolhido)
        reservas = conn.execute(
            "select r.*, s.nome as servico_nome from reservas r"
            " join servicos s on s.id = r.servico_id"
            " where r.inicio >= %s and r.inicio < %s and r.status <> 'remarcada' order by r.inicio",
            (inicio, fim),
        ).fetchall()
        espera = conn.execute(
            "select e.*, s.nome as servico_nome from espera e"
            " join servicos s on s.id = e.servico_id"
            " where e.dia = %s order by e.criada_em",
            (escolhido,),
        ).fetchall()
        faixa_ini, _ = limites_no_fuso(tz, hoje)
        _, faixa_fim = limites_no_fuso(tz, hoje + timedelta(days=DIAS_NA_FAIXA - 1))
        # Agrupa por dia no relógio do profissional aqui, não no banco: não depende do banco
        # conhecer o fuso (o Postgres embutido do Windows não conhece).
        por_dia: dict = {}
        for linha in conn.execute(
            "select inicio from reservas where status = 'confirmada' and inicio >= %s"
            " and inicio < %s",
            (faixa_ini, faixa_fim),
        ):
            dia_local = linha["inicio"].astimezone(tz).date()
            por_dia[dia_local] = por_dia.get(dia_local, 0) + 1
        total = conn.execute("select count(*) as n from reservas").fetchone()["n"]
        n_servicos = conn.execute("select count(*) as n from servicos where ativo").fetchone()["n"]
    faixa = [
        {"dia": hoje + timedelta(days=i), "n": por_dia.get(hoje + timedelta(days=i), 0)}
        for i in range(DIAS_NA_FAIXA)
    ]
    return pagina(
        request,
        "painel.html",
        secao="inicio",
        perfil=perfil,
        tz=tz,
        hoje=hoje,
        escolhido=escolhido,
        anterior=escolhido - timedelta(days=1),
        proximo=escolhido + timedelta(days=1),
        reservas=reservas,
        espera=espera,
        faixa=faixa,
        agora=agora,
        link=f"{carregar().base_url}/{perfil['slug']}",
        total=total,
        n_servicos=n_servicos,
        codigos_restantes=restantes,
        telefone=telefone.formatar,
    )


def _reserva_ou_404(conn, rid: str) -> dict:
    ident = uuid_valido(rid)
    linha = (
        conn.execute(
            "select r.*, s.nome as servico_nome from reservas r"
            " join servicos s on s.id = r.servico_id where r.id = %s",
            (ident,),
        ).fetchone()
        if ident
        else None
    )
    if linha is None:
        raise HTTPException(404)
    return linha


@roteador.post("/reservas/{rid}/lembrar", dependencies=Protegido)
def lembrar(request: Request, rid: str):
    pro = exigir_perfil(request)
    with painel(pro) as conn:
        reserva = _reserva_ou_404(conn, rid)
        perfil = conn.execute("select * from profissionais").fetchone()
        if reserva["status"] != "confirmada" or not reserva["cliente_whatsapp"]:
            raise HTTPException(
                409, "Só dá para lembrar uma reserva ativa que ainda tem o WhatsApp."
            )
        tz = carregar_fuso(perfil["fuso"])
        texto = mensagens.lembrete(
            perfil, reserva, reserva["servico_nome"], tz, _link_da_reserva(reserva["id"])
        )
        conn.execute("update reservas set lembrete_em = now() where id = %s", (reserva["id"],))
    return _whatsapp(reserva["cliente_whatsapp"], texto)


@roteador.post("/reservas/{rid}/estado", dependencies=Protegido)
def mudar_estado(request: Request, rid: str, novo: Campo = "", dia: Campo = ""):
    pro = exigir_perfil(request)
    if novo not in ("atendida", "faltou"):
        raise HTTPException(422, "Escolha atendida ou faltou.")
    with painel(pro) as conn:
        reserva = _reserva_ou_404(conn, rid)
        if reserva["inicio"] > tempo.agora():
            raise HTTPException(409, "Só dá para marcar depois que o horário começou.")
        if reserva["status"] not in ("confirmada", "atendida", "faltou"):
            raise HTTPException(409, "Esta reserva foi cancelada ou trocada.")
        conn.execute("update reservas set status = %s where id = %s", (novo, reserva["id"]))
    return ir_para(_volta(dia))


@roteador.get("/reservas/{rid}/cancelar")
def cancelar_form(request: Request, rid: str, dia: str = ""):
    pro = exigir_perfil(request)
    with painel(pro) as conn:
        reserva = _reserva_ou_404(conn, rid)
        perfil = conn.execute("select * from profissionais").fetchone()
    tz = carregar_fuso(perfil["fuso"])
    return pagina(request, "painel_cancelar.html", secao="inicio", reserva=reserva, tz=tz, dia=dia)


@roteador.post("/reservas/{rid}/cancelar", dependencies=Protegido)
def cancelar(request: Request, rid: str, dia: Campo = ""):
    pro = exigir_perfil(request)
    with painel(pro) as conn:
        reserva = _reserva_ou_404(conn, rid)
        perfil = conn.execute("select * from profissionais").fetchone()
        if reserva["status"] != "confirmada":
            raise HTTPException(409, "Esta reserva já não está ativa.")
        conn.execute("update reservas set status = 'cancelada_profissional' where id = %s", (rid,))
    tz = carregar_fuso(perfil["fuso"])
    aviso = (
        telefone.link_whatsapp(
            reserva["cliente_whatsapp"], mensagens.aviso_de_cancelamento(perfil, reserva, tz)
        )
        if reserva["cliente_whatsapp"]
        else None
    )
    return pagina(
        request,
        "painel_cancelada.html",
        secao="inicio",
        reserva=reserva,
        tz=tz,
        aviso=aviso,
        volta=_volta(dia),
    )


def _espera_ou_404(conn, eid: str) -> dict:
    ident = uuid_valido(eid)
    linha = (
        conn.execute("select * from espera where id = %s", (ident,)).fetchone() if ident else None
    )
    if linha is None:
        raise HTTPException(404)
    return linha


@roteador.post("/espera/{eid}/chamar", dependencies=Protegido)
def chamar_da_espera(request: Request, eid: str):
    pro = exigir_perfil(request)
    with painel(pro) as conn:
        espera = _espera_ou_404(conn, eid)
        perfil = conn.execute("select * from profissionais").fetchone()
        conn.execute("update espera set avisada_em = now() where id = %s", (espera["id"],))
    texto = mensagens.chamada_da_espera(
        perfil, espera, f"{carregar().base_url}/{perfil['slug']}", carregar_fuso(perfil["fuso"])
    )
    return _whatsapp(espera["whatsapp"], texto)


@roteador.post("/espera/{eid}/apagar", dependencies=Protegido)
def apagar_da_espera(request: Request, eid: str, dia: Campo = ""):
    pro = exigir_perfil(request)
    with painel(pro) as conn:
        espera = _espera_ou_404(conn, eid)
        conn.execute("delete from espera where id = %s", (espera["id"],))
    return ir_para(_volta(dia))
