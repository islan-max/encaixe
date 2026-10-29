import re
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from encaixe import assinatura, google, limite
from encaixe.app import create_app
from encaixe.db import painel, publico, sistema
from encaixe.senhas import email_normalizado, problema_na_senha

SENHA = "uma frase longa e boa"


@pytest.fixture(autouse=True)
def zerar_limites():
    for limitador in limite.TODOS:
        limitador.esquecer_tudo()


@pytest.fixture
def cliente(banco):
    return TestClient(create_app(), follow_redirects=False)


def csrf_da_pagina(html: str) -> str:
    return re.search(r'name="csrf" value="([0-9a-f]+)"', html).group(1)


def cadastrar(cliente, email="rafa@exemplo.com", senha=SENHA):
    return cliente.post("/cadastrar", data={"email": email, "senha": senha})


def codigos_da_pagina(html: str) -> list[str]:
    return re.findall(r"<li>([a-z0-9]{5}-[a-z0-9]{5})</li>", html)


# --- cadastro e entrada -----------------------------------------------------------------------


def test_cadastro_mostra_oito_codigos_e_deixa_a_pessoa_logada(cliente):
    r = cadastrar(cliente)
    assert r.status_code == 200
    assert len(set(codigos_da_pagina(r.text))) == 8
    assert "sessao" in r.cookies
    assert cliente.get("/painel").status_code == 200


def test_senha_e_guardada_com_argon2id_e_a_sessao_so_como_hash(cliente):
    r = cadastrar(cliente)
    token = r.cookies["sessao"]
    with sistema() as conn:
        conta = conn.execute("select * from contas").fetchone()
        assert conta["senha_hash"].startswith("$argon2id$")
        assert SENHA not in conta["senha_hash"]
        sessoes = conn.execute("select token_hash from sessoes").fetchall()
        assert len(sessoes) == 1 and token.encode() not in bytes(sessoes[0]["token_hash"])


@pytest.mark.parametrize(
    ("email", "senha", "trecho"),
    [
        ("sem-arroba", SENHA, "e-mail"),
        ("a@b.com", "curta", "10 caracteres"),
        ("a@b.com", "1234567890", "fácil de adivinhar"),
        ("a@b.com", "aaaaaaaaaaaa", "fácil de adivinhar"),
    ],
)
def test_cadastro_recusa_dados_ruins_com_mensagem_clara(cliente, email, senha, trecho):
    r = cadastrar(cliente, email, senha)
    assert r.status_code == 422 and trecho in r.text
    with sistema() as conn:
        assert conn.execute("select count(*) as n from contas").fetchone()["n"] == 0


def test_email_repetido_nao_cria_outra_conta(cliente):
    cadastrar(cliente)
    outro = TestClient(create_app(), follow_redirects=False)
    r = cadastrar(outro, "RAFA@exemplo.com ")
    assert r.status_code == 422 and "Não deu para criar a conta" in r.text
    with sistema() as conn:
        assert conn.execute("select count(*) as n from contas").fetchone()["n"] == 1


def test_login_certo_e_errado(cliente):
    cadastrar(cliente)
    outro = TestClient(create_app(), follow_redirects=False)
    r = outro.post("/entrar", data={"email": "rafa@exemplo.com", "senha": SENHA})
    assert r.status_code == 303 and r.headers["location"] == "/painel" and "sessao" in r.cookies
    r1 = outro.post("/entrar", data={"email": "rafa@exemplo.com", "senha": "errada errada"})
    r2 = outro.post("/entrar", data={"email": "ninguem@exemplo.com", "senha": "errada errada"})
    assert r1.status_code == r2.status_code == 401
    assert "E-mail ou senha incorretos." in r1.text and "E-mail ou senha incorretos." in r2.text


def test_depois_de_cinco_erros_o_login_trava_ate_com_a_senha_certa(cliente):
    cadastrar(cliente)
    outro = TestClient(create_app(), follow_redirects=False)
    for _ in range(5):
        assert (
            outro.post("/entrar", data={"email": "rafa@exemplo.com", "senha": "x" * 12}).status_code
            == 401
        )
    r = outro.post("/entrar", data={"email": "rafa@exemplo.com", "senha": SENHA})
    assert r.status_code == 429 and "Espere" in r.text
    # Outro e-mail, de outra pessoa, não é afetado.
    cadastrar(TestClient(create_app(), follow_redirects=False), "ana@exemplo.com")
    ok = outro.post("/entrar", data={"email": "ana@exemplo.com", "senha": SENHA})
    assert ok.status_code == 303


def test_painel_exige_login(cliente):
    r = cliente.get("/painel")
    assert r.status_code == 303 and r.headers["location"] == "/entrar"


def test_sair_exige_o_token_csrf_e_derruba_a_sessao(cliente):
    r = cadastrar(cliente)
    csrf = csrf_da_pagina(r.text)
    assert cliente.post("/sair", data={"csrf": "errado"}).status_code == 403
    assert cliente.get("/painel").status_code == 200  # continuou logada
    assert cliente.post("/sair", data={"csrf": csrf}).status_code == 303
    assert cliente.get("/painel").status_code == 303
    with sistema() as conn:
        assert conn.execute("select count(*) as n from sessoes").fetchone()["n"] == 0


def test_requisicao_de_outra_origem_e_recusada(cliente):
    r = cliente.post(
        "/entrar",
        data={"email": "a@b.com", "senha": "x" * 12},
        headers={"Origin": "https://site-malicioso.example"},
    )
    assert r.status_code == 403
    mesma = cliente.post(
        "/entrar",
        data={"email": "a@b.com", "senha": "x" * 12},
        headers={"Origin": "http://testserver"},
    )
    assert mesma.status_code == 401


def test_conferencia_de_origem_usa_sec_fetch_site_antes_do_origin(cliente):
    dados = {"email": "a@b.com", "senha": "x" * 12}
    # O Chrome manda `Origin: null` num formulário do próprio site quando o referrer é cortado:
    # o que vale é o Sec-Fetch-Site.
    do_proprio = cliente.post(
        "/entrar", data=dados, headers={"Origin": "null", "Sec-Fetch-Site": "same-origin"}
    )
    assert do_proprio.status_code == 401
    for de_fora in ("cross-site", "same-site"):
        recusada = cliente.post("/entrar", data=dados, headers={"Sec-Fetch-Site": de_fora})
        assert recusada.status_code == 403
    # Sem Sec-Fetch-Site, `Origin: null` não é prova de nada.
    assert cliente.post("/entrar", data=dados, headers={"Origin": "null"}).status_code == 403


def test_cabecalhos_de_seguranca(cliente):
    r = cliente.get("/entrar")
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "same-origin"
    assert r.headers["cache-control"] == "no-store"
    assert "<script" not in r.text.lower()  # a página não depende de JavaScript


# --- recuperação -----------------------------------------------------------------------------


def test_codigo_de_recuperacao_troca_a_senha_uma_vez_so(cliente):
    r = cadastrar(cliente)
    codigos = codigos_da_pagina(r.text)
    outro = TestClient(create_app(), follow_redirects=False)
    dados = {
        "email": "rafa@exemplo.com",
        "codigo": codigos[0].upper(),
        "nova_senha": "outra frase boa",
    }
    ok = outro.post("/recuperar", data=dados)
    assert ok.status_code == 303 and "sessao" in ok.cookies
    # A senha antiga já não vale; a nova vale; a sessão antiga caiu.
    assert (
        outro.post("/entrar", data={"email": "rafa@exemplo.com", "senha": SENHA}).status_code == 401
    )
    assert (
        outro.post(
            "/entrar", data={"email": "rafa@exemplo.com", "senha": "outra frase boa"}
        ).status_code
        == 303
    )
    assert cliente.get("/painel").status_code == 303
    # O mesmo código não funciona de novo.
    de_novo = TestClient(create_app(), follow_redirects=False).post("/recuperar", data=dados)
    assert de_novo.status_code == 401
    # Os outros sete continuam.
    assert outro.get("/painel").status_code == 200


def test_recuperacao_com_codigo_ou_email_errado_da_a_mesma_resposta(cliente):
    cadastrar(cliente)
    c = TestClient(create_app(), follow_redirects=False)
    r1 = c.post(
        "/recuperar",
        data={"email": "rafa@exemplo.com", "codigo": "aaaaa-bbbbb", "nova_senha": SENHA},
    )
    r2 = c.post(
        "/recuperar",
        data={"email": "ninguem@exemplo.com", "codigo": "aaaaa-bbbbb", "nova_senha": SENHA},
    )
    assert r1.status_code == r2.status_code == 401


def test_recuperacao_tem_limite_de_tentativas(cliente):
    c = TestClient(create_app(), follow_redirects=False)
    corpo = {"email": "a@b.com", "codigo": "aaaaa-bbbbb", "nova_senha": SENHA}
    codigos = [c.post("/recuperar", data=corpo).status_code for _ in range(11)]
    assert codigos[:10] == [401] * 10 and codigos[10] == 429


# --- Google ----------------------------------------------------------------------------------


class GoogleFalso:
    def __init__(self, claims=None, erro=False):
        self.claims, self.erro, self.chamadas = (
            claims or {"sub": "g-1", "email": "rafa@gmail.com"},
            erro,
            [],
        )

    def identificar(self, config, codigo, desafio):
        self.chamadas.append((codigo, desafio))
        if self.erro:
            raise google.LoginGoogleFalhou("falhou")
        return self.claims


@pytest.fixture
def com_google(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cliente-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "segredo-de-teste")
    monkeypatch.setenv("BASE_URL", "https://encaixe.exemplo")


def test_sem_configuracao_o_google_some(cliente):
    assert cliente.get("/entrar/google").status_code == 404
    assert "Entrar com Google" not in cliente.get("/entrar").text


def test_google_ida_e_volta(cliente, com_google):
    assert "Entrar com Google" in cliente.get("/entrar").text
    ida = cliente.get("/entrar/google")
    assert ida.status_code == 303
    url = urlsplit(ida.headers["location"])
    consulta = parse_qs(url.query)
    assert url.netloc == "accounts.google.com"
    assert consulta["code_challenge_method"] == ["S256"] and consulta["scope"] == ["openid email"]
    assert consulta["redirect_uri"] == ["https://encaixe.exemplo/entrar/google/retorno"]
    falso = GoogleFalso()
    cliente.app.state.google = falso
    volta = cliente.get(
        "/entrar/google/retorno", params={"code": "abc", "state": consulta["state"][0]}
    )
    assert volta.status_code == 303 and volta.headers["location"] == "/painel"
    assert falso.chamadas[0][0] == "abc" and falso.chamadas[0][1]["nonce"] == consulta["nonce"][0]
    assert cliente.get("/painel").status_code == 200
    with sistema() as conn:
        conta = conn.execute("select * from contas").fetchone()
    assert conta["google_sub"] == "g-1" and conta["email"] is None and conta["senha_hash"] is None


def test_google_com_state_errado_ou_sem_cookie_falha(cliente, com_google):
    cliente.app.state.google = GoogleFalso()
    ida = cliente.get("/entrar/google")
    estado = parse_qs(urlsplit(ida.headers["location"]).query)["state"][0]
    errado = cliente.get("/entrar/google/retorno", params={"code": "abc", "state": "outro"})
    assert errado.status_code == 400 and cliente.get("/painel").status_code == 303
    sem_cookie = TestClient(create_app(), follow_redirects=False)
    sem_cookie.app.state.google = GoogleFalso()
    assert (
        sem_cookie.get(
            "/entrar/google/retorno", params={"code": "abc", "state": estado}
        ).status_code
        == 400
    )


def test_google_recusado_pelo_provedor_nao_cria_conta(cliente, com_google):
    cliente.app.state.google = GoogleFalso(erro=True)
    ida = cliente.get("/entrar/google")
    estado = parse_qs(urlsplit(ida.headers["location"]).query)["state"][0]
    r = cliente.get("/entrar/google/retorno", params={"code": "abc", "state": estado})
    assert r.status_code == 400 and "Não deu para entrar com o Google" in r.text
    with sistema() as conn:
        assert conn.execute("select count(*) as n from contas").fetchone()["n"] == 0


def test_conta_google_nao_se_mistura_com_conta_de_senha_do_mesmo_email(cliente, com_google):
    cadastrar(cliente, "rafa@gmail.com")
    outro = TestClient(create_app(), follow_redirects=False)
    outro.app.state.google = GoogleFalso({"sub": "g-9", "email": "rafa@gmail.com"})
    estado = parse_qs(urlsplit(outro.get("/entrar/google").headers["location"]).query)["state"][0]
    outro.get("/entrar/google/retorno", params={"code": "abc", "state": estado})
    with sistema() as conn:
        assert conn.execute("select count(*) as n from contas").fetchone()["n"] == 2


@pytest.fixture(scope="module")
def chaves_rsa():
    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return privada, privada.public_key()


def _id_token(privada, **mudar):
    agora = datetime.now(UTC)
    claims = {
        "iss": "https://accounts.google.com",
        "aud": "cliente-id",
        "sub": "g-1",
        "email": "a@b.com",
        "nonce": "n-1",
        "iat": agora,
        "exp": agora + timedelta(minutes=5),
    }
    claims.update(mudar)
    return jwt.encode(claims, privada, algorithm="RS256")


def test_id_token_valido_passa(chaves_rsa):
    privada, publica = chaves_rsa
    claims = google.verificar_id_token(_id_token(privada), publica, "cliente-id", "n-1")
    assert claims["sub"] == "g-1"
    google.verificar_id_token(
        _id_token(privada, iss="accounts.google.com"), publica, "cliente-id", "n-1"
    )


@pytest.mark.parametrize(
    "mudar",
    [
        {"aud": "outro-cliente"},
        {"iss": "https://evil.example"},
        {"nonce": "n-2"},
        {"exp": datetime.now(UTC) - timedelta(minutes=5)},
    ],
)
def test_id_token_invalido_e_recusado(chaves_rsa, mudar):
    privada, publica = chaves_rsa
    with pytest.raises(google.LoginGoogleFalhou):
        google.verificar_id_token(_id_token(privada, **mudar), publica, "cliente-id", "n-1")


def test_id_token_assinado_por_outra_chave_ou_algoritmo_e_recusado(chaves_rsa):
    _, publica = chaves_rsa
    outra = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(google.LoginGoogleFalhou):
        google.verificar_id_token(_id_token(outra), publica, "cliente-id", "n-1")
    publica_pem = publica.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    sem_assinatura = jwt.encode(
        {"iss": "accounts.google.com", "aud": "cliente-id", "sub": "x"}, None, algorithm="none"
    )
    with pytest.raises(google.LoginGoogleFalhou):
        google.verificar_id_token(sem_assinatura, publica_pem, "cliente-id", "n-1")


# --- peças ---------------------------------------------------------------------------------


def test_valor_assinado_adulterado_ou_vencido_nao_vale():
    bom = assinatura.assinar({"a": 1}, 60)
    assert assinatura.ler(bom)["a"] == 1
    corpo, mac = bom.split(".")
    assert assinatura.ler(f"{corpo}x.{mac}") is None
    assert assinatura.ler(f"{corpo}.{mac[:-2]}aa") is None
    assert assinatura.ler(assinatura.assinar({"a": 1}, -1)) is None
    assert assinatura.ler(None) is None and assinatura.ler("lixo") is None


def test_limitador_deslizante():
    lim = limite.Limitador(maximo=3, janela_s=10)
    assert [lim.registrar("k", agora=t) for t in (0, 1, 2)] == [None, None, None]
    assert lim.registrar("k", agora=3) == 8  # espera até o primeiro sair da janela
    assert lim.registrar("outra", agora=3) is None
    assert lim.registrar("k", agora=10.5) is None  # o primeiro já saiu


def test_senhas_e_emails():
    assert problema_na_senha("uma frase longa e boa") is None
    assert problema_na_senha("a@b.com-a@b.com", "a@b.com-a@b.com") is not None
    assert email_normalizado("  Rafa@Exemplo.COM ") == "rafa@exemplo.com"
    for ruim in ("", "a@b", "a b@c.com", "@c.com", "x" * 260 + "@c.com"):
        assert email_normalizado(ruim) is None


def test_papeis_restritos_nao_enxergam_contas_nem_sessoes(banco, novo_profissional):
    pro = novo_profissional()
    for abrir in (painel, publico):
        for tabela in ("contas", "sessoes", "codigos_recuperacao"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), abrir(pro) as conn:
                conn.execute(f"select * from {tabela}")  # noqa: S608


def test_tempo_de_vida_da_sessao_vence(cliente):
    cadastrar(cliente)
    with sistema() as conn:
        conn.execute("update sessoes set expira_em = now() - interval '1 second'")
    assert cliente.get("/painel").status_code == 303
