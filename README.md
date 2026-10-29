# Encaixe

Agenda para autônomos. Cada profissional tem uma página de agendamento própria, com link curto e QR code. O cliente escolhe o horário e marca **sem criar conta**. O profissional vê o dia e manda o lembrete com um toque, pelo WhatsApp. Grátis e de código aberto.

> Em construção. O que já existe: esqueleto do projeto e CI. A documentação de uso e de instalação chega junto com o deploy.

## Para desenvolver

Precisa de Python 3.12 e [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run ruff check
uv run pytest
uv run uvicorn encaixe.app:app --reload
```

Os testes que usam banco sobem um Postgres embutido (`pgserver`). Para usar outro banco, defina `TEST_DATABASE_URL`.

## Licença

MIT.
