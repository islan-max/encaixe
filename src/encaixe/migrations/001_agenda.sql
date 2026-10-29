-- Agenda: profissionais, serviços, horários, folgas e reservas.
--
-- Três jeitos de falar com o banco (ver db.py):
--   sistema        conecta como dono: cadastro, login, limpeza diária. Ignora o RLS.
--   encaixe_painel o profissional logado. Só enxerga o que tem `profissional_id` igual ao dele.
--   encaixe_publico a página pública. Não lê reserva de ninguém; lê só a ocupação (sem dados
--                  pessoais) e a PRÓPRIA reserva, para quem tem o link secreto.
-- O sem-reserva-dupla NÃO depende do app: é o gatilho `reservas_antes_de_inserir`.

do $$
begin
  if not exists (select from pg_roles where rolname = 'encaixe_painel') then
    create role encaixe_painel nologin;
  end if;
  if not exists (select from pg_roles where rolname = 'encaixe_publico') then
    create role encaixe_publico nologin;
  end if;
end $$;

-- Para a aplicação poder fazer `set role`, quem conecta precisa ser membro dos dois papéis.
grant encaixe_painel, encaixe_publico to current_user;

create function enc_pro() returns uuid language sql stable
as $$ select nullif(current_setting('encaixe.profissional_id', true), '')::uuid $$;

create function enc_token() returns bytea language sql stable
as $$ select decode(nullif(current_setting('encaixe.token_hash', true), ''), 'hex') $$;

create table profissionais (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique check (slug ~ '^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$'),
  nome text not null check (char_length(nome) between 2 and 80),
  categoria text not null check (categoria in ('beleza', 'treino', 'saude', 'outro')),
  whatsapp text not null check (whatsapp ~ '^[0-9]{10,15}$'),  -- só dígitos, com o código do país
  fuso text not null default 'America/Sao_Paulo',
  passo_min int not null default 30 check (passo_min in (5, 10, 15, 20, 30, 60)),
  antecedencia_min int not null default 120 check (antecedencia_min between 0 and 20160),
  dias_a_frente int not null default 30 check (dias_a_frente between 1 and 180),
  cancelar_ate_min int not null default 120 check (cancelar_ate_min between 0 and 20160),
  mensagem_lembrete text not null default
    'Oi, {nome}! Passando para lembrar do seu horário {dia} às {hora}. Para ver ou cancelar: {link}'
    check (char_length(mensagem_lembrete) <= 500),
  lembrete_discreto boolean not null default false,  -- {servico} vira "atendimento" na mensagem
  criado_em timestamptz not null default now()
);

create table servicos (
  id uuid primary key default gen_random_uuid(),
  profissional_id uuid not null references profissionais (id) on delete cascade,
  nome text not null check (char_length(nome) between 2 and 80),
  duracao_min int not null check (duracao_min between 5 and 480),
  folga_min int not null default 0 check (folga_min between 0 and 120),
  vagas int not null default 1 check (vagas between 1 and 50),
  preco_centavos int check (preco_centavos is null or preco_centavos between 0 and 10000000),
  ativo boolean not null default true,
  ordem int not null default 0,
  criado_em timestamptz not null default now(),
  unique (id, profissional_id)
);

create table horarios_semanais (
  id uuid primary key default gen_random_uuid(),
  profissional_id uuid not null references profissionais (id) on delete cascade,
  dia_semana smallint not null check (dia_semana between 0 and 6),  -- 0 = segunda
  inicio time not null,
  fim time not null,
  check (fim > inicio)
);

create table bloqueios (
  id uuid primary key default gen_random_uuid(),
  profissional_id uuid not null references profissionais (id) on delete cascade,
  inicio timestamptz not null,
  fim timestamptz not null,
  motivo text check (char_length(motivo) <= 120),
  check (fim > inicio)
);

create table reservas (
  id uuid primary key default gen_random_uuid(),
  profissional_id uuid not null,
  servico_id uuid not null,
  inicio timestamptz not null,
  fim timestamptz not null,        -- o gatilho calcula a partir do serviço
  ocupa_ate timestamptz not null,  -- fim + folga do serviço, também calculado pelo gatilho
  status text not null default 'confirmada' check (status in (
    'confirmada', 'cancelada_cliente', 'cancelada_profissional', 'remarcada', 'atendida', 'faltou'
  )),
  cliente_nome text not null check (char_length(cliente_nome) between 1 and 80),
  cliente_whatsapp text check (cliente_whatsapp ~ '^[0-9]{10,15}$'),
  cliente_email text check (char_length(cliente_email) <= 254),
  token_hash bytea not null unique,  -- só o hash do link secreto fica aqui
  origem_id uuid,
  remarcada_para uuid references reservas (id) deferrable initially deferred,
  lembrete_em timestamptz,
  anonimizada_em timestamptz,
  criada_em timestamptz not null default now(),
  atualizada_em timestamptz not null default now(),
  foreign key (servico_id, profissional_id) references servicos (id, profissional_id),
  check ((status = 'remarcada') = (remarcada_para is not null)),
  check (anonimizada_em is not null or cliente_whatsapp is not null)
);

create index reservas_agenda_idx on reservas (profissional_id, inicio)
  where status in ('confirmada', 'atendida', 'faltou');

-- ---------------------------------------------------------------------------------------------
-- Gatilho de inserção: a garantia contra reserva dupla.
-- Um bloqueio de transação por profissional serializa quem disputa o mesmo horário, e vale atrás
-- do pooler do Neon porque é de transação, não de sessão. Roda como dono (security definer)
-- para enxergar todas as reservas do profissional, que o papel público não enxerga.
-- ---------------------------------------------------------------------------------------------
create function reservas_antes_de_inserir() returns trigger
language plpgsql security definer set search_path = public, pg_temp
as $$
declare
  s servicos%rowtype;
  na_aula int;
begin
  perform pg_advisory_xact_lock(hashtextextended(new.profissional_id::text, 0));

  select * into s from servicos
  where id = new.servico_id and profissional_id = new.profissional_id and ativo;
  if not found then
    raise exception 'serviço inválido' using errcode = 'EN004';
  end if;

  new.fim := new.inicio + make_interval(mins => s.duracao_min);
  new.ocupa_ate := new.fim + make_interval(mins => s.folga_min);
  new.status := 'confirmada';

  if exists (
    select 1 from bloqueios b
    where b.profissional_id = new.profissional_id
      and b.inicio < new.ocupa_ate and new.inicio < b.fim
  ) then
    raise exception 'horário bloqueado' using errcode = 'EN003';
  end if;

  if s.vagas = 1 then
    if exists (
      select 1 from reservas r
      where r.profissional_id = new.profissional_id
        and r.status in ('confirmada', 'atendida', 'faltou')
        and r.inicio < new.ocupa_ate and new.inicio < r.ocupa_ate
    ) then
      raise exception 'horário ocupado' using errcode = 'EN001';
    end if;
  else
    -- Aula: divide o horário quem é da mesma aula (mesmo serviço, mesmo início).
    if exists (
      select 1 from reservas r
      where r.profissional_id = new.profissional_id
        and r.status in ('confirmada', 'atendida', 'faltou')
        and r.inicio < new.ocupa_ate and new.inicio < r.ocupa_ate
        and not (r.servico_id = new.servico_id and r.inicio = new.inicio)
    ) then
      raise exception 'horário ocupado' using errcode = 'EN001';
    end if;
    select count(*) into na_aula from reservas r
    where r.profissional_id = new.profissional_id
      and r.status in ('confirmada', 'atendida', 'faltou')
      and r.servico_id = new.servico_id and r.inicio = new.inicio;
    if na_aula >= s.vagas then
      raise exception 'aula lotada' using errcode = 'EN002';
    end if;
  end if;
  return new;
end $$;

create trigger reservas_inserir before insert on reservas
for each row execute function reservas_antes_de_inserir();

-- A reserva é imutável: só o estado muda, em transições permitidas, e os dados do cliente só
-- mudam para serem apagados (anonimização).
create function reservas_antes_de_atualizar() returns trigger language plpgsql as $$
begin
  if (new.id, new.profissional_id, new.servico_id, new.inicio, new.fim, new.ocupa_ate,
      new.token_hash, new.origem_id, new.criada_em)
     is distinct from
     (old.id, old.profissional_id, old.servico_id, old.inicio, old.fim, old.ocupa_ate,
      old.token_hash, old.origem_id, old.criada_em) then
    raise exception 'reserva não pode ser alterada' using errcode = 'EN010';
  end if;
  if new.status <> old.status and not (
       (old.status = 'confirmada' and new.status in (
         'cancelada_cliente', 'cancelada_profissional', 'remarcada', 'atendida', 'faltou'))
    or (old.status = 'atendida' and new.status = 'faltou')
    or (old.status = 'faltou' and new.status = 'atendida')
  ) then
    raise exception 'mudança de estado não permitida' using errcode = 'EN011';
  end if;
  if old.anonimizada_em is not null and new.anonimizada_em is distinct from old.anonimizada_em then
    raise exception 'reserva já anonimizada' using errcode = 'EN012';
  end if;
  if (new.cliente_nome, new.cliente_whatsapp, new.cliente_email)
       is distinct from (old.cliente_nome, old.cliente_whatsapp, old.cliente_email)
     and new.anonimizada_em is null then
    raise exception 'dados do cliente só mudam para serem apagados' using errcode = 'EN012';
  end if;
  new.atualizada_em := now();
  return new;
end $$;

create trigger reservas_atualizar before update on reservas
for each row execute function reservas_antes_de_atualizar();

-- ---------------------------------------------------------------------------------------------
-- Leitura pública sem dado pessoal: o que a página precisa para mostrar horários livres.
-- ---------------------------------------------------------------------------------------------
create view ocupacoes_publicas with (security_barrier) as
  select profissional_id, servico_id, inicio, fim, ocupa_ate from reservas
  where status in ('confirmada', 'atendida', 'faltou') and profissional_id = enc_pro();

create view bloqueios_publicos with (security_barrier) as
  select profissional_id, inicio, fim from bloqueios where profissional_id = enc_pro();

create function profissional_id_por_slug(texto text) returns uuid
language sql stable security definer set search_path = public, pg_temp
as $$ select id from profissionais where slug = texto $$;

-- A página da reserva (/reserva/<token>) não traz o slug: o app descobre o profissional pelo hash.
create function profissional_id_da_reserva(hash bytea) returns uuid
language sql stable security definer set search_path = public, pg_temp
as $$ select profissional_id from reservas where token_hash = hash $$;

-- Só o dono do banco (o app, no contexto `sistema`) usa estas buscas.
revoke execute on function profissional_id_por_slug(text) from public;
revoke execute on function profissional_id_da_reserva(bytea) from public;

-- ---------------------------------------------------------------------------------------------
-- RLS e permissões
-- ---------------------------------------------------------------------------------------------
alter table profissionais enable row level security;
alter table servicos enable row level security;
alter table horarios_semanais enable row level security;
alter table bloqueios enable row level security;
alter table reservas enable row level security;

-- Profissional logado.
create policy profissionais_painel on profissionais for all to encaixe_painel
  using (id = enc_pro()) with check (id = enc_pro());
create policy servicos_painel on servicos for all to encaixe_painel
  using (profissional_id = enc_pro()) with check (profissional_id = enc_pro());
create policy horarios_painel on horarios_semanais for all to encaixe_painel
  using (profissional_id = enc_pro()) with check (profissional_id = enc_pro());
create policy bloqueios_painel on bloqueios for all to encaixe_painel
  using (profissional_id = enc_pro()) with check (profissional_id = enc_pro());
create policy reservas_painel on reservas for all to encaixe_painel
  using (profissional_id = enc_pro()) with check (profissional_id = enc_pro());

grant select, update (slug, nome, categoria, whatsapp, fuso, passo_min, antecedencia_min,
  dias_a_frente, cancelar_ate_min, mensagem_lembrete, lembrete_discreto)
  on profissionais to encaixe_painel;
grant select, insert, update, delete on servicos, horarios_semanais, bloqueios to encaixe_painel;
grant select, insert, update on reservas to encaixe_painel;

-- Página pública.
create policy profissionais_publico on profissionais for select to encaixe_publico
  using (id = enc_pro());
create policy servicos_publico on servicos for select to encaixe_publico
  using (profissional_id = enc_pro() and ativo);
create policy horarios_publico on horarios_semanais for select to encaixe_publico
  using (profissional_id = enc_pro());
create policy reservas_publico_ver on reservas for select to encaixe_publico
  using (token_hash = enc_token());
create policy reservas_publico_criar on reservas for insert to encaixe_publico
  with check (profissional_id = enc_pro());
create policy reservas_publico_mudar on reservas for update to encaixe_publico
  using (token_hash = enc_token())
  with check (token_hash = enc_token()
              and status in ('confirmada', 'cancelada_cliente', 'remarcada'));

grant select on profissionais, servicos, horarios_semanais to encaixe_publico;
grant select on ocupacoes_publicas, bloqueios_publicos to encaixe_publico;
grant select on reservas to encaixe_publico;
grant insert (id, profissional_id, servico_id, inicio, cliente_nome, cliente_whatsapp,
  cliente_email, token_hash, origem_id) on reservas to encaixe_publico;
grant update (status, remarcada_para, cliente_nome, cliente_whatsapp, cliente_email,
  anonimizada_em) on reservas to encaixe_publico;
