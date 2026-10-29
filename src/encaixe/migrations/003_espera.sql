-- Lista de espera: o cliente deixa nome e WhatsApp para um dia lotado, e o profissional avisa
-- pelo WhatsApp se alguém cancelar. Não há envio automático.

create table espera (
  id uuid primary key default gen_random_uuid(),
  profissional_id uuid not null,
  servico_id uuid not null,
  dia date not null,  -- no relógio do profissional
  nome text not null check (char_length(nome) between 1 and 80),
  whatsapp text not null check (whatsapp ~ '^[0-9]{10,15}$'),
  criada_em timestamptz not null default now(),
  avisada_em timestamptz,
  foreign key (servico_id, profissional_id) references servicos (id, profissional_id)
    on delete cascade,
  unique (profissional_id, servico_id, dia, whatsapp)
);

create index espera_dia_idx on espera (profissional_id, dia);

alter table espera enable row level security;

create policy espera_painel on espera for all to encaixe_painel
  using (profissional_id = enc_pro()) with check (profissional_id = enc_pro());
-- O público só entra na fila: não lê a lista (que tem o WhatsApp de outras pessoas).
create policy espera_publico_entrar on espera for insert to encaixe_publico
  with check (profissional_id = enc_pro());

grant select, update (avisada_em), delete on espera to encaixe_painel;
grant insert (profissional_id, servico_id, dia, nome, whatsapp) on espera to encaixe_publico;

-- Quem tem o link da reserva precisa ver o nome do serviço mesmo que o profissional o tenha
-- desativado depois.
drop policy servicos_publico on servicos;
create policy servicos_publico on servicos for select to encaixe_publico
  using (
    profissional_id = enc_pro()
    and (ativo or exists (
      select 1 from reservas r where r.servico_id = servicos.id and r.token_hash = enc_token()
    ))
  );

-- O cliente não atualiza a própria reserva direto: o papel público perde o UPDATE e ganha três
-- funções que só fazem a transição certa. Assim nem um erro no app deixa o cliente se marcar como
-- "atendida", mudar o horário ou escrever em outra coluna.
drop policy reservas_publico_mudar on reservas;
revoke update on reservas from encaixe_publico;

create function cancelar_pelo_cliente(hash bytea) returns boolean
language plpgsql security definer set search_path = public, pg_temp
as $$
begin
  update reservas set status = 'cancelada_cliente' where token_hash = hash and status = 'confirmada';
  return found;
end $$;

-- Marca a antiga como remarcada, apontando para a nova (que o app insere logo em seguida, na
-- mesma transação: a chave estrangeira só é conferida no fim).
create function remarcar_pelo_cliente(hash bytea, nova uuid) returns boolean
language plpgsql security definer set search_path = public, pg_temp
as $$
begin
  update reservas set status = 'remarcada', remarcada_para = nova
  where token_hash = hash and status = 'confirmada';
  return found;
end $$;

-- Só depois que a reserva acabou ou foi cancelada: apagar os dados de uma reserva futura
-- deixaria o profissional sem saber quem vem.
create function apagar_dados_da_reserva(hash bytea) returns boolean
language plpgsql security definer set search_path = public, pg_temp
as $$
begin
  update reservas
  set cliente_nome = 'Cliente removido', cliente_whatsapp = null, cliente_email = null,
      anonimizada_em = now()
  where token_hash = hash and anonimizada_em is null and (status <> 'confirmada' or fim <= now());
  return found;
end $$;

-- Para a página da reserva antiga mostrar "remarcada para ...", sem abrir a nova reserva.
create function sucessora_da_reserva(hash bytea) returns table (inicio timestamptz, status text)
language sql stable security definer set search_path = public, pg_temp
as $$
  select n.inicio, n.status from reservas o join reservas n on n.id = o.remarcada_para
  where o.token_hash = hash
$$;

revoke execute on function cancelar_pelo_cliente(bytea), remarcar_pelo_cliente(bytea, uuid),
  apagar_dados_da_reserva(bytea), sucessora_da_reserva(bytea) from public;
grant execute on function cancelar_pelo_cliente(bytea), remarcar_pelo_cliente(bytea, uuid),
  apagar_dados_da_reserva(bytea), sucessora_da_reserva(bytea) to encaixe_publico;
