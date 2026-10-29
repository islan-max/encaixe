"""A página pública do profissional e a da reserva (link secreto), sem conta e sem JavaScript.

O fluxo é uma sequência de GETs com parâmetros na URL (`s` serviço, `dia`, `h` horário em segundos
UNIX), então cada passo é um link que se pode compartilhar. Nenhum dado pessoal vai para a URL:
nome e WhatsApp só viajam em POST. O token da reserva vai no caminho, e o `Referrer-Policy`
impede que saia para outro site.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request

from encaixe import limite, slugs, telefone, tempo
from encaixe.agenda import (
    dias_livres,
    horarios_no_dia,
    regras_do_profissional,
    servico_de,
)
from encaixe.categorias import FUSOS
from encaixe.datas import data_longa, hora_curta
from encaixe.db import hash_do_token, publico, sistema
from encaixe.formularios import consulta, data, inteiro, texto, uuid_valido
from encaixe.horarios import Horario, Ocupada, pode_cancelar
from encaixe.reservas import ReservaRecusada, criar, novo_token
from encaixe.senhas import email_normalizado
from encaixe.web import ir_para, pagina

roteador = APIRouter()
Campo = Annotated[str, Form(max_length=300)]


def _pro_ou_404(slug: str) -> str:
    if not slugs.PADRAO.match(slug) or slug in slugs.RESERVADOS:
        raise HTTPException(404)  # nem chega ao banco: robôs batem em /wp-admin, /admin etc.
    with sistema() as conn:
        achado = conn.execute("select profissional_id_por_slug(%s) as id", (slug,)).fetchone()["id"]
    if not achado:
        raise HTTPException(404)
    return str(achado)


def _basico(conn) -> tuple[dict, list[dict], object]:
    perfil = conn.execute("select * from profissionais").fetchone()
    servicos = conn.execute("select * from servicos order by ordem, criado_em").fetchall()
    return perfil, servicos, regras_do_profissional(conn, perfil)


def _escolher_servico(servicos: list[dict], s: str) -> dict | None:
    ident = uuid_valido(s) if s else None
    for servico in servicos:
        if ident and str(servico["id"]) == ident:
            return servico
    return servicos[0] if len(servicos) == 1 else None


def _epoch(h: str) -> datetime | None:
    n = inteiro(h, 0, 4_102_444_800)
    return datetime.fromtimestamp(n, UTC) if n is not None else None


def _ocupada(reserva: dict) -> Ocupada:
    return Ocupada(str(reserva["servico_id"]), reserva["inicio"], reserva["ocupa_ate"])


def _servico_da_reserva(reserva: dict) -> dict:
    """O que o resumo da tela precisa saber do serviço de uma reserva que já existe."""
    return {
        "nome": reserva["servico_nome"],
        "duracao_min": reserva["duracao_min"],
        "preco_centavos": reserva["preco_centavos"],
    }


def _achar(horarios: list[Horario], h: str) -> Horario | None:
    inicio = _epoch(h)
    return next((x for x in horarios if x.inicio == inicio), None) if inicio else None


def _fuso_aviso(perfil: dict) -> str | None:
    return FUSOS.get(perfil["fuso"]) if perfil["fuso"] != "America/Sao_Paulo" else None


def _mensagem_para_o_profissional(
    perfil: dict, nome_cliente: str, servico: str, quando: str
) -> str:
    o_que = "meu horário" if perfil["lembrete_discreto"] else f"{servico}"
    return f"Oi, {perfil['nome']}! Aqui é {nome_cliente}. Marquei {o_que} para {quando}."


# --- página do profissional -----------------------------------------------------------------


@roteador.get("/{slug}")
def pagina_publica(
    request: Request,
    slug: str,
    s: str = "",
    dia: str = "",
    h: str = "",
    pg: str = "0",
    v: str = "",
):
    pro = _pro_ou_404(slug)
    agora = tempo.agora()
    contexto: dict = {"slug": slug, "v": v[:20], "consulta": consulta, "etapa": "servico"}
    with publico(pro) as conn:
        perfil, servicos, regras = _basico(conn)
        contexto.update(perfil=perfil, servicos=servicos, fuso_aviso=_fuso_aviso(perfil))
        escolhido = _escolher_servico(servicos, s)
        if not servicos:
            contexto["etapa"] = "sem_servicos"
        elif escolhido is not None:
            servico = servico_de(escolhido)
            contexto.update(servico=escolhido, unico=len(servicos) == 1)
            d = data(dia)
            if d is None:
                pagina_n = inteiro(pg, 0, 30) or 0
                dias, mais = dias_livres(conn, regras, servico, agora, pagina_n)
                contexto.update(etapa="dia", dias=dias, mais=mais, pg=pagina_n)
            else:
                horarios = horarios_no_dia(conn, regras, servico, d, agora)
                alvo = _achar(horarios, h) if h else None
                contexto.update(etapa="horario", dia=d, horarios=horarios, tz=regras.tz)
                if alvo and alvo.reservavel:
                    contexto.update(etapa="dados", alvo=alvo, valores={}, erros={})
                elif h:
                    contexto["aviso"] = "Esse horário não está mais livre. Escolha outro."
    return pagina(request, "publica.html", **contexto)


@roteador.post("/{slug}/reservar")
def reservar(
    request: Request,
    slug: str,
    s: Campo = "",
    dia: Campo = "",
    h: Campo = "",
    nome: Campo = "",
    whatsapp: Campo = "",
    email: Campo = "",
    v: Campo = "",
    site: Campo = "",
):
    if site:  # isca para robô: gente de verdade não vê nem preenche este campo
        raise HTTPException(400)
    pro = _pro_ou_404(slug)
    agora = tempo.agora()
    espera = limite.RESERVA_POR_IP.registrar(limite.ip_do_cliente(request))
    if espera:
        raise HTTPException(429)
    token = novo_token()
    nome_ok = texto(nome, 2, 80)
    numero = telefone.normalizar(whatsapp)
    email_ok = email_normalizado(email) if email.strip() else None
    erros: dict[str, str] = {}
    if not nome_ok:
        erros["nome"] = "Escreva seu nome, com pelo menos 2 letras."
    if not numero:
        erros["whatsapp"] = "Digite o DDD e o número do celular, como (11) 98888-7777."
    if email.strip() and not email_ok:
        erros["email"] = "Esse e-mail não parece certo. Deixe em branco se preferir."
    contexto: dict = {"slug": slug, "v": v[:20], "consulta": consulta}
    with publico(pro) as conn:
        perfil, servicos, regras = _basico(conn)
        escolhido = _escolher_servico(servicos, s)
        inicio = _epoch(h)
        if escolhido is None or inicio is None:
            raise HTTPException(404)
        servico = servico_de(escolhido)
        dia_local = inicio.astimezone(regras.tz).date()
        horarios = horarios_no_dia(conn, regras, servico, dia_local, agora)
        alvo = next((x for x in horarios if x.inicio == inicio), None)
        if alvo is None:
            raise HTTPException(404)
        conflito = not alvo.reservavel
        if not erros and not conflito:
            try:
                criar(
                    conn,
                    profissional_id=pro,
                    servico_id=str(escolhido["id"]),
                    inicio=inicio,
                    cliente_nome=nome_ok,
                    cliente_whatsapp=numero,
                    cliente_email=email_ok,
                    token=token,
                )
            except ReservaRecusada:
                conflito = True
                horarios = horarios_no_dia(conn, regras, servico, dia_local, agora)
            else:
                return ir_para(f"/reserva/{token}?nova=1")
        contexto.update(
            perfil=perfil,
            servicos=servicos,
            servico=escolhido,
            unico=len(servicos) == 1,
            fuso_aviso=_fuso_aviso(perfil),
            dia=dia_local,
            horarios=horarios,
            tz=regras.tz,
            valores={"nome": nome, "whatsapp": whatsapp, "email": email},
            erros=erros,
        )
    if conflito:
        contexto.update(etapa="conflito")
        return pagina(request, "publica.html", status=409, **contexto)
    contexto.update(etapa="dados", alvo=alvo)
    return pagina(request, "publica.html", status=422, **contexto)


@roteador.post("/{slug}/espera")
def entrar_na_espera(
    request: Request,
    slug: str,
    s: Campo = "",
    dia: Campo = "",
    nome: Campo = "",
    whatsapp: Campo = "",
    v: Campo = "",
    site: Campo = "",
):
    if site:
        raise HTTPException(400)
    pro = _pro_ou_404(slug)
    if limite.RESERVA_POR_IP.registrar(limite.ip_do_cliente(request)):
        raise HTTPException(429)
    agora = tempo.agora()
    nome_ok = texto(nome, 2, 80)
    numero = telefone.normalizar(whatsapp)
    d = data(dia)
    with publico(pro) as conn:
        perfil, servicos, regras = _basico(conn)
        escolhido = _escolher_servico(servicos, s)
        if escolhido is None or d is None:
            raise HTTPException(404)
        hoje = agora.astimezone(regras.tz).date()
        if not nome_ok or not numero:
            erros = {
                "nome": "" if nome_ok else "Escreva seu nome, com pelo menos 2 letras.",
                "whatsapp": "" if numero else "Digite o DDD e o número do celular.",
            }
            return pagina(
                request,
                "espera_erro.html",
                status=422,
                perfil=perfil,
                slug=slug,
                servico=escolhido,
                dia=d,
                erros={k: x for k, x in erros.items() if x},
                valores={"nome": nome, "whatsapp": whatsapp},
                consulta=consulta,
                v=v[:20],
            )
        if not hoje <= d <= date.fromordinal(hoje.toordinal() + regras.dias_a_frente):
            raise HTTPException(404)
        conn.execute(
            "insert into espera (profissional_id, servico_id, dia, nome, whatsapp)"
            " values (%s, %s, %s, %s, %s) on conflict do nothing",
            (pro, escolhido["id"], d, nome_ok, numero),
        )
    return pagina(
        request,
        "espera_ok.html",
        perfil=perfil,
        slug=slug,
        servico=escolhido,
        dia=d,
        consulta=consulta,
        v=v[:20],
    )


# --- a reserva, pelo link secreto ----------------------------------------------------------


def _pro_da_reserva(token: str) -> str:
    if not 20 <= len(token) <= 64:
        raise HTTPException(404)
    with sistema() as conn:
        achado = conn.execute(
            "select profissional_id_da_reserva(decode(%s, 'hex')) as id", (hash_do_token(token),)
        ).fetchone()["id"]
    if not achado:
        raise HTTPException(404)
    return str(achado)


def _carregar_reserva(conn, token: str, agora: datetime) -> dict:
    reserva = conn.execute(
        "select r.*, s.nome as servico_nome, s.duracao_min, s.folga_min, s.vagas,"
        " s.preco_centavos from reservas r"
        " join servicos s on s.id = r.servico_id"
    ).fetchone()
    if reserva is None:
        raise HTTPException(404)
    perfil = conn.execute("select * from profissionais").fetchone()
    regras = regras_do_profissional(conn, perfil)
    tz = regras.tz
    sucessora = None
    if reserva["status"] == "remarcada":
        sucessora = conn.execute(
            "select * from sucessora_da_reserva(decode(%s, 'hex'))", (hash_do_token(token),)
        ).fetchone()
    passou = reserva["fim"] <= agora
    inicio_local = reserva["inicio"].astimezone(tz)
    quando = f"{data_longa(inicio_local.date())}, {hora_curta(reserva['inicio'], tz)}"
    return {
        "reserva": reserva,
        "perfil": perfil,
        "regras": regras,
        "tz": tz,
        "sucessora": sucessora,
        "passou": passou,
        "ativa": reserva["status"] == "confirmada" and not passou,
        "pode_cancelar": reserva["status"] == "confirmada"
        and not passou
        and pode_cancelar(regras, reserva["inicio"], agora),
        "pode_apagar": reserva["anonimizada_em"] is None
        and (reserva["status"] != "confirmada" or passou),
        "quando": quando,
        "link_whatsapp": telefone.link_whatsapp(
            perfil["whatsapp"],
            _mensagem_para_o_profissional(
                perfil, reserva["cliente_nome"], reserva["servico_nome"], quando
            ),
        ),
        "link_contato": telefone.link_whatsapp(perfil["whatsapp"]),
        "token": token,
        "data_longa": data_longa,
        "hora_curta": hora_curta,
    }


def _ver(request: Request, token: str, modelo: str, status: int = 200, **extra):
    pro = _pro_da_reserva(token)
    agora = tempo.agora()
    with publico(pro, token) as conn:
        dados = _carregar_reserva(conn, token, agora)
    return pagina(request, modelo, status=status, **dados, **extra)


@roteador.get("/reserva/{token}")
def ver_reserva(request: Request, token: str):
    return _ver(request, token, "reserva.html")


@roteador.get("/reserva/{token}/cancelar")
def cancelar_confirmar(request: Request, token: str):
    return _ver(request, token, "reserva_cancelar.html")


@roteador.post("/reserva/{token}/cancelar")
def cancelar(request: Request, token: str):
    pro = _pro_da_reserva(token)
    if limite.CANCELAR_POR_IP.registrar(limite.ip_do_cliente(request)):
        raise HTTPException(429)
    agora = tempo.agora()
    with publico(pro, token) as conn:
        dados = _carregar_reserva(conn, token, agora)
        if dados["pode_cancelar"]:
            conn.execute("select cancelar_pelo_cliente(decode(%s, 'hex'))", (hash_do_token(token),))
            return ir_para(f"/reserva/{token}?cancelada=1")
    return pagina(request, "reserva_cancelar.html", status=409, **dados)


@roteador.post("/reserva/{token}/apagar")
def apagar_dados(request: Request, token: str):
    pro = _pro_da_reserva(token)
    with publico(pro, token) as conn:
        feito = conn.execute(
            "select apagar_dados_da_reserva(decode(%s, 'hex')) as ok", (hash_do_token(token),)
        ).fetchone()["ok"]
    if not feito:
        raise HTTPException(409, "Esta reserva ainda está ativa. Cancele antes de apagar os dados.")
    return ir_para(f"/reserva/{token}?apagada=1")


@roteador.get("/reserva/{token}/remarcar")
def remarcar_passos(request: Request, token: str, dia: str = "", h: str = "", pg: str = "0"):
    pro = _pro_da_reserva(token)
    agora = tempo.agora()
    with publico(pro, token) as conn:
        dados = _carregar_reserva(conn, token, agora)
        if not dados["pode_cancelar"]:
            return pagina(request, "reserva_cancelar.html", status=409, **dados)
        antiga = dados["reserva"]
        servico = servico_de({**antiga, "id": antiga["servico_id"]})
        regras = dados["regras"]
        d = data(dia)
        extra: dict = {"servico": _servico_da_reserva(antiga)}
        if d is None:
            pagina_n = inteiro(pg, 0, 30) or 0
            dias, mais = dias_livres(conn, regras, servico, agora, pagina_n, _ocupada(antiga))
            extra.update(etapa="dia", dias=dias, mais=mais, pg=pagina_n)
        else:
            horarios = horarios_no_dia(conn, regras, servico, d, agora, _ocupada(antiga))
            alvo = _achar(horarios, h) if h else None
            extra.update(etapa="horario", dia=d, horarios=horarios)
            if alvo and alvo.reservavel and alvo.inicio != dados["reserva"]["inicio"]:
                extra.update(etapa="confirmar", alvo=alvo)
            elif h:
                extra["aviso"] = "Esse horário não está mais livre. Escolha outro."
    return pagina(request, "reserva_remarcar.html", **dados, **extra)


class _Desfazer(Exception):
    def __init__(self, dia: date):
        self.dia = dia


@roteador.post("/reserva/{token}/remarcar")
def remarcar(request: Request, token: str, h: Campo = ""):
    try:
        return _remarcar(request, token, h)
    except _Desfazer as desfeito:
        return ir_para(f"/reserva/{token}/remarcar{consulta(dia=desfeito.dia.isoformat())}")


def _remarcar(request: Request, token: str, h: str):
    pro = _pro_da_reserva(token)
    if limite.CANCELAR_POR_IP.registrar(limite.ip_do_cliente(request)):
        raise HTTPException(429)
    agora = tempo.agora()
    novo_token_ = novo_token()
    inicio = _epoch(h)
    if inicio is None:
        raise HTTPException(404)
    with publico(pro, token) as conn:
        dados = _carregar_reserva(conn, token, agora)
        antiga = dados["reserva"]
        if not dados["pode_cancelar"] or inicio == antiga["inicio"]:
            return pagina(request, "reserva_cancelar.html", status=409, **dados)
        servico = servico_de({**antiga, "id": antiga["servico_id"]})
        regras = dados["regras"]
        dia_local = inicio.astimezone(regras.tz).date()
        horarios = horarios_no_dia(conn, regras, servico, dia_local, agora, _ocupada(antiga))
        alvo = next((x for x in horarios if x.inicio == inicio), None)
        if alvo is None or not alvo.reservavel:
            return ir_para(f"/reserva/{token}/remarcar{consulta(dia=dia_local.isoformat())}")
        nova_id = str(uuid.uuid4())
        # A antiga sai da frente primeiro: assim um horário vizinho (ou o mesmo dia) não conflita
        # com ela. Se a nova for recusada, a transação inteira volta e nada muda.
        conn.execute(
            "select remarcar_pelo_cliente(decode(%s, 'hex'), %s)", (hash_do_token(token), nova_id)
        )
        try:
            criar(
                conn,
                profissional_id=pro,
                servico_id=str(antiga["servico_id"]),
                inicio=inicio,
                cliente_nome=antiga["cliente_nome"],
                cliente_whatsapp=antiga["cliente_whatsapp"],
                cliente_email=antiga["cliente_email"],
                token=novo_token_,
                origem_id=antiga["origem_id"],
                id=nova_id,
            )
        except ReservaRecusada:
            raise _Desfazer(dia_local) from None  # sai do `with`: a transação inteira volta
    return ir_para(f"/reserva/{novo_token_}?remarcada=1")
