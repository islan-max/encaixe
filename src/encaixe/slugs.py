"""O endereço curto de cada profissional (/rafa-barbeiro)."""

import re
import unicodedata

PADRAO = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")

# Tudo que já é rota do site (ou poderia virar) e nomes que enganariam quem lê o endereço.
RESERVADOS = frozenset(
    """
    entrar cadastrar cadastro sair login logout recuperar painel reserva reservas r static saude
    interno privacidade termos robots sitemap favicon admin administrador api app www encaixe
    ajuda suporte contato conta contas sobre inicio home index erro 404 500 status docs
    blog preco precos planos sistema root null undefined health ping redoc swagger openapi
    """.split()
)


def sugerir(nome: str) -> str:
    """'Rafa Barbeiro' vira 'rafa-barbeiro'. Pode devolver algo curto demais: valide depois."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")[:40].strip("-")


def problema(slug: str) -> str | None:
    """Mensagem para o usuário, ou None se o endereço serve (falta só conferir se está livre)."""
    if not PADRAO.match(slug):
        return (
            "Use de 3 a 40 letras minúsculas, números e hífen, sem acento nem espaço. "
            "Exemplo: rafa-barbeiro."
        )
    if slug in RESERVADOS:
        return "Esse endereço é reservado pelo Encaixe. Escolha outro."
    if "--" in slug:
        return "Não use dois hífens seguidos."
    return None
