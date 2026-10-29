# Arquitetura

Para quem vai ler ou mexer no código. O Encaixe é um **monolito FastAPI** que renderiza páginas HTML no servidor (Jinja2), com SQL puro sobre Postgres e quase nenhum JavaScript: nenhuma página depende dele. Foi pensado para rodar de graça numa instância pequena.

## Mapa do código

```
src/encaixe/
  app.py            monta o FastAPI: rotas, middleware de segurança, páginas de erro
  config.py         variáveis de ambiente (SECRET_KEY, BASE_URL, ...)
  db.py             pool de conexões e os 3 jeitos de falar com o banco (sistema, painel, publico)
  migrate.py        aplica migrations/*.sql em ordem, com trava contra execução dupla
  migrations/       001 agenda, 002 contas, 003 espera + funções do cliente, 004 origens
  horarios.py       FUNÇÕES PURAS: grade de horários, fuso, conflito (o que a tela mostra)
  agenda.py         monta dias e horários livres a partir do banco
  reservas.py       criar reserva, token derivado do id
  rotas_*.py        contas, painel, agenda do dia, divulgação, páginas públicas, site
  contas.py, senhas.py, google.py, assinatura.py, limite.py, seguranca.py   segurança
  divulgacao.py, mensagens.py, limpeza.py, telefone.py, slugs.py, formularios.py, datas.py
  templates/, static/   HTML e CSS (fonte do sistema, sem fontes nem scripts de terceiros)
tests/              pytest (banco real: Postgres embutido ou o do CI)
e2e/                Playwright + axe-core: acessibilidade, teclado, celular, privacidade
scripts/            dev.py (sobe tudo local), gerar_imagens.py
```

## Os três jeitos de falar com o banco

O app conecta como dono do banco, e o dono ignora o RLS. Por isso toda requisição que fala em nome de alguém **troca de papel** (`set local role`) e diz quem é (`set_config(..., true)`, que só vale até o fim da transação):

| Contexto (`db.py`) | Papel | Quem usa | O que enxerga |
| --- | --- | --- | --- |
| `sistema()` | dono | cadastro, login, redirecionador, limpeza | tudo (o código tem de ser cuidadoso) |
| `painel(id)` | `encaixe_painel` | profissional logado | só linhas com o `profissional_id` dele (RLS) |
| `publico(id, token?)` | `encaixe_publico` | cliente | ocupação **sem dados pessoais** (views) e a própria reserva, se tiver o token |

O papel público **não tem UPDATE** em `reservas`: o cliente só cancela, troca ou apaga os dados por quatro funções `SECURITY DEFINER` (`cancelar_pelo_cliente`, `remarcar_pelo_cliente`, `apagar_dados_da_reserva`, `sucessora_da_reserva`) que só fazem a transição certa. Os papéis restritos não têm nenhum acesso a `contas`, `sessoes` e `codigos_recuperacao`.

Um teste existe para cada fronteira: profissional A não lê nem escreve dados de B, o público não lê reservas sem o link, não cria reserva em nome de outro profissional, não lê a lista de espera.

## Sem reserva dupla

O banco é quem garante, não o app. O gatilho `reservas_antes_de_inserir` (em `001_agenda.sql`):

1. toma `pg_advisory_xact_lock` pelo id do profissional (lock de **transação**: funciona atrás do pooler do Neon, que troca de conexão a cada transação);
2. recalcula fim e fim-com-folga a partir do serviço e força o estado `confirmada` (o cliente nunca manda duração nem estado);
3. recusa se cruza uma folga, se cruza outra reserva (atendimento individual) ou, em aula, se for outro serviço, outro início ou se as vagas acabaram.

Os erros têm códigos próprios (`EN001` ocupado, `EN002` lotado, `EN003` bloqueado, `EN004` serviço inválido), traduzidos em `reservas.py`. Outro gatilho torna a reserva **imutável**: só o estado muda, em transições permitidas, e os dados do cliente só mudam para serem apagados.

`horarios.py` espelha essas regras para **mostrar** o que ainda cabe; um teste confere que, para cada horário que a tela oferece (ou esconde), o gatilho aceita (ou recusa) de fato. Os testes de corrida disparam 12 threads pelo mesmo horário e conferem que exatamente uma vence (e que uma aula de 3 vagas nunca passa de 3).

## Fuso e horário de verão

Tudo é `timestamptz`. O horário de atendimento (`09:00–12:00`) é montado no relógio do profissional com `zoneinfo` e convertido para UTC; a grade anda **em passos de UTC**, então um dia de troca de horário tem uma hora a menos (ou a mais) em vez de horários que não existem ou se repetem. Há testes com Nova York em 2024 e com São Paulo em 2018 (último ano de horário de verão). O dia da agenda e a contagem de aberturas também valem no fuso do profissional (agrupados em Python, porque o Postgres embutido do Windows não conhece os fusos).

## Reserva, link secreto e estado

O cliente não tem conta. A reserva tem um token de 192 bits derivado do id com HMAC-SHA256 da `SECRET_KEY` (`reservas.token_da_reserva`). O banco guarda **só o hash**; assim o profissional consegue montar o link no lembrete sem que ele fique salvo, e quem só tem o banco não calcula os links. Trocar a `SECRET_KEY` invalida os links já enviados.

Estados: `confirmada → atendida | faltou | cancelada_cliente | cancelada_profissional | remarcada`. Remarcar marca a antiga como `remarcada` (apontando para a nova) e insere a nova **na mesma transação**; se a nova for recusada, tudo volta.

## Sessões, contas e CSRF

- Cadastro e login com senha (Argon2id; 10 caracteres no mínimo) ou Google (OpenID Connect com PKCE, `state` e `nonce`; só `openid email`). Contas de senha e de Google **nunca se juntam por e-mail**, porque o e-mail de senha não é verificado.
- Sem e-mail não há "esqueci a senha": o cadastro dá 8 códigos de recuperação de uso único.
- Sessão: cookie `HttpOnly`, `SameSite=Lax`, com prefixo `__Host-` e `Secure` em produção; no banco só o hash. 30 dias.
- Requisições que alteram dados passam por `Sec-Fetch-Site` (com `Origin` de reserva), e todo formulário do painel leva um token CSRF por sessão. O `Referrer-Policy` é `same-origin`: com `no-referrer` o Chrome manda `Origin: null` em todo formulário.
- Limite de tentativas em memória (`limite.py`): vale para **uma instância**. Com várias, troque por um contador compartilhado.

## Privacidade por construção

Nenhuma tabela tem IP, user agent, cookie ou referer; um teste varre o esquema. O redirecionador de divulgação grava só um contador por origem e por dia. Dados pessoais do cliente: nome, WhatsApp, e-mail opcional; anonimizados 90 dias depois do horário (`limpeza.py`, chamada por `POST /interno/limpeza` com `CRON_SECRET`). Excluir a conta apaga tudo do profissional.

## Interface e acessibilidade

- Páginas em sequência de GETs com parâmetros na URL (`s` serviço, `dia`, `h` horário em segundos UNIX); só nome e WhatsApp viajam em POST.
- **Lista de dias em vez de grade de calendário**: evita as armadilhas de acessibilidade do `role="grid"` e funciona sem JavaScript.
- CSP sem `unsafe-inline` e sem recursos de fora: nada de `style=""` nas páginas (use classes de `estilo.css`).
- Tema claro/escuro por `prefers-color-scheme`. Os contrastes conferidos estão nos comentários de `estilo.css`.

## Testes

```bash
uv run pytest                                  # banco de verdade (pgserver local, serviço Postgres no CI)
npm ci --prefix e2e && npm run --prefix e2e test:a11y
```

- `tests/` cobre os caminhos permitido e proibido de cada módulo. O relógio é injetável (`encaixe.tempo.agora`), então datas em 2030 não dependem do dia em que o teste roda.
- `e2e/` sobe o app de verdade, semeia dados pelo próprio site e roda **axe (WCAG 2.2 AA) em 35 páginas e estados nos dois temas**, reflow a 640 e 320 px, texto a 200%, foco visível, marcar horário só com o teclado e no celular emulado, e a ausência de cookies, de requisições externas e de dados pessoais na URL.
- CI (`.github/workflows/ci.yml`): `test`, `security` (gitleaks, pip-audit, npm audit) e `a11y`.

## Decisões que valem ser lembradas

| Decisão | Por quê |
| --- | --- |
| Monolito, sem JWT nem microsserviços | Um produto, um problema; sessão no banco é revogável |
| `pg_advisory_xact_lock` por profissional | Simples, correto e compatível com PgBouncer em modo transação |
| Token derivado do id, não sorteado | O profissional precisa reconstruir o link do lembrete |
| Sem e-mail | Provedores gratuitos exigem domínio próprio; o Render bloqueia SMTP |
| `/saude` fora do banco | O ping que mantém o Render acordado não pode gastar a cota do Neon |
| Papel público sem UPDATE | Nem um erro no app deixa o cliente mudar o horário ou o estado |

## Como estender

- **Nova tela do painel:** rota em `rotas_painel.py` ou `rotas_agenda.py`, usando `Protegido` (CSRF) nos POSTs e `painel(id)` para o banco; template em `templates/` com `{% from "_csrf.html" import csrf_campo with context %}` (sem o `with context` o token sai vazio, e há um teste que pega isso).
- **Nova tabela por profissional:** coluna `profissional_id`, RLS com `enc_pro()` e permissões mínimas por papel, num novo `00N_*.sql`. Migrações já aplicadas nunca são editadas.
- **Nova regra de horário:** altere o gatilho **e** `horarios._motivo`; o teste de concordância (`test_grade_do_python_e_o_gatilho_do_banco_concordam`) mostra se divergiram.
