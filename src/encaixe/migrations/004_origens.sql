-- Divulgação: cada profissional cria links curtos por origem (Instagram, WhatsApp, cartão...).
-- O que se guarda de um acesso é só um contador por origem e por dia: nenhum IP, nenhum user
-- agent, nenhum cookie. A pergunta que isso responde é "de onde vêm os clientes", não "quem".

create table origens (
  id uuid primary key default gen_random_uuid(),
  profissional_id uuid not null references profissionais (id) on delete cascade,
  nome text not null check (char_length(nome) between 2 and 40),
  codigo text not null unique check (codigo ~ '^[0-9A-Za-z]{7}$'),
  arquivada_em timestamptz,  -- some da lista, mas o link impresso continua funcionando
  criada_em timestamptz not null default now()
);

create index origens_profissional_idx on origens (profissional_id);

create table cliques_dia (
  origem_id uuid not null references origens (id) on delete cascade,
  dia date not null,  -- no relógio do profissional
  n int not null default 0,
  primary key (origem_id, dia)
);

alter table reservas
  add constraint reservas_origem_fk foreign key (origem_id) references origens (id);

alter table origens enable row level security;
alter table cliques_dia enable row level security;

create policy origens_painel on origens for all to encaixe_painel
  using (profissional_id = enc_pro()) with check (profissional_id = enc_pro());
create policy cliques_painel on cliques_dia for select to encaixe_painel
  using (exists (
    select 1 from origens o where o.id = cliques_dia.origem_id and o.profissional_id = enc_pro()
  ));

grant select, insert (profissional_id, nome, codigo), update (arquivada_em) on origens
  to encaixe_painel;
grant select on cliques_dia to encaixe_painel;
-- Quem escreve em cliques_dia é o contexto `sistema` (o redirecionador). O público não toca nisto.
