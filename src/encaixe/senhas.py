import re

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# Parâmetros padrão do argon2-cffi: Argon2id com o perfil recomendado pela RFC 9106.
_hasher = PasswordHasher()
# Hash de uma senha que ninguém tem: gasta o mesmo tempo quando o e-mail não existe, para o login
# não revelar quais e-mails têm conta pela demora da resposta.
_FALSO = _hasher.hash("senha-que-ninguem-tem")

SENHA_MIN = 10
SENHA_MAX = 128
_COMUNS = {
    "1234567890",
    "12345678910",
    "0123456789",
    "senha12345",
    "senha123456",
    "password123",
    "qwertyuiop",
    "1q2w3e4r5t",
    "abcdefghij",
    "brasil12345",
    "mudar12345",
}
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


def hash_da_senha(senha: str) -> str:
    return _hasher.hash(senha)


def senha_confere(hash_: str | None, senha: str) -> bool:
    """Com `hash_` None (e-mail sem conta), confere contra um hash falso e devolve False."""
    try:
        _hasher.verify(hash_ or _FALSO, senha)
        return hash_ is not None
    except (VerificationError, InvalidHashError):
        return False


def problema_na_senha(senha: str, email: str = "") -> str | None:
    """Mensagem para o usuário, ou None se a senha serve. Sem regra de maiúscula e símbolo: o que
    protege é o tamanho."""
    if len(senha) < SENHA_MIN:
        return f"Use pelo menos {SENHA_MIN} caracteres. Uma frase curta serve."
    if len(senha) > SENHA_MAX:
        return f"Use no máximo {SENHA_MAX} caracteres."
    if senha.lower() in _COMUNS or len(set(senha)) < 4:
        return "Essa senha é fácil de adivinhar. Escolha outra."
    if email and senha.lower() == email.lower():
        return "A senha não pode ser igual ao e-mail."
    return None


def email_normalizado(texto: str) -> str | None:
    """E-mail em minúsculas e sem espaços nas pontas, ou None se não parece um e-mail."""
    email = texto.strip().lower()
    if len(email) > 254 or not _EMAIL.match(email):
        return None
    return email
