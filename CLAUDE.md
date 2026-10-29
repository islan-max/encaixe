# Encaixe: instruções para agentes

Agenda para autônomos. Interface e documentação em português do Brasil. Só soluções gratuitas.

## Guia de desenvolvimento

Guia local do mantenedor: `Documents/Obsidian Vault/IA/guia-desenvolvimento-ia/README.md` (fora do repositório).
Leia o fluxo de trabalho e, antes de alterar uma funcionalidade, os módulos indicados pelos gatilhos do índice.
Registre contexto, decisões e resultados em `docs/CONTEXTO.md` e `docs/VERIFICACAO.md`, sem segredos ou dados pessoais.
Antes de publicar, percorra o checklist de publicação e justifique itens não aplicáveis.
Informe o que foi verificado, o que falhou e o que depende de acesso ou teste posterior.

## Regras do projeto

- Fluxo: issue, branch, PR, CI verde, merge squash. Nunca commit direto na `main`. Sem PR vazio ou só cosmético. A branch seguinte só nasce depois do merge da anterior.
- **Sem coautoria**: nada de `Co-Authored-By` e nenhum rodapé de IA em commits, PRs ou issues.
- Comandos: `uv sync`, `uv run ruff check`, `uv run ruff format --check`, `uv run pytest`.
- Testes de banco sobem um Postgres embutido (`pgserver`); com `TEST_DATABASE_URL` usam o banco indicado (é o que o CI faz).
- Nada de IP, user agent ou cookie de visitante guardados. Dados pessoais do cliente só nome, WhatsApp e e-mail opcional.
- Acessibilidade WCAG 2.2 AA é requisito, não polimento: sem cor como única informação, foco visível, funciona sem JavaScript.
- No Windows/Git Bash heredocs grandes truncam: use a ferramenta Write e `python -X utf8`.
