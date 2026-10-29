# Hospedar o seu próprio Encaixe, de graça

Para quem quer ter o Encaixe no próprio nome (ou ao lado de outros profissionais) sem pagar. Leva uns 20 minutos e **não pede cartão de crédito**. Você precisa de uma conta no GitHub, no Neon (banco) e no Render (aplicação).

## O que é de graça, e os limites

Conferido nas páginas oficiais em 29/10/2026. Os planos mudam: confira antes de depender.

| Serviço | Para quê | Limites que importam | Pegadinhas |
| --- | --- | --- | --- |
| **Render** (web service free) | Roda o app | 512 MB de RAM, 750 h por mês por conta (uma instância ligada o mês todo cabe) | **Hiberna depois de 15 min sem acesso** (cerca de 1 min para acordar). O Render diz que o plano free não é para produção. **Bloqueia SMTP**, então não há e-mail por ele. O banco do próprio Render expira em 30 dias: use o Neon. |
| **Neon** (Postgres free) | Guarda os dados | 100 CU-h por mês, 1 GB por projeto, suspende sozinho após 5 min parado (acorda em poucos segundos). Plano permanente, sem cartão | Se a cota acabar, o banco suspende até o mês seguinte (nada é apagado). Restauração de backup é limitada no plano free: faça `pg_dump` de vez em quando. |
| **GitHub Actions** (repositório público) | Ping a cada 10 min e limpeza diária | Minutos grátis em repositório público | Agendamentos atrasam em horário de pico; o GitHub desativa o agendamento depois de 60 dias sem atividade no repositório. |

**Não use a Vercel Hobby:** os termos dela proíbem uso comercial, e uma agenda de profissional é uso comercial. Sobre o Render e o Neon, os termos não dizem com clareza se o plano gratuito serve a um negócio: para quem depende da agenda, o caminho seguro é um plano pago ou outra hospedagem.

## Passo a passo

### 1. Banco no Neon

1. Crie um projeto em [neon.com](https://neon.com) e escolha a **região mais perto do Render** (cada página consulta o banco várias vezes; região diferente soma latência). Se o Render ficar em Virginia, use `aws-us-east-1`.
2. Em *Connection details*, copie a **connection string** (com `?sslmode=require`). Pode usar a versão *pooled* (host com `-pooler`).

### 2. Aplicação no Render

1. No Render: **New → Blueprint**, conecte seu fork deste repositório. Ele lê o `render.yaml`.
2. Preencha as variáveis que ele pedir:
   - `DATABASE_URL`: a connection string do Neon.
   - `BASE_URL`: o endereço que o Render der ao serviço, por exemplo `https://encaixe.onrender.com` (sem barra no fim). Se ainda não souber, ponha um valor provisório e corrija depois.
   - `CRON_SECRET`: invente uma frase longa (32+ caracteres). Guarde: vai também no GitHub.
   - `CONTATO_EMAIL`: o e-mail que a política de privacidade mostra para pedidos sobre dados pessoais. Opcional, mas recomendado.
   - `GOOGLE_CLIENT_ID` e `GOOGLE_CLIENT_SECRET`: deixe em branco por enquanto.
3. O `SECRET_KEY` o Render gera sozinho. **Nunca troque depois**: ele deriva os links das reservas, e trocar invalida os links já enviados aos clientes.
4. Quando o deploy terminar, abra `BASE_URL/saude`: deve responder `{"estado":"ok"}`. Depois crie uma conta de teste em `BASE_URL/cadastrar`.

O app aplica as migrações do banco sozinho a cada partida (`python -m encaixe.migrate`).

### 3. Manter acordado e limpar dados (GitHub)

No seu repositório: *Settings → Secrets and variables → Actions → New repository secret*:

- `APP_URL`: o mesmo `BASE_URL`.
- `CRON_SECRET`: o mesmo valor que você pôs no Render.

O workflow `Manutenção` faz um ping a cada 10 minutos (para o Render não hibernar) e, uma vez por dia, chama a limpeza que anonimiza dados vencidos. O ping não toca o banco, então o Neon continua dormindo e não gasta a cota. Em *Actions → Manutenção → Run workflow* você pode rodar na hora para testar.

### 4. Entrar com Google (opcional)

1. Em [console.cloud.google.com](https://console.cloud.google.com), crie um projeto → *APIs e serviços → Credenciais → Criar credenciais → ID do cliente OAuth* → tipo **Aplicativo da Web**.
2. Em *URIs de redirecionamento autorizados*, adicione `BASE_URL/entrar/google/retorno`.
3. Copie o ID e o segredo para `GOOGLE_CLIENT_ID` e `GOOGLE_CLIENT_SECRET` no Render e reimplante. O botão "Entrar com Google" aparece sozinho quando as duas variáveis existem.
4. Pela tela de consentimento, o Encaixe só pede `openid` e `email`, que não exigem verificação do Google. Enquanto o app estiver em modo "Teste", só os e-mails que você listar conseguem entrar.

## Variáveis de ambiente

| Variável | Obrigatória | Para quê |
| --- | --- | --- |
| `DATABASE_URL` | sim | Postgres |
| `ENCAIXE_ENV` | em produção | `producao` liga cookie seguro (`__Host-`, `Secure`), HSTS e exige `SECRET_KEY` boa |
| `SECRET_KEY` | em produção | 32+ caracteres. Assina o login Google e **deriva os links das reservas** |
| `BASE_URL` | sim | Endereço público, sem barra no fim |
| `PROXY_HOPS` | recomendada | Quantos proxies de confiança há na frente do app. Com `1`, o limite de tentativas usa o endereço que o proxy acrescentou ao `X-Forwarded-For` (o mais à direita). Com `0`, usa o endereço da conexão. |
| `CRON_SECRET` | para a limpeza | Autoriza `POST /interno/limpeza` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | opcionais | Entrar com Google |
| `CONTATO_EMAIL` | opcional | E-mail mostrado na política de privacidade |
| `DB_POOL_MAX` | opcional | Conexões simultâneas por instância (padrão 5) |

## Rodar em outro lugar (sem Render)

Qualquer máquina com Python 3.12 e um Postgres 15+ serve:

```bash
uv sync --no-dev
export DATABASE_URL=postgresql://... ENCAIXE_ENV=producao SECRET_KEY=... BASE_URL=https://seu.dominio
uv run python -m encaixe.migrate
uv run uvicorn encaixe.app:app --host 0.0.0.0 --port 8000 --no-access-log
```

Ponha na frente um proxy com HTTPS (Caddy, nginx, Cloudflare) e acerte `PROXY_HOPS`. O usuário do banco precisa poder criar papéis (`create role`): as migrações criam `encaixe_painel` e `encaixe_publico` e o app troca de papel a cada requisição.

## Domínio próprio e e-mail

Com um domínio (cerca de R$ 40 por ano) você pode apontá-lo para o Render e, no futuro, ligar e-mail transacional (ver [fase 2](fase-2.md)). Sem domínio, o endereço `*.onrender.com` funciona normalmente.

## Cuidados de quem opera

- **Backup:** `pg_dump "$DATABASE_URL" > encaixe.sql` (guarde fora do repositório: tem dados pessoais).
- **Atualizar:** faça `git pull` do repositório original no seu fork; o Render reimplanta e as migrações novas rodam sozinhas.
- **Dados de terceiros:** quem hospeda é o operador dos dados dos clientes dos profissionais. Mantenha a política de privacidade (`src/encaixe/templates/privacidade.html`) coerente com o que você de fato faz (por exemplo, a região do banco) e um canal de contato real em `CONTATO_EMAIL`.
- **Segredos:** nunca no Git. O `gitleaks` roda no CI.
- **Logs:** o link da reserva é um segredo e vai no caminho da URL. O app roda com `--no-access-log` para não gravá-lo; mas a hospedagem (o roteador do Render) pode registrar o caminho nos logs dela, por isso o painel do Render deve ser acessível só por você.

## Problemas comuns

| Sintoma | Causa provável |
| --- | --- |
| A primeira página demora cerca de 1 min | O Render free estava hibernado. O ping de 10 min reduz isso; não elimina. |
| "Estamos acordando por aqui" (503) | O Neon estava suspenso; tente de novo em alguns segundos. |
| Erro `must be owner`/`permission denied to create role` na migração | O usuário do `DATABASE_URL` não pode criar papéis. No Neon, use o papel padrão do projeto (dono). |
| Login com Google dá erro | A URI de redirecionamento não é exatamente `BASE_URL/entrar/google/retorno`, ou o app está em modo "Teste" e seu e-mail não está na lista. |
| Links de reserva antigos pararam de abrir | A `SECRET_KEY` foi trocada. Volte ao valor anterior. |
| O limite de tentativas bloqueia todo mundo | `PROXY_HOPS` errado: o app está vendo o endereço do proxy como se fosse o do visitante. |
