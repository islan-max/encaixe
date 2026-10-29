"""Peças compartilhadas pelos testes de tela."""

import re
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from encaixe.app import create_app
from encaixe.db import sistema

SENHA = "uma frase longa e boa"
SP = ZoneInfo("America/Sao_Paulo")


class Sessao:
    """Um navegador com conta criada. `csrf` é o token que as páginas põem nos formulários."""

    def __init__(self, email: str):
        self.http = TestClient(create_app(), follow_redirects=False)
        r = self.http.post("/cadastrar", data={"email": email, "senha": SENHA})
        self.csrf = re.search(r'name="csrf" value="([0-9a-f]+)"', r.text).group(1)
        self.codigos = re.findall(r"<li>([a-z0-9]{5}-[a-z0-9]{5})</li>", r.text)

    def post(self, url, **dados):
        return self.http.post(url, data={"csrf": self.csrf, **dados})

    def get(self, url):
        return self.http.get(url)

    def criar_perfil(self, slug="rafa-barbeiro", categoria="beleza", nome="Rafa Barbeiro"):
        return self.post(
            "/painel/comecar",
            nome=nome,
            slug=slug,
            whatsapp="(11) 98888-7777",
            categoria=categoria,
        )

    def perfil_id(self) -> str:
        with sistema() as conn:
            return str(
                conn.execute("select id from profissionais where slug is not null").fetchone()["id"]
            )
