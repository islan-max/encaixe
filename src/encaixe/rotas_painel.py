"""Painel do profissional: criar o perfil e configurar serviços, horários, regras, folgas e perfil.

Toda leitura e escrita passa por `painel(profissional_id)`: o banco só devolve linhas do próprio
profissional (RLS). Os formulários nunca escolhem `profissional_id`.
"""

import re
from datetime import UTC, datetime, time, timedelta
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from encaixe import contas, slugs, telefone
from encaixe.categorias import CATEGORIAS, FUSOS
from encaixe.config import carregar
from encaixe.db import painel, sistema
from encaixe.formularios import dinheiro, hora, inteiro, texto, uuid_valido
from encaixe.horarios import carregar_fuso
from encaixe.profissionais import SlugEmUso, criar_perfil
from encaixe.senhas import senha_confere
from encaixe.web import checar_csrf, exigir_usuario, ir_para, pagina, usuario_atual

roteador = APIRouter(prefix="/painel")
Campo = Annotated[str, Form(max_length=2000)]

PASSOS = (10, 15, 20, 30, 60)
ANTECEDENCIAS_H = (0, 1, 2, 4, 8, 12, 24, 48, 72)
HORIZONTES_D = (7, 14, 30, 60, 90, 180)
CANCELAR_H = (0, 1, 2, 4, 12, 24, 48)
FICHAS = ("nome", "servico", "dia", "hora", "link", "profissional")
DIAS_SEMANA = (
    "Segunda-feira",
    "Terça-feira",
    "Quarta-feira",
    "Quinta-feira",
    "Sexta-feira",
    "Sábado",
    "Domingo",
)


class ComecarPerfil(Exception):
    pass


def exigir_perfil(request: Request) -> str:
    usuario = exigir_usuario(request)
    if not usuario["profissional_id"]:
        raise ComecarPerfil
    return str(usuario["profissional_id"])


def exigir_csrf(request: Request, csrf: Annotated[str, Form()] = "") -> None:
    exigir_usuario(request)
    checar_csrf(request, csrf)


Protegido = [Depends(exigir_csrf)]


def _link_publico(slug: str) -> str:
    return f"{carregar().base_url}/{slug}"


def _perfil(conn: psycopg.Connection) -> dict:
    return conn.execute("select * from profissionais").fetchone()


# --- início e criação do perfil ------------------------------------------------------------------


def _comecar_contexto(valores=None, erros=None):
    return {
        "categorias": CATEGORIAS.values(),
        "valores": valores or {},
        "erros": erros or {},
    }


@roteador.get("/comecar")
def comecar_form(request: Request):
    usuario = exigir_usuario(request)
    if usuario["profissional_id"]:
        return ir_para("/painel")
    return pagina(request, "comecar.html", **_comecar_contexto())


@roteador.post("/comecar", dependencies=Protegido)
def comecar(
    request: Request,
    nome: Campo = "",
    slug: Campo = "",
    whatsapp: Campo = "",
    categoria: Campo = "",
):
    usuario = exigir_usuario(request)
    if usuario["profissional_id"]:
        return ir_para("/painel")
    erros: dict[str, str] = {}
    nome_ok = texto(nome, 2, 80)
    slug_ok = slug.strip().lower() or slugs.sugerir(nome)
    numero = telefone.normalizar(whatsapp)
    if not nome_ok:
        erros["nome"] = "Escreva o nome que seus clientes conhecem, com 2 a 80 letras."
    if (p := slugs.problema(slug_ok)) is not None:
        erros["slug"] = p
    if not numero:
        erros["whatsapp"] = "Digite o DDD e o número do celular, como (11) 98888-7777."
    if categoria not in CATEGORIAS:
        erros["categoria"] = "Escolha o que combina mais com o seu trabalho."
    valores = {"nome": nome, "slug": slug_ok, "whatsapp": whatsapp, "categoria": categoria}
    if not erros:
        try:
            with sistema() as conn:
                criar_perfil(conn, usuario["id"], nome_ok, slug_ok, numero, categoria)
        except SlugEmUso:
            erros["slug"] = "Esse endereço já é de outra pessoa. Tente outro."
    if erros:
        return pagina(request, "comecar.html", status=422, **_comecar_contexto(valores, erros))
    return ir_para("/painel")


# --- serviços --------------------------------------------------------------------------------


def _ler_servico(nome, duracao, folga, vagas, preco) -> tuple[dict, dict]:
    erros: dict[str, str] = {}
    dados = {
        "nome": texto(nome, 2, 80),
        "duracao_min": inteiro(duracao, 5, 480),
        "folga_min": inteiro(folga or "0", 0, 120),
        "vagas": inteiro(vagas or "1", 1, 50),
        "preco_centavos": None,
    }
    if dados["nome"] is None:
        erros["nome"] = "Dê um nome de 2 a 80 letras, como Corte ou Consulta."
    if dados["duracao_min"] is None:
        erros["duracao"] = "Diga quantos minutos dura, de 5 a 480."
    if dados["folga_min"] is None:
        erros["folga"] = "A folga vai de 0 a 120 minutos."
    if dados["vagas"] is None:
        erros["vagas"] = "As vagas vão de 1 a 50."
    if preco.strip():
        dados["preco_centavos"] = dinheiro(preco)
        if dados["preco_centavos"] is None:
            erros["preco"] = "Escreva o valor assim: 35 ou 35,50."
    return dados, erros


@roteador.get("/servicos")
def servicos(request: Request):
    pro = exigir_perfil(request)
    with painel(pro) as conn:
        lista = conn.execute(
            "select * from servicos order by ativo desc, ordem, criado_em"
        ).fetchall()
    return pagina(request, "servicos.html", secao="servicos", servicos=lista, valores={}, erros={})


@roteador.post("/servicos", dependencies=Protegido)
def servico_novo(
    request: Request,
    nome: Campo = "",
    duracao: Campo = "",
    folga: Campo = "",
    vagas: Campo = "",
    preco: Campo = "",
):
    pro = exigir_perfil(request)
    dados, erros = _ler_servico(nome, duracao, folga, vagas, preco)
    with painel(pro) as conn:
        if not erros:
            conn.execute(
                "insert into servicos (profissional_id, nome, duracao_min, folga_min, vagas,"
                " preco_centavos, ordem) values (%s, %s, %s, %s, %s, %s,"
                " (select coalesce(max(ordem) + 1, 0) from servicos))",
                (
                    pro,
                    dados["nome"],
                    dados["duracao_min"],
                    dados["folga_min"],
                    dados["vagas"],
                    dados["preco_centavos"],
                ),
            )
            return ir_para("/painel/servicos")
        lista = conn.execute(
            "select * from servicos order by ativo desc, ordem, criado_em"
        ).fetchall()
    valores = {"nome": nome, "duracao": duracao, "folga": folga, "vagas": vagas, "preco": preco}
    return pagina(
        request,
        "servicos.html",
        status=422,
        secao="servicos",
        servicos=lista,
        valores=valores,
        erros=erros,
    )


def _servico_ou_404(conn: psycopg.Connection, servico_id: str) -> dict:
    ident = uuid_valido(servico_id)
    linha = (
        conn.execute("select * from servicos where id = %s", (ident,)).fetchone() if ident else None
    )
    if linha is None:
        raise HTTPException(404)
    return linha


@roteador.get("/servicos/{servico_id}")
def servico_editar_form(request: Request, servico_id: str):
    pro = exigir_perfil(request)
    with painel(pro) as conn:
        servico = _servico_ou_404(conn, servico_id)
    return pagina(request, "servico_editar.html", secao="servicos", servico=servico, erros={})


@roteador.post("/servicos/{servico_id}", dependencies=Protegido)
def servico_editar(
    request: Request,
    servico_id: str,
    nome: Campo = "",
    duracao: Campo = "",
    folga: Campo = "",
    vagas: Campo = "",
    preco: Campo = "",
):
    pro = exigir_perfil(request)
    dados, erros = _ler_servico(nome, duracao, folga, vagas, preco)
    with painel(pro) as conn:
        atual = _servico_ou_404(conn, servico_id)
        if not erros:
            conn.execute(
                "update servicos set nome = %s, duracao_min = %s, folga_min = %s, vagas = %s,"
                " preco_centavos = %s where id = %s",
                (
                    dados["nome"],
                    dados["duracao_min"],
                    dados["folga_min"],
                    dados["vagas"],
                    dados["preco_centavos"],
                    atual["id"],
                ),
            )
            return ir_para("/painel/servicos")
    mostrado = {
        **atual,
        "nome": nome,
        "duracao_min": duracao,
        "folga_min": folga,
        "vagas": vagas,
        "preco_texto": preco,
    }
    return pagina(
        request, "servico_editar.html", status=422, secao="servicos", servico=mostrado, erros=erros
    )


@roteador.post("/servicos/{servico_id}/ativo", dependencies=Protegido)
def servico_ativar(request: Request, servico_id: str, ativo: Campo = "0"):
    pro = exigir_perfil(request)
    with painel(pro) as conn:
        atual = _servico_ou_404(conn, servico_id)
        conn.execute("update servicos set ativo = %s where id = %s", (ativo == "1", atual["id"]))
    return ir_para("/painel/servicos")


# --- horários semanais e regras -----------------------------------------------------------------


def _ler_semana(form: dict[str, str]) -> tuple[dict[int, list[tuple[time, time]]], dict[str, str]]:
    semana: dict[int, list[tuple[time, time]]] = {}
    erros: dict[str, str] = {}
    for dia in range(7):
        faixas = []
        for periodo in ("a", "b"):
            ini_txt = form.get(f"d{dia}{periodo}_ini", "").strip()
            fim_txt = form.get(f"d{dia}{periodo}_fim", "").strip()
            if not ini_txt and not fim_txt:
                continue
            ini, fim = hora(ini_txt), hora(fim_txt)
            if ini is None or fim is None or fim <= ini:
                erros[f"d{dia}{periodo}"] = (
                    f"{DIAS_SEMANA[dia]}: preencha começo e fim; o fim vem depois do começo."
                )
                continue
            faixas.append((ini, fim))
        faixas.sort()
        for anterior, seguinte in zip(faixas, faixas[1:], strict=False):
            if seguinte[0] < anterior[1]:
                erros[f"d{dia}a"] = f"{DIAS_SEMANA[dia]}: os dois períodos se cruzam."
        if faixas:
            semana[dia] = faixas
    return semana, erros


def _semana_para_tela(conn: psycopg.Connection) -> dict[str, str]:
    campos: dict[str, str] = {}
    linhas = conn.execute(
        "select dia_semana, inicio, fim from horarios_semanais order by dia_semana, inicio"
    ).fetchall()
    por_dia: dict[int, list] = {}
    for linha in linhas:
        por_dia.setdefault(linha["dia_semana"], []).append(linha)
    for dia, faixas in por_dia.items():
        for periodo, faixa in zip("ab", faixas[:2], strict=False):
            campos[f"d{dia}{periodo}_ini"] = faixa["inicio"].strftime("%H:%M")
            campos[f"d{dia}{periodo}_fim"] = faixa["fim"].strftime("%H:%M")
    return campos


@roteador.get("/horarios")
def horarios_form(request: Request):
    pro = exigir_perfil(request)
    with painel(pro) as conn:
        valores = _semana_para_tela(conn)
    return pagina(
        request, "horarios.html", secao="horarios", valores=valores, erros={}, dias=DIAS_SEMANA
    )


@roteador.post("/horarios")
async def horarios_salvar(request: Request):
    form = {k: str(v) for k, v in (await request.form()).items()}
    return await run_in_threadpool(_horarios_salvar, request, form)


def _horarios_salvar(request: Request, form: dict[str, str]):
    pro = exigir_perfil(request)
    checar_csrf(request, form.get("csrf", ""))
    semana, erros = _ler_semana(form)
    if erros:
        return pagina(
            request,
            "horarios.html",
            status=422,
            secao="horarios",
            valores=form,
            erros=erros,
            dias=DIAS_SEMANA,
        )
    with painel(pro) as conn:
        conn.execute("delete from horarios_semanais")
        for dia, faixas in semana.items():
            for ini, fim in faixas:
                conn.execute(
                    "insert into horarios_semanais (profissional_id, dia_semana, inicio, fim)"
                    " values (%s, %s, %s, %s)",
                    (pro, dia, ini, fim),
                )
    return ir_para("/painel/horarios?salvo=1")


@roteador.get("/regras")
def regras_form(request: Request):
    pro = exigir_perfil(request)
    with painel(pro) as conn:
        perfil = _perfil(conn)
    return pagina(request, "regras.html", secao="regras", **_regras_contexto(perfil))


def _regras_contexto(perfil: dict, erros: dict | None = None) -> dict:
    return {
        "perfil": perfil,
        "erros": erros or {},
        "passos": PASSOS,
        "antecedencias": ANTECEDENCIAS_H,
        "horizontes": HORIZONTES_D,
        "cancelares": CANCELAR_H,
        "ante_h": perfil["antecedencia_min"] // 60,
        "cancelar_h": perfil["cancelar_ate_min"] // 60,
    }


@roteador.post("/regras", dependencies=Protegido)
def regras_salvar(
    request: Request,
    passo: Campo = "",
    antecedencia: Campo = "",
    horizonte: Campo = "",
    cancelar: Campo = "",
):
    pro = exigir_perfil(request)
    passo_ok = inteiro(passo, 5, 60)
    ante_ok = inteiro(antecedencia, 0, 336)
    hor_ok = inteiro(horizonte, 1, 180)
    canc_ok = inteiro(cancelar, 0, 336)
    if None in (passo_ok, ante_ok, hor_ok, canc_ok) or passo_ok not in PASSOS:
        raise HTTPException(422, "Alguma opção não é válida. Volte e escolha de novo.")
    with painel(pro) as conn:
        conn.execute(
            "update profissionais set passo_min = %s, antecedencia_min = %s, dias_a_frente = %s,"
            " cancelar_ate_min = %s",
            (passo_ok, ante_ok * 60, hor_ok, canc_ok * 60),
        )
    return ir_para("/painel/regras?salvo=1")


# --- folgas ----------------------------------------------------------------------------------


def _folgas_da_tela(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        "select b.*, (select count(*) from reservas r where r.status = 'confirmada'"
        " and r.inicio < b.fim and b.inicio < r.ocupa_ate) as reservas"
        " from bloqueios b where b.fim > now() order by b.inicio"
    ).fetchall()


@roteador.get("/folgas")
def folgas(request: Request):
    pro = exigir_perfil(request)
    with painel(pro) as conn:
        fuso = carregar_fuso(_perfil(conn)["fuso"])
        lista = _folgas_da_tela(conn)
    return pagina(
        request, "folgas.html", secao="folgas", folgas=lista, fuso=fuso, valores={}, erros={}
    )


def _momento(dia: str, horario: str, fuso, fim_do_dia: bool) -> datetime | None:
    try:
        d = datetime.strptime(dia.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None
    if horario.strip():
        h = hora(horario)
        if h is None:
            return None
        return datetime.combine(d, h, tzinfo=fuso).astimezone(UTC)
    if fim_do_dia:  # sem hora no fim: vai até o fim daquele dia
        return datetime.combine(d + timedelta(days=1), time(0), tzinfo=fuso).astimezone(UTC)
    return datetime.combine(d, time(0), tzinfo=fuso).astimezone(UTC)


@roteador.post("/folgas", dependencies=Protegido)
def folga_nova(
    request: Request,
    de_dia: Campo = "",
    de_hora: Campo = "",
    ate_dia: Campo = "",
    ate_hora: Campo = "",
    motivo: Campo = "",
):
    pro = exigir_perfil(request)
    with painel(pro) as conn:
        fuso = carregar_fuso(_perfil(conn)["fuso"])
        inicio = _momento(de_dia, de_hora, fuso, fim_do_dia=False)
        fim = _momento(ate_dia or de_dia, ate_hora, fuso, fim_do_dia=True)
        erros: dict[str, str] = {}
        if inicio is None:
            erros["de"] = "Escolha o dia em que a folga começa."
        if fim is None:
            erros["ate"] = "Escolha o dia em que a folga termina."
        if inicio and fim and fim <= inicio:
            erros["ate"] = "A folga precisa terminar depois de começar."
        motivo_ok = texto(motivo, 0, 120)
        if motivo_ok is None:
            erros["motivo"] = "O motivo pode ter até 120 letras."
        if not erros:
            cruzam = conn.execute(
                "select count(*) as n from reservas where status = 'confirmada'"
                " and inicio < %s and %s < ocupa_ate",
                (fim, inicio),
            ).fetchone()["n"]
            conn.execute(
                "insert into bloqueios (profissional_id, inicio, fim, motivo)"
                " values (%s, %s, %s, %s)",
                (pro, inicio, fim, motivo_ok or None),
            )
            return ir_para(f"/painel/folgas?criada=1&cruzam={cruzam}")
        lista = _folgas_da_tela(conn)
    valores = {
        "de_dia": de_dia,
        "de_hora": de_hora,
        "ate_dia": ate_dia,
        "ate_hora": ate_hora,
        "motivo": motivo,
    }
    return pagina(
        request,
        "folgas.html",
        status=422,
        secao="folgas",
        folgas=lista,
        fuso=fuso,
        valores=valores,
        erros=erros,
    )


@roteador.post("/folgas/{folga_id}/apagar", dependencies=Protegido)
def folga_apagar(request: Request, folga_id: str):
    pro = exigir_perfil(request)
    ident = uuid_valido(folga_id)
    if not ident:
        raise HTTPException(404)
    with painel(pro) as conn:
        apagou = conn.execute("delete from bloqueios where id = %s", (ident,))
        if apagou.rowcount == 0:
            raise HTTPException(404)
    return ir_para("/painel/folgas")


# --- perfil ----------------------------------------------------------------------------------


@roteador.get("/perfil")
def perfil_form(request: Request):
    pro = exigir_perfil(request)
    with painel(pro) as conn:
        perfil = _perfil(conn)
    return pagina(
        request,
        "perfil.html",
        secao="perfil",
        valores={**perfil, "whatsapp": telefone.formatar(perfil["whatsapp"])},
        erros={},
        fusos=FUSOS,
        categorias=CATEGORIAS,
        por_senha=bool(usuario_atual(request).get("email")),
    )


@roteador.post("/perfil", dependencies=Protegido)
def perfil_salvar(
    request: Request,
    nome: Campo = "",
    slug: Campo = "",
    whatsapp: Campo = "",
    fuso: Campo = "",
    mensagem_lembrete: Campo = "",
    lembrete_discreto: Campo = "",
):
    pro = exigir_perfil(request)
    erros: dict[str, str] = {}
    nome_ok = texto(nome, 2, 80)
    slug_ok = slug.strip().lower()
    numero = telefone.normalizar(whatsapp)
    mensagem = mensagem_lembrete.replace("\r\n", "\n").strip()
    if not nome_ok:
        erros["nome"] = "Escreva o nome que seus clientes conhecem, com 2 a 80 letras."
    if (p := slugs.problema(slug_ok)) is not None:
        erros["slug"] = p
    if not numero:
        erros["whatsapp"] = "Digite o DDD e o número do celular, como (11) 98888-7777."
    if fuso not in FUSOS:
        erros["fuso"] = "Escolha um dos fusos da lista."
    desconhecidas = sorted(set(re.findall(r"\{(\w*)\}", mensagem)) - set(FICHAS))
    sobra = re.sub(r"\{\w*\}", "", mensagem)
    if not 10 <= len(mensagem) <= 500:
        erros["mensagem"] = "A mensagem precisa ter de 10 a 500 letras."
    elif desconhecidas or "{" in sobra or "}" in sobra:
        trecho = ", ".join("{" + d + "}" for d in desconhecidas) or "chaves soltas"
        erros["mensagem"] = f"Tem algo que não conheço na mensagem: {trecho}. Veja a lista abaixo."
    with painel(pro) as conn:
        if not erros:
            try:
                with conn.transaction():
                    conn.execute(
                        "update profissionais set nome = %s, slug = %s, whatsapp = %s, fuso = %s,"
                        " mensagem_lembrete = %s, lembrete_discreto = %s",
                        (nome_ok, slug_ok, numero, fuso, mensagem, lembrete_discreto == "1"),
                    )
                return ir_para("/painel/perfil?salvo=1")
            except psycopg.errors.UniqueViolation:
                erros["slug"] = "Esse endereço já é de outra pessoa. Tente outro."
        categoria = _perfil(conn)["categoria"]
    valores = {
        "nome": nome,
        "slug": slug,
        "whatsapp": whatsapp,
        "fuso": fuso,
        "mensagem_lembrete": mensagem_lembrete,
        "lembrete_discreto": lembrete_discreto == "1",
        "categoria": categoria,
    }
    return pagina(
        request,
        "perfil.html",
        status=422,
        secao="perfil",
        valores=valores,
        erros=erros,
        fusos=FUSOS,
        categorias=CATEGORIAS,
        por_senha=bool(usuario_atual(request).get("email")),
    )


@roteador.post("/codigos", dependencies=Protegido)
def codigos_novos(request: Request, senha: Campo = ""):
    usuario = exigir_usuario(request)
    with sistema() as conn:
        conta = conn.execute(
            "select senha_hash from contas where id = %s", (usuario["id"],)
        ).fetchone()
        if not conta["senha_hash"] or not senha_confere(conta["senha_hash"], senha):
            raise HTTPException(403, "Senha incorreta. Volte e tente de novo.")
        novos = contas.gerar_codigos(conn, str(usuario["id"]))
    return pagina(request, "codigos.html", codigos=novos)
