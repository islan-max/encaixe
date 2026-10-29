-- Contas de profissionais. Só o contexto `sistema` (dono do banco) mexe nestas tabelas: os papéis
-- `encaixe_painel` e `encaixe_publico` não têm permissão nenhuma sobre elas.
--
-- Uma conta é de senha (e-mail + hash) OU do Google (`google_sub`), nunca as duas coisas: o e-mail
-- de senha não é verificado (não há como enviar e-mail), então juntar contas por e-mail deixaria
-- quem cadastrou o e-mail de outra pessoa entrar na conta dela.

create table contas (
  id uuid primary key default gen_random_uuid(),
  email text unique check (email = lower(email) and char_length(email) between 5 and 254),
  senha_hash text,
  google_sub text unique,
  google_email text,
  profissional_id uuid unique references profissionais (id) on delete cascade,
  criada_em timestamptz not null default now(),
  check ((email is not null and senha_hash is not null) <> (google_sub is not null))
);

create table sessoes (
  token_hash bytea primary key,
  conta_id uuid not null references contas (id) on delete cascade,
  criada_em timestamptz not null default now(),
  expira_em timestamptz not null
);

create index sessoes_conta_idx on sessoes (conta_id);

-- Sem e-mail não existe "esqueci a senha" por e-mail: estes códigos de uso único são o caminho.
create table codigos_recuperacao (
  conta_id uuid not null references contas (id) on delete cascade,
  codigo_hash bytea not null,
  usado_em timestamptz,
  primary key (conta_id, codigo_hash)
);

alter table contas enable row level security;
alter table sessoes enable row level security;
alter table codigos_recuperacao enable row level security;
-- Sem políticas e sem grants: os papéis restritos não leem nada daqui.
