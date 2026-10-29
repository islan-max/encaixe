# Contexto do projeto

Instância do modelo de contexto do guia. Sem segredos. "Desconhecido" = ainda não confirmado.

## Produto e ambientes

- Nome, objetivo e responsável: **Encaixe**, agenda para autônomos (barbeiro, manicure, personal, psicólogo e afins). Cada profissional tem uma página de agendamento própria; o cliente marca sem criar conta. Responsável: Islan Max (islan-max).
- Tipo: aplicação web (monolito) com páginas renderizadas no servidor.
- Público e dispositivos: profissionais autônomos e seus clientes, quase sempre no celular, vindos de um link no Instagram ou WhatsApp, às vezes em celular simples e rede 4G.
- Fluxos essenciais: (1) o profissional se cadastra, define serviços e horários e divulga o link; (2) o cliente escolhe serviço, dia e horário e marca sem conta; (3) o cliente vê o estado da reserva, cancela ou reagenda; (4) o profissional vê o dia e manda o lembrete por WhatsApp com um toque; (5) o profissional vê de onde veio cada cliente.
- Público, privado e administrativo: público = página do profissional, página da reserva (link secreto), política e termos. Privado = painel do profissional (dados dele e dos clientes dele). Administrativo: não há papel de administrador no produto; a operação é feita por linha de comando e pelos painéis do Render e do Neon.
- Domínios e ambientes: repositório `github.com/islan-max/encaixe`. Produção: desconhecido até o deploy (Render, endereço `*.onrender.com`; sem domínio próprio).
- Escopo autorizado: construir o MVP, publicar o repositório e fazer o deploy gratuito até 03/11/2026.

## Implementação real

- Repositório e instruções locais: este repositório; `CLAUDE.md`.
- Runtime: Python 3.12, uv, FastAPI, Jinja2, psycopg 3 com SQL puro e migrações `.sql`. Quase nenhum JavaScript no navegador.
- Comandos: `uv sync`, `uv run ruff check`, `uv run ruff format --check`, `uv run pytest`.
- Autenticação: e-mail e senha (Argon2id) com códigos de recuperação e login com Google (OIDC); sessão em cookie, guardada no banco. Cliente final não tem conta: acessa a reserva por link secreto.
- Banco: Postgres (Neon free em São Paulo). Isolamento por profissional com RLS. Sem armazenamento de arquivos nem upload.
- Hospedagem: Render free (aplicação) + Neon free (banco). A instância pública é uma demonstração gratuita sem garantia de disponibilidade.
- Serviços externos: Neon, Render, Google (login), GitHub Actions (CI e ping). Nenhum serviço de e-mail ativo; e-mail é opcional (fase 2).
- Variáveis sensíveis (só nomes): `DATABASE_URL`, `SECRET_KEY`, `CRON_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`. Gerenciadas no painel do Render e nos segredos do GitHub.

## Dados e operação

- Dados coletados: do profissional (e-mail, hash da senha, nome, WhatsApp, serviços, horários); do cliente final (nome, WhatsApp, e-mail opcional, horário reservado, origem do link). Finalidade: agendar e lembrar. Retenção do cliente: anonimização 90 dias após o atendimento; o cliente pode apagar antes pela página da reserva. Não se guarda IP, user agent nem cookie de visitante.
- Cookies: apenas o cookie de sessão do painel (necessário ao funcionamento). Sem analytics, sem pixel, sem fonte ou script de terceiros.
- Indexação: página inicial, política e termos indexáveis; páginas de profissionais e de reservas com `noindex` (decisão do profissional não existe no MVP).
- Limites de custo: tudo gratuito. Neon: 100 CU-h/mês (o `/saude` não toca o banco para ele poder suspender); Render: 750 h/mês e hibernação em 15 min sem tráfego.
- Backup, reversão e incidentes: desconhecido até o deploy; Neon free tem restauração limitada. Reversão = reverter o commit e reimplantar. Responsável: Islan Max.
- Fora do MVP: e-mail, pagamento, equipe de vários profissionais, exportação .ics.
- Identidade: tom de colega ("você", frase curta), fonte do sistema, verde `#0B6B3A` no claro e `#25D366` no escuro, sem marca do WhatsApp.

## Seleção de módulos

| Módulo | Aplicável? | Motivo |
| --- | --- | --- |
| S01 | Sim | Git público, segredos no Render e no GitHub, gitleaks no CI |
| S02 | Sim | Login do profissional, sessões, acesso por link secreto do cliente |
| S03 | Sim | Postgres, multi-inquilino com RLS, SQL parametrizado |
| S04 | Sim | Formulários públicos e privados, campos que o cliente não pode definir |
| S05 | N/A | Sem upload nem download de arquivos do usuário (o QR é gerado, não enviado) |
| S06 | Sim | Dados pessoais de clientes, hash de senha, logs sem dado pessoal |
| S07 | Sim | HTTPS no Render, cookie de sessão, CSP e demais cabeçalhos |
| S08 | Sim | Cadastro, login, criação e cancelamento de reserva e redirecionador públicos |
| S09 | Sim | Dependências Python e Node fixadas e auditadas no CI |
| Q01, Q02, I01 | Sim | Avaliados em qualquer site |
| V01 | Sim | Página inicial e páginas legais públicas |
| V02 | Sim | robots.txt e sitemap; páginas de reserva fora do índice |
| V03 | Sim | Favicon, prévia de compartilhamento, rodapé com responsável real |
| D01 | Sim | Dados pessoais no formulário; sem analytics nem cookie de visitante |

## Decisões

| Decisão | Justificativa | Data |
| --- | --- | --- |
| Monolito FastAPI + Jinja2, sem microserviços nem JWT | Um produto para um problema; sessão no banco é revogável e mais simples | 29/10/2026 |
| Render free + Neon São Paulo; Vercel descartada | Termos da Vercel Hobby proíbem uso comercial; Render hiberna mas é aceitável | 29/10/2026 |
| Sem e-mail no MVP; link privado + WhatsApp | Provedores gratuitos exigem domínio próprio; Render bloqueia SMTP | 29/10/2026 |
| Entrada de dia por lista de links, não grade de calendário | Evita as armadilhas de acessibilidade do `role="grid"` e funciona sem JavaScript | 29/10/2026 |
| Origem do cliente por contador diário e `?v=`, sem IP | LGPD: coleta mínima; a pergunta é "de onde vieram", não "quem" | 29/10/2026 |
| Capacidade garantida por gatilho com `pg_advisory_xact_lock` por profissional | Funciona em transação, inclusive atrás do pooler do Neon | 29/10/2026 |
