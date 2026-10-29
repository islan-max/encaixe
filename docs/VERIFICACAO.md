# Relatório de verificação

Modelo: `guia-desenvolvimento-ia/07-modelos/relatorio-verificacao.md`. Estados: APROVADO, FALHOU, NÃO VERIFICADO, N/A (com motivo). Um resultado misto não é resumido como aprovado.

## Identificação

- Projeto: Encaixe, agenda para autônomos. Responsável: Islan Max.
- Versão: `main` no commit `432b18f` mais a remoção do log de diagnóstico (PR de verificação). Sem versão numerada.
- Ambientes: **local** (Windows 11, Python 3.12, Postgres 16 embutido `pgserver`, Chrome); **CI** (GitHub Actions, Ubuntu, Postgres 17, Chromium do Playwright); **publicado** em `https://encaixe-1rpp.onrender.com` (Render free, Virginia, + Neon free, AWS us-east-1, conexão pelo pooler).
- Data: 29/10/2026. Executor: Claude (a pedido do Islan), com o Islan criando as contas e colando os segredos.
- Escopo: MVP completo do `docs/CONTEXTO.md`. Dados de teste sintéticos; as contas de teste criadas no site publicado foram apagadas pelo próprio fluxo "Excluir minha conta" (restam contas de teste no banco; ver Pendências).
- Módulos consultados: S01 a S09, Q01, Q02, I01, V01, V02, V03 e D01.

## Parecer

**PUBLICADO E VERIFICADO NO ESCOPO**, com as pendências e os limites abaixo. Nenhum bloqueador conhecido em aberto. Não é uma declaração de segurança absoluta nem de conformidade legal: ver "Limites da verificação".

## Resumo do que foi executado

| Verificação | Onde | Resultado |
| --- | --- | --- |
| `ruff check` e `ruff format --check` | CI e local | APROVADO |
| 222 testes `pytest` (banco real; concorrência com threads; RLS; fuso e horário de verão; privacidade) | local (Postgres 16) e CI (Postgres 17) | APROVADO |
| 121 testes de navegador (Playwright + axe-core 4.14.0: WCAG A, AA, 2.1, 2.2 e boas práticas, tema claro e escuro, reflow, texto a 200%, teclado, celular, privacidade do visitante) | local (Chrome), CI (Chromium) e **no site publicado** | APROVADO nos três |
| gitleaks no histórico inteiro, `pip-audit` e `npm audit` | CI | APROVADO |
| 5 reservas simultâneas do mesmo horário atrás do pooler do Neon | site publicado | 1 venceu, 4 recusadas (409) |
| Workflow de manutenção (ping e limpeza diária) | GitHub Actions, em produção | APROVADO (os dois jobs) |

## Evidências por controle

### S01 Segredos e Git

| ID | Crit. | Teste ou inspeção | Esperado | Observado | Estado | Evidência |
| --- | --- | --- | --- | --- | --- | --- |
| S01-01 | Bloqueador | gitleaks com `fetch-depth: 0` | Nenhum segredo no histórico | Passou em todos os PRs | APROVADO | job `security` do CI |
| S01-02 | Bloqueador | Inspeção de `.gitignore`, `.env.example` | `.env` ignorado; exemplo sem valores | Conforme | APROVADO | `.gitignore`, `.env.example` |
| S01-03 | Bloqueador | Segredos de produção só no painel do Render e no GitHub Secrets | Nenhum valor no repositório | `DATABASE_URL`, `SECRET_KEY`, `CRON_SECRET` só nos painéis; `render.yaml` usa `sync: false` e `generateValue` | APROVADO | `render.yaml`; painel do Render (valores mascarados) |
| S01-04 | Bloqueador | Teste de configuração | Produção recusa `SECRET_KEY` ausente ou curta | Levanta `RuntimeError` | APROVADO | `tests/test_privacidade.py::test_producao_exige_uma_chave_secreta_boa` |
| S01-05 | Recomendado | Artefato de build | Wheel só com o pacote | 4 migrações, 33 templates, estáticos | APROVADO | build do Render simulado em venv limpo e build real |
| S01-06 | Recomendado | A connection string do Neon foi colada por engano no campo `BASE_URL` do Render durante o deploy e exibida numa captura de tela da sessão | Segredo só onde deve estar | Corrigido no mesmo dia; a senha do banco **deve ser trocada** (ver Pendências) | NÃO VERIFICADO | histórico desta sessão |

### S02 Autenticação e autorização

| ID | Crit. | Teste ou inspeção | Esperado | Observado | Estado | Evidência |
| --- | --- | --- | --- | --- | --- | --- |
| S02-01 | Bloqueador | Senha guardada | Argon2id; mínimo 10 caracteres; lista de senhas óbvias | `$argon2id$` no banco | APROVADO | `tests/test_contas.py` |
| S02-02 | Bloqueador | Cookie no endereço final | `__Host-sessao`, `Secure`, `HttpOnly`, `SameSite=Lax`, sem `Domain` | `Set-Cookie: __Host-sessao=…; HttpOnly; Max-Age=2592000; Path=/; SameSite=lax; Secure` | APROVADO | `curl -D` no site publicado |
| S02-03 | Bloqueador | Acesso direto sem login | Painel redireciona; isolamento por profissional | `/painel` e filhos: 303 para `/entrar`; um profissional recebe 404 em serviço, folga, reserva, link e lista de espera do outro | APROVADO | `tests/test_painel.py`, `test_agenda_painel.py`, `test_divulgacao.py` |
| S02-04 | Bloqueador | Mensagem de login e recuperação | Mesma resposta para e-mail inexistente e senha/código errados | Mesma mensagem e mesmo status | APROVADO (mensagem); tempo de resposta NÃO VERIFICADO | `test_login_certo_e_errado`; hash falso para igualar o custo, sem medição |
| S02-05 | Bloqueador | Logout e recuperação | Sessão cai; código de uso único | Sessões removidas; código gasto não vale de novo | APROVADO | `tests/test_contas.py` |
| S02-06 | Bloqueador | Link secreto da reserva | 192 bits; só o hash no banco; token errado dá 404 | HMAC de 24 bytes; `bytes(token_hash)` confere | APROVADO | `tests/test_publica.py`, `test_agenda_painel.py` |
| S02-07 | Bloqueador | Entrar com Google | PKCE, `state`, `nonce`, assinatura, emissor, público e validade conferidos | Testado com chaves e provedor falsos (inclui `alg: none` e chave de outro emissor) | APROVADO (lógica); **login real contra o Google NÃO VERIFICADO** | `tests/test_contas.py`; falta o cliente OAuth do Islan |
| S02-08 | Recomendado | MFA | — | Não existe | N/A | fora do MVP (`docs/fase-2.md`); sem e-mail não há segundo fator por e-mail |
| S02-09 | Condicional | Papel administrativo | — | O produto não tem administrador | N/A | `docs/CONTEXTO.md` |

### S03 Banco e RLS

| ID | Crit. | Teste ou inspeção | Esperado | Observado | Estado | Evidência |
| --- | --- | --- | --- | --- | --- | --- |
| S03-01 | Bloqueador | SQL | Parametrizado; nenhuma entrada concatenada | `ruff` com regra `S` (bandit) no CI; só `noqa: S608` em teste com nome de tabela fixo | APROVADO | `pyproject.toml`, CI |
| S03-02 | Bloqueador | RLS por profissional | A não lê nem altera B | Verificado para serviços, reservas, folgas, origens, espera e perfil | APROVADO | `tests/test_reservas_banco.py`, `test_painel.py` |
| S03-03 | Bloqueador | Papéis e permissões | Papéis sem acesso a contas, sessões, códigos; público sem UPDATE em reservas e sem ler a espera | `InsufficientPrivilege` em todos | APROVADO | `test_papeis_restritos_nao_enxergam_contas_nem_sessoes` |
| S03-04 | Bloqueador | Sem reserva dupla | Uma vence | 12 threads por 1 vaga: 1 vence; aula de 3 vagas com 12 threads: 3 vencem | APROVADO | local, CI (Postgres 17) |
| S03-05 | Bloqueador | Mesma disputa **no Neon pelo pooler** (PgBouncer, modo transação) | Uma vence | 5 simultâneas: `[303, 409, 409, 409, 409]`, 1 reserva no painel | APROVADO | `corrida_remota.py` no site publicado |
| S03-06 | Bloqueador | Migrações no Neon | Criam papéis e rodam pelo pooler | O app subiu com `python -m encaixe.migrate` no Neon (dono `neondb_owner`); páginas com banco funcionam | APROVADO | logs do Render; 121 testes no site publicado |
| S03-07 | Recomendado | RLS não protege contra injeção de SQL | — | Mitigado por S03-01, não eliminado | NÃO VERIFICADO | limitação conhecida |
| S03-08 | Recomendado | Backup e restauração | Restauração testada | Nunca testada; o plano free do Neon tem restauração limitada | NÃO VERIFICADO | ver Pendências |

### S04 Entradas e mass assignment

| ID | Crit. | Teste ou inspeção | Esperado | Observado | Estado | Evidência |
| --- | --- | --- | --- | --- | --- | --- |
| S04-01 | Bloqueador | Campos privilegiados | Cliente não define estado, fim, duração nem token | O gatilho calcula; inserir `status='atendida'` vira `confirmada` | APROVADO | `test_reserva_recebe_fim_e_estado_do_banco_e_nao_do_cliente` |
| S04-02 | Bloqueador | Validação | Nome, WhatsApp, e-mail, datas, horários, UUID, slug e fuso validados; horário fora da grade, no passado e fora do horizonte recusados | Tabela de casos recusados | APROVADO | `tests/test_painel.py`, `test_publica.py` |
| S04-03 | Bloqueador | CSRF e origem | Formulários do painel levam o token **da própria página**; POST de outro site recusado | `Sec-Fetch-Site` com `Origin` de reserva; teste confere o token em cada formulário | APROVADO | `test_todo_formulario_do_painel_carrega_o_proprio_token_csrf` |
| S04-04 | Recomendado | Isca anti-robô e envio duplo | Isca preenchida recusada; mesmo horário duas vezes não duplica | 400; 409 | APROVADO | `tests/test_publica.py` |

### S05 Uploads

| ID | Estado | Justificativa |
| --- | --- | --- |
| S05 | N/A | Não há envio de arquivos. O QR code e as imagens são gerados no servidor, não enviados. |

### S06 Dados e respostas

| ID | Crit. | Teste ou inspeção | Esperado | Observado | Estado | Evidência |
| --- | --- | --- | --- | --- | --- | --- |
| S06-01 | Bloqueador | Respostas de erro | Sem detalhe interno | 500 e 503 só com texto amigável; `Traceback` e mensagem da exceção ausentes | APROVADO | `test_erro_inesperado_...`, `test_banco_fora_do_ar_...` |
| S06-02 | Bloqueador | Dados do cliente fora do alcance de terceiros | Público não lê reservas sem o link; views públicas sem dados pessoais | Conferido | APROVADO | `tests/test_reservas_banco.py` |
| S06-03 | Bloqueador | Nenhum IP, user agent, cookie ou referer guardado | Esquema sem essas colunas | Teste varre `information_schema` | APROVADO | `test_nenhuma_tabela_guarda_ip_nem_user_agent` |
| S06-04 | Recomendado | Anonimização e exclusão | 90 dias; espera 7; conta apagada leva tudo | Testado com relógio injetado; idempotente | APROVADO | `tests/test_privacidade.py` |
| S06-05 | Recomendado | Logs | Sem dado pessoal; o link secreto não deve ser gravado | O app roda com `--no-access-log`. **O roteador do Render pode registrar o caminho `/reserva/<token>` nos logs dele**: não verificado | NÃO VERIFICADO | `render.yaml`; ver Pendências |
| S06-06 | Recomendado | Criptografia em repouso e backup | — | Depende do provedor (Neon/AWS); não confirmado por mim | NÃO VERIFICADO | — |

### S07 HTTPS, headers e cookies

| ID | Crit. | Teste ou inspeção | Esperado | Observado | Estado | Evidência |
| --- | --- | --- | --- | --- | --- | --- |
| S07-01 | Bloqueador | HTTPS e redirecionamento no endereço final | `http://` redireciona; HSTS | `301 → https://encaixe-1rpp.onrender.com/`; `strict-transport-security: max-age=31536000` | APROVADO | `curl` no site publicado |
| S07-02 | Bloqueador | Cabeçalhos no endereço final | CSP, nosniff, frame, referrer, permissions | `content-security-policy: default-src 'none'; style-src 'self'; script-src 'self'; …; frame-ancestors 'none'`, `x-content-type-options: nosniff`, `x-frame-options: DENY`, `referrer-policy: same-origin`, `cross-origin-opener-policy: same-origin`, `cache-control: no-store` | APROVADO | `curl -I` no site publicado |
| S07-03 | Bloqueador | CSP não quebra a página | Sem erro de CSP no console em nenhuma página | 121 testes de navegador falham se houver erro no console | APROVADO | `e2e/`, local, CI e publicado |
| S07-04 | Recomendado | Certificado | Válido, emitido por autoridade pública | O Chrome (Playwright) abriu o site publicado sem erro | APROVADO | e2e no site publicado; validade e cadeia não inspecionadas |

### S08 Rate limit e bots

| ID | Crit. | Teste ou inspeção | Esperado | Observado | Estado | Evidência |
| --- | --- | --- | --- | --- | --- | --- |
| S08-01 | Bloqueador | Limites por operação | Login (5 por e-mail e 30 por IP em 15 min), cadastro (10/h), recuperação (10/h), reserva e espera (20/h), cancelar (30/h), redirecionador (120/min, sem contar acima) | Cada limite recusa (429) e recupera; outro usuário segue atendido | APROVADO | `tests/test_contas.py`, `test_publica.py`, `test_divulgacao.py` |
| S08-02 | Bloqueador | **IP do visitante atrás do Cloudflare e do Render** | Cabeçalho que o visitante escreve não contorna o limite | **FALHOU na primeira configuração** (`PROXY_HOPS=1`: 12 tentativas com `X-Forwarded-For` diferentes, todas 401). Corrigido no PR #23 com `CLIENT_IP_HEADER=cf-connecting-ip`. Depois: tentativas de uma máquina com `X-Forwarded-For` variando chegam ao 429; o Cloudflare devolve 403 a um `CF-Connecting-IP` forjado | APROVADO (não contornável por `X-Forwarded-For`); **que o limite é por visitante e não global NÃO VERIFICADO** | PR #23; `curl` no site publicado; falta o teste de um segundo aparelho |
| S08-03 | Recomendado | Limite com várias instâncias | — | Contadores em memória: valem para uma instância (o caso do Render free). Documentado | NÃO VERIFICADO | `limite.py`, `docs/fase-2.md` |
| S08-04 | Recomendado | CAPTCHA | — | Não há; usa isca e limite | N/A | decisão de acessibilidade (CAPTCHA é barreira) |

### S09 Dependências

| ID | Crit. | Teste ou inspeção | Esperado | Observado | Estado | Evidência |
| --- | --- | --- | --- | --- | --- | --- |
| S09-01 | Bloqueador | `pip-audit` (produção) e `npm audit` (testes de navegador) | Sem achado alto | Passaram em todos os PRs | APROVADO | job `security` |
| S09-02 | Recomendado | Versões fixadas | `uv.lock`, `e2e/package-lock.json`, actions por SHA | Conforme; o CI confere `requirements.txt` contra o `uv.lock` | APROVADO | `.github/workflows/ci.yml` |
| S09-03 | Recomendado | Scripts de terceiros no navegador | Nenhum | CSP `script-src 'self'` e teste de "nada sai do site" | APROVADO | e2e |
| S09-04 | Recomendado | Atualização automática (Dependabot) | — | Não configurado | NÃO VERIFICADO | pendência |

### Q01 Funcionamento, celular e navegação

| ID | Crit. | Teste ou inspeção | Esperado | Observado | Estado | Evidência |
| --- | --- | --- | --- | --- | --- | --- |
| Q01-01 | Bloqueador | Fluxo essencial do cliente, ponta a ponta, no site publicado | Escolher, marcar, ver estado, trocar, cancelar | Percorrido pelos testes de navegador (Chrome desktop e Pixel 5 emulado com toque) | APROVADO | e2e publicado |
| Q01-02 | Bloqueador | Fluxo essencial do profissional | Cadastro, página, serviços, horários, regras, folgas, agenda, lembrar, divulgação, excluir conta | Percorrido por testes de unidade e de navegador | APROVADO | `tests/`, e2e publicado |
| Q01-03 | Bloqueador | Formulários | Sucesso, erro, vazio, inválido, envio duplicado, serviço indisponível | Todos os casos, incluindo "horário perdido" e 503 do banco | APROVADO | `tests/`, e2e |
| Q01-04 | Bloqueador | 404 e rotas | 404 útil; recarregar rota interna | Página própria com status 404; endereço reservado ou inexistente não toca o banco | APROVADO | `tests/test_publica.py` |
| Q01-05 | Recomendado | Link do WhatsApp | Número com código do país e mensagem preenchida | Verificado o formato (`https://wa.me/<dígitos>?text=<texto codificado>`) e a mensagem; **abrir o `wa.me` num aparelho e no computador NÃO VERIFICADO** | NÃO VERIFICADO (formato APROVADO) | `tests/test_agenda_painel.py`, `test_painel.py` |
| Q01-06 | Recomendado | Aparelho físico | — | Só emulação (Pixel 5 no Chrome). Nenhum celular real | NÃO VERIFICADO | — |

### Q02 Desempenho

| ID | Crit. | Teste ou inspeção | Esperado | Observado | Estado | Evidência |
| --- | --- | --- | --- | --- | --- | --- |
| Q02-01 | Recomendado | Peso das páginas | Sem imagem, fonte nem JavaScript no fluxo | Só HTML e `estilo.css` (~15 KB); fonte do sistema | APROVADO | inspeção |
| Q02-02 | Recomendado | Tempo de resposta no site publicado (desta máquina, Brasil → Virginia) | Página em cerca de 1 s | 0,72 s a 1,13 s em páginas com e sem banco, com o app acordado | APROVADO (amostra pequena) | `curl -w time_total` |
| Q02-03 | Recomendado | Primeira abertura depois da hibernação do Render | ~1 min | Não medida: o ping a cada 10 min evita a hibernação | NÃO VERIFICADO | — |
| Q02-04 | Opcional | Lighthouse/PageSpeed em campo | — | Não executado | NÃO VERIFICADO | — |

### I01 Infraestrutura e publicação

| ID | Crit. | Teste ou inspeção | Esperado | Observado | Estado | Evidência |
| --- | --- | --- | --- | --- | --- | --- |
| I01-01 | Bloqueador | Build e start no destino | Sobem pelo `render.yaml` | Build pip (Python 3.12.10) e start com migração funcionaram; 1ª tentativa caiu por falta de `DATABASE_URL` (colada no campo errado) | APROVADO (após correção) | painel do Render |
| I01-02 | Bloqueador | Manutenção agendada | Ping e limpeza rodam em produção | `workflow_dispatch`: `ping` e `limpeza` com sucesso; `/interno/limpeza` sem segredo responde 404 | APROVADO | execução 40948657228 |
| I01-03 | Bloqueador | Reversão e recuperação | Plano escrito | Reverter o commit e reimplantar; banco: `pg_dump` manual. **Ensaio de reversão e de restauração NÃO VERIFICADO** | NÃO VERIFICADO | `docs/instalacao.md` |
| I01-04 | Recomendado | Cota do plano free | Cabe | Um serviço ligado o mês todo (~744 h de 750 h). Um serviço antigo (`polar`) foi **suspendido** para não consumir a cota | APROVADO | painel do Render |
| I01-05 | Recomendado | Domínio próprio | — | Não há; endereço `*.onrender.com` | N/A | `docs/CONTEXTO.md` |
| I01-06 | Recomendado | Pooler do Neon | Funciona com `set local role`, `set_config` e `pg_advisory_xact_lock` | Funciona (S03-05, S03-06) | APROVADO | ver S03 |

### V01 a V03 Presença pública

| ID | Crit. | Teste ou inspeção | Esperado | Observado | Estado | Evidência |
| --- | --- | --- | --- | --- | --- | --- |
| V01-01 | Recomendado | Idioma, título, um só `h1`, zoom permitido | Em todas as páginas | Conferido por teste de navegador | APROVADO | e2e |
| V01-02 | Recomendado | Descrições e URLs coerentes | Páginas públicas com título e descrição próprios | Início, políticas e página do profissional; páginas privadas com `noindex` | APROVADO | `tests/test_privacidade.py` |
| V02-01 | Recomendado | `robots.txt` e `sitemap.xml` | Coerentes com a intenção | Painel, reservas, redirecionador e `/interno/` bloqueados; sitemap só com início, privacidade e termos | APROVADO | `tests/test_privacidade.py` |
| V02-02 | Opcional | Search Console, `llms.txt` | — | Não usados | N/A | decisão: o produto é feito para divulgação direta |
| V03-01 | Recomendado | Favicon, prévia social, rodapé | Próprios e acessíveis | `favicon.svg`, `og.png` 1200×630 e `apple-touch-icon.png` servidos (200, PNG); metadados `og:*` | APROVADO | `tests/test_privacidade.py` |
| V03-02 | Recomendado | Prévia no WhatsApp/Instagram | — | Não conferida em ferramenta de prévia | NÃO VERIFICADO | — |
| V03-03 | Recomendado | Contato real do responsável no rodapé e na política | E-mail real | O Islan optou por **não publicar e-mail** por ora; a política aponta para as issues do GitHub e diz como apagar dados pelo próprio produto | NÃO VERIFICADO | pendência registrada |
| V03-04 | Condicional | Perfil da Empresa no Google | — | Não se aplica a um produto sem endereço comercial | N/A | — |

### D01 Privacidade e métricas

| ID | Crit. | Teste ou inspeção | Esperado | Observado | Estado | Evidência |
| --- | --- | --- | --- | --- | --- | --- |
| D01-01 | Bloqueador | Inventário de coleta | Documentado e coerente com o código | Política descreve dados, finalidade, retenção, destinatários, local dos dados (EUA) e direitos | APROVADO (coerência); adequação legal NÃO VERIFICADA | `/privacidade`, `docs/CONTEXTO.md` |
| D01-02 | Bloqueador | Quem só marca horário no navegador limpo | Nenhum cookie, nenhum armazenamento, nenhuma requisição para fora | `ctx.cookies()` vazio, `document.cookie` vazio, `localStorage`/`sessionStorage` vazios, nenhuma requisição externa | APROVADO | e2e, local, CI e publicado |
| D01-03 | Bloqueador | Dados pessoais na URL | Nunca | Nome e WhatsApp só em POST; teste de navegador confere todas as navegações | APROVADO | e2e |
| D01-04 | Recomendado | Cookies do painel | Só o de sessão (e o do login Google, por 10 min) | Conferido | APROVADO | e2e, `test_contas.py` |
| D01-05 | Opcional | Analytics e banner | — | Não há analytics, pixel nem banner (só cookie estritamente necessário) | N/A | — |
| D01-06 | Bloqueador | Análise jurídica da LGPD | Feita por quem pode | **Não houve revisão jurídica.** A política é uma descrição fiel do que o programa faz, não um parecer | NÃO VERIFICADO | — |

### Acessibilidade (WCAG 2.2 AA)

| ID | Crit. | Teste ou inspeção | Esperado | Observado | Estado | Evidência |
| --- | --- | --- | --- | --- | --- | --- |
| A11Y-01 | Bloqueador | axe-core 4.14.0 (WCAG 2.0, 2.1, 2.2 A e AA e boas práticas) em 35 páginas e estados, **nos temas claro e escuro** | 0 violações | 0 violações nas 70 combinações, no local, no CI e no site publicado | APROVADO | `e2e/test/a11y.test.mjs` |
| A11Y-02 | Bloqueador | Teclado | "Pular para o conteúdo"; foco visível e alvo de 24 px em tudo que recebe foco; marcar um horário só com o teclado | Conferido | APROVADO | e2e |
| A11Y-03 | Bloqueador | Reflow e zoom | Sem rolagem horizontal a 640 px (200%) e 320 px (400%); texto a 200% | Conferido em 14 páginas | APROVADO | e2e |
| A11Y-04 | Bloqueador | Celular | Fluxo completo por toque, com axe no meio | Pixel 5 emulado, claro e escuro | APROVADO (emulação) | e2e |
| A11Y-05 | Bloqueador | Erros ligados ao campo | `aria-invalid`, `aria-describedby`, mensagens em palavras | Conferido | APROVADO | e2e |
| A11Y-06 | Bloqueador | Leitor de tela real (NVDA, VoiceOver, TalkBack) | Usável | **Não testado.** O axe não substitui. | NÃO VERIFICADO | — |
| A11Y-07 | Recomendado | Contraste fora do alcance do axe (estados de foco, bordas) | ≥ 3:1 | Conferido pelos pares de cor do `docs/identidade.md` e pelos testes de foco; sem medição independente | APROVADO (parcial) | `estilo.css` |

## Achados da verificação (o que falhou e foi corrigido)

| # | O que falhou | Como apareceu | Correção |
| --- | --- | --- | --- |
| F-01 | **Todo formulário do painel falhava no navegador**: a macro do token CSRF era importada sem contexto e saía com valor vazio | Testes de unidade passavam (usavam o token do menu); o teste de navegador viu o 403 | PR #18; teste novo confere o token de cada formulário |
| F-02 | A CSP bloqueava os `style=""` das páginas | Erro de CSP no console do navegador | PR #18: classes no `estilo.css` |
| F-03 | O Chrome mandava `Origin: null` em todo formulário (com `Referrer-Policy: no-referrer`), e a conferência de origem recusava o cadastro | Teste manual no navegador interno | PR #6: `Sec-Fetch-Site` e `same-origin` |
| F-04 | `aria-label` que não continha o texto visível (WCAG 2.5.3); alvos pequenos; foco sem anel em campos de hora | axe e teste de foco | PR #18 |
| F-05 | A rota coringa `/{slug}` engolia o `/saude`, e o ping tocaria o banco | Teste de `/saude` sem banco | PR #10 |
| F-06 | **O limite de tentativas usava o `X-Forwarded-For` que o visitante escreve** | Experimento de 12 tentativas no site publicado | PR #23 |
| F-07 | Primeiro deploy caiu: connection string no campo errado do Render | Logs do Render | Corrigido no painel; ver S01-06 |

## Pendências

| Controle | Impacto | O que falta | Responsável | Próxima ação |
| --- | --- | --- | --- | --- |
| S01-06 | A senha do banco apareceu numa captura de tela da sessão de deploy | Trocá-la | Islan | Neon → Connect → *Reset password* e colar a nova `DATABASE_URL` no Render |
| S02-07 | O login real com Google não foi exercitado | Cliente OAuth do Google (gratuito) no console do Google; `GOOGLE_CLIENT_ID` e `GOOGLE_CLIENT_SECRET` no Render | Islan | Seguir `docs/instalacao.md`; eu confiro no endereço final |
| S08-02 | Falta provar que o limite é por visitante e não global atrás do Cloudflare | Teste de um segundo aparelho (celular em dados móveis) no `/recuperar` depois de esgotar o limite de outra máquina | Islan e Claude | Se o segundo aparelho também recebe "Muitas tentativas", trocar a estratégia de IP |
| S06-05 | O roteador do Render pode gravar o link secreto da reserva | Conferir/limitar acesso aos logs | Islan | Manter o painel do Render restrito ao dono |
| V03-03 | Sem canal privado de contato para pedidos sobre dados pessoais | Definir um e-mail e pôr em `CONTATO_EMAIL` | Islan | Variável no Render e novo deploy |
| S03-08, I01-03 | Backup e restauração nunca testados | `pg_dump` e restauração de ensaio | Islan | Rotina mensal |
| S09-04 | Sem atualização automática de dependências | Ativar o Dependabot | Islan | Opcional |
| Contas de teste | Restam no banco de produção contas de teste: algumas **sem página** (testes de cadastro) e 3 com página de endereço `debug-*` (criadas à mão para diagnosticar o deploy) | Apagar | Islan | No console SQL do Neon: `delete from profissionais where slug like 'debug-%';` (leva a conta junto) e `delete from contas where email like '%@exemplo.com';` |

## Não verificado e por quê

Leitor de tela real; aparelho físico; Lighthouse e desempenho em campo; abrir o WhatsApp de verdade e enviar mensagem; login real com Google; primeira abertura depois da hibernação; restauração de backup; criptografia em repouso e backups do Neon; revisão jurídica da LGPD; prévia de compartilhamento nas redes; tempo de resposta do login (ataque por tempo).

## Plano de recuperação

1. Algo quebrou depois de um deploy: reverter o commit na `main` (`git revert`, PR com CI verde) e deixar o Render reimplantar (`autoDeployTrigger: checksPass`).
2. Banco indisponível: o app responde 503 com `Retry-After`; o Neon acorda sozinho em segundos. Se a cota mensal acabar, o banco suspende até o mês seguinte e nada é apagado.
3. Vazamento de `SECRET_KEY`: trocar o valor invalida os links de reserva já enviados (aceitável) e as sessões de login em andamento.
4. Vazamento de `DATABASE_URL`: resetar a senha no Neon e atualizar o Render.

## Limites da verificação

O resultado vale para a versão, o ambiente e o escopo acima. Este relatório não afirma segurança absoluta nem conformidade legal completa. Os testes de carga foram propositalmente pequenos (5 e 12 requisições simultâneas) para não gerar carga em produção. A acessibilidade foi verificada por automação (axe), por testes de teclado, zoom e celular emulado, e **não por pessoas com deficiência nem por tecnologia assistiva real**.
