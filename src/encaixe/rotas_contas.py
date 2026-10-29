"""Cadastro, entrada, saída, recuperação e login com Google."""

import secrets
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from encaixe import assinatura, contas, google, limite
from encaixe.config import carregar
from encaixe.db import sistema
from encaixe.senhas import email_normalizado, hash_da_senha, problema_na_senha, senha_confere
from encaixe.web import (
    apagar_cookie_sessao,
    checar_csrf,
    definir_cookie_sessao,
    exigir_usuario,
    ir_para,
    pagina,
    usuario_atual,
)

roteador = APIRouter()
Campo = Annotated[str, Form(max_length=300)]
COOKIE_GOOGLE = "oauth"


def _espera(segundos: int) -> str:
    minutos = max(1, -(-segundos // 60))
    return f"Muitas tentativas. Espere {minutos} min e tente de novo."


@roteador.get("/cadastrar")
def cadastrar_form(request: Request):
    if usuario_atual(request):
        return ir_para("/painel")
    return pagina(request, "cadastrar.html", google_ativo=carregar().google_ativo)


@roteador.post("/cadastrar")
def cadastrar(request: Request, email: Campo = "", senha: Campo = ""):
    ip = limite.ip_do_cliente(request)
    espera = limite.CADASTRO_POR_IP.registrar(ip)
    erros: dict[str, str] = {}
    email_ok = email_normalizado(email)
    if espera:
        erros["geral"] = _espera(espera)
    else:
        if not email_ok:
            erros["email"] = "Esse e-mail não parece certo. Confira se tem @ e o final, como .com."
        if (problema := problema_na_senha(senha, email_ok or "")) is not None:
            erros["senha"] = problema
    if erros:
        return pagina(
            request,
            "cadastrar.html",
            status=429 if espera else 422,
            erros=erros,
            email=email,
            google_ativo=carregar().google_ativo,
        )
    with sistema() as conn:
        conta_id = contas.criar_conta_senha(conn, email_ok, hash_da_senha(senha))
        if conta_id is None:
            # E-mail não é verificado, então a recusa é inevitável; a frase não diz mais que isso.
            erros["geral"] = (
                "Não deu para criar a conta com esses dados. Se você já tem conta, entre por aqui."
            )
            return pagina(
                request,
                "cadastrar.html",
                status=422,
                erros=erros,
                email=email,
                google_ativo=carregar().google_ativo,
            )
        codigos = contas.gerar_codigos(conn, conta_id)
        token = contas.criar_sessao(conn, conta_id)
    # A página dos códigos já aparece "logada": o menu precisa do usuário e do token do CSRF.
    request.state.usuario = {"id": conta_id, "email": email_ok, "profissional_id": None}
    request.state.sessao_token = token
    resposta = pagina(request, "codigos.html", codigos=codigos)
    definir_cookie_sessao(resposta, token)
    return resposta


@roteador.get("/entrar")
def entrar_form(request: Request):
    if usuario_atual(request):
        return ir_para("/painel")
    return pagina(request, "entrar.html", google_ativo=carregar().google_ativo)


@roteador.post("/entrar")
def entrar(request: Request, email: Campo = "", senha: Campo = ""):
    ip = limite.ip_do_cliente(request)
    email_ok = email_normalizado(email)
    chave_email = email_ok or "invalido"
    espera = limite.LOGIN_POR_EMAIL.esta_bloqueado(
        chave_email
    ) or limite.LOGIN_POR_IP.esta_bloqueado(ip)
    if espera:
        return pagina(
            request,
            "entrar.html",
            status=429,
            erro=_espera(espera),
            email=email,
            google_ativo=carregar().google_ativo,
        )
    with sistema() as conn:
        conta = contas.conta_por_email(conn, email_ok) if email_ok else None
        confere = senha_confere(conta["senha_hash"] if conta else None, senha)
        if not (conta and confere):
            limite.LOGIN_POR_EMAIL.registrar(chave_email)
            limite.LOGIN_POR_IP.registrar(ip)
            return pagina(
                request,
                "entrar.html",
                status=401,
                erro="E-mail ou senha incorretos.",
                email=email,
                google_ativo=carregar().google_ativo,
            )
        token = contas.criar_sessao(conn, str(conta["id"]))
    limite.LOGIN_POR_EMAIL.zerar(chave_email)
    resposta = ir_para("/painel")
    definir_cookie_sessao(resposta, token)
    return resposta


@roteador.post("/sair")
def sair(request: Request, csrf: Campo = ""):
    exigir_usuario(request)
    checar_csrf(request, csrf)
    with sistema() as conn:
        contas.encerrar_sessao(conn, request.state.sessao_token)
    resposta = ir_para("/")
    apagar_cookie_sessao(resposta)
    return resposta


@roteador.get("/recuperar")
def recuperar_form(request: Request):
    return pagina(request, "recuperar.html")


@roteador.post("/recuperar")
def recuperar(request: Request, email: Campo = "", codigo: Campo = "", nova_senha: Campo = ""):
    espera = limite.RECUPERAR_POR_IP.registrar(limite.ip_do_cliente(request))
    if espera:
        return pagina(request, "recuperar.html", status=429, erro=_espera(espera), email=email)
    email_ok = email_normalizado(email)
    problema = problema_na_senha(nova_senha, email_ok or "")
    if problema:
        return pagina(request, "recuperar.html", status=422, erro_senha=problema, email=email)
    novo_hash = hash_da_senha(
        nova_senha
    )  # calculado sempre: a demora não revela se o e-mail existe
    with sistema() as conn:
        conta = contas.conta_por_email(conn, email_ok) if email_ok else None
        if not (conta and conta["senha_hash"] and contas.usar_codigo(conn, conta["id"], codigo)):
            return pagina(
                request,
                "recuperar.html",
                status=401,
                erro="O e-mail ou o código não conferem. Cada código só vale uma vez.",
                email=email,
            )
        contas.trocar_senha(conn, str(conta["id"]), novo_hash)
        token = contas.criar_sessao(conn, str(conta["id"]))
    resposta = ir_para("/painel")
    definir_cookie_sessao(resposta, token)
    return resposta


# --- Entrar com Google -------------------------------------------------------------------------


@roteador.get("/entrar/google")
def google_inicio(request: Request):
    config = carregar()
    if not config.google_ativo:
        return pagina(request, "erro.html", status=404, titulo="Página não encontrada")
    desafio = google.novo_desafio()
    resposta = RedirectResponse(google.url_de_autorizacao(config, desafio), status_code=303)
    resposta.set_cookie(
        COOKIE_GOOGLE,
        assinatura.assinar(desafio, 600),
        max_age=600,
        httponly=True,
        secure=config.cookie_seguro,
        samesite="lax",  # a volta do Google é uma navegação de topo: Lax envia o cookie
        path="/entrar/google",
    )
    return resposta


@roteador.get("/entrar/google/retorno")
def google_retorno(request: Request, code: str = "", state: str = ""):
    config = carregar()
    desafio = assinatura.ler(request.cookies.get(COOKIE_GOOGLE))
    ip = limite.ip_do_cliente(request)

    def falhou():
        resposta = pagina(
            request,
            "entrar.html",
            status=400,
            erro="Não deu para entrar com o Google. Tente de novo ou use e-mail e senha.",
            google_ativo=config.google_ativo,
        )
        resposta.delete_cookie(COOKIE_GOOGLE, path="/entrar/google")
        return resposta

    if limite.LOGIN_POR_IP.registrar(ip) or not config.google_ativo:
        return falhou()
    if not desafio or not code or not secrets.compare_digest(str(desafio["state"]), state):
        return falhou()
    try:
        claims = request.app.state.google.identificar(config, code, desafio)
    except google.LoginGoogleFalhou:
        return falhou()
    with sistema() as conn:
        conta = contas.conta_google(conn, claims["sub"], claims.get("email"))
        token = contas.criar_sessao(conn, str(conta["id"]))
    resposta = ir_para("/painel")
    definir_cookie_sessao(resposta, token)
    resposta.delete_cookie(COOKIE_GOOGLE, path="/entrar/google")
    return resposta
