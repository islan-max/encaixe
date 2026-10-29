"""O redirecionador /r/<código> e a tela de divulgação do painel."""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from encaixe import divulgacao, limite, tempo
from encaixe.config import carregar
from encaixe.db import painel, sistema
from encaixe.formularios import consulta, texto, uuid_valido
from encaixe.horarios import carregar_fuso
from encaixe.rotas_painel import Protegido, exigir_perfil
from encaixe.web import ir_para, pagina

roteador = APIRouter()
Campo = Annotated[str, Form(max_length=200)]


@roteador.get("/r/{codigo}")
def redirecionar(request: Request, codigo: str):
    if not divulgacao.PADRAO_CODIGO.match(codigo):
        raise HTTPException(404)
    with sistema() as conn:
        origem = conn.execute(
            "select o.id, p.slug, p.fuso from origens o join profissionais p"
            " on p.id = o.profissional_id where o.codigo = %s",
            (codigo,),
        ).fetchone()
        if origem is None:
            raise HTTPException(404)
        pessoa = not divulgacao.parece_robo(request.headers.get("user-agent"))
        # Passou do limite do endereço? Segue o redirecionamento, mas sem contar.
        if pessoa and not limite.REDIRECT_POR_IP.registrar(limite.ip_do_cliente(request)):
            hoje = tempo.agora().astimezone(carregar_fuso(origem["fuso"])).date()
            divulgacao.contar_acesso(conn, str(origem["id"]), hoje)
    return RedirectResponse(f"/{origem['slug']}{consulta(v=codigo)}", status_code=302)


def _origens_com_numeros(conn, hoje) -> tuple[list[dict], int]:
    origens = conn.execute(
        "select o.id, o.nome, o.codigo,"
        " coalesce((select sum(c.n) from cliques_dia c where c.origem_id = o.id), 0) as acessos,"
        " coalesce((select sum(c.n) from cliques_dia c where c.origem_id = o.id"
        "           and c.dia >= %s), 0) as acessos_30,"
        " (select count(*) from reservas r where r.origem_id = o.id"
        "  and r.status <> 'remarcada') as reservas"
        " from origens o where o.arquivada_em is null order by o.criada_em",
        (hoje - timedelta(days=29),),
    ).fetchall()
    diretas = conn.execute(
        "select count(*) as n from reservas where origem_id is null and status <> 'remarcada'"
    ).fetchone()["n"]
    return origens, diretas


def _contexto(pro: str) -> dict:
    base = carregar().base_url
    with painel(pro) as conn:
        perfil = conn.execute("select * from profissionais").fetchone()
        hoje = tempo.agora().astimezone(carregar_fuso(perfil["fuso"])).date()
        origens, diretas = _origens_com_numeros(conn, hoje)
    itens = []
    for o in origens:
        url = f"{base}/r/{o['codigo']}"
        qr = divulgacao.qr_inline(url, f"QR code do link {o['nome']}")
        itens.append({**o, "url": url, "qr": qr})
    return {
        "secao": "divulgacao",
        "perfil": perfil,
        "link_direto": f"{base}/{perfil['slug']}",
        "itens": itens,
        "diretas": diretas,
        "valores": {},
        "erros": {},
    }


@roteador.get("/painel/divulgacao")
def divulgacao_pagina(request: Request):
    return pagina(request, "divulgacao.html", **_contexto(exigir_perfil(request)))


@roteador.post("/painel/divulgacao", dependencies=Protegido)
def divulgacao_criar(request: Request, nome: Campo = ""):
    pro = exigir_perfil(request)
    nome_ok = texto(nome, 2, 40)
    if not nome_ok:
        contexto = _contexto(pro) | {
            "valores": {"nome": nome},
            "erros": {
                "nome": "Dê um nome de 2 a 40 letras, como Instagram ou Cartão da barbearia."
            },
        }
        return pagina(request, "divulgacao.html", status=422, **contexto)
    with painel(pro) as conn:
        divulgacao.criar_origem(conn, pro, nome_ok)
    return ir_para("/painel/divulgacao")


@roteador.post("/painel/divulgacao/{origem_id}/arquivar", dependencies=Protegido)
def divulgacao_arquivar(request: Request, origem_id: str):
    pro = exigir_perfil(request)
    ident = uuid_valido(origem_id)
    if not ident:
        raise HTTPException(404)
    with painel(pro) as conn:
        feito = conn.execute(
            "update origens set arquivada_em = now() where id = %s and arquivada_em is null",
            (ident,),
        )
        if feito.rowcount == 0:
            raise HTTPException(404)
    return ir_para("/painel/divulgacao")


@roteador.get("/painel/divulgacao/{origem_id}/qr.{formato}")
def divulgacao_qr(request: Request, origem_id: str, formato: str):
    pro = exigir_perfil(request)
    ident = uuid_valido(origem_id)
    if formato not in ("svg", "png") or not ident:
        raise HTTPException(404)
    with painel(pro) as conn:
        origem = conn.execute("select * from origens where id = %s", (ident,)).fetchone()
    if origem is None:
        raise HTTPException(404)
    url = f"{carregar().base_url}/r/{origem['codigo']}"
    nome_do_arquivo = f"encaixe-qr-{origem['codigo']}.{formato}"
    return Response(
        divulgacao.qr_arquivo(url, formato),
        media_type="image/svg+xml" if formato == "svg" else "image/png",
        headers={"Content-Disposition": f'attachment; filename="{nome_do_arquivo}"'},
    )
