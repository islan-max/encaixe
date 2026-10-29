"""Horários livres de um profissional: funções puras, sem banco. `agora` sempre entra por parâmetro.

Todo instante é um `datetime` com fuso e circula em UTC. O fuso do profissional só serve para dizer
"das 8h às 12h no relógio dele" e para mostrar datas. As regras de conflito daqui espelham o gatilho
de `migrations/001_agenda.sql`: o gatilho é quem GARANTE (sem reserva dupla); este módulo é quem
MOSTRA o que ainda cabe.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

Faixa = tuple[time, time]  # [início, fim) no relógio do profissional


def carregar_fuso(nome: str) -> ZoneInfo:
    """Nome IANA (America/Sao_Paulo). Recusa vazio, caminho e nome que não existe."""
    try:
        return ZoneInfo(nome)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError(
            "fuso horário desconhecido; use um nome IANA como America/Sao_Paulo"
        ) from None


@dataclass(frozen=True)
class Regras:
    fuso: str
    passo_min: int  # de quantos em quantos minutos um horário pode começar
    antecedencia_min: int  # minutos mínimos entre agora e o início
    dias_a_frente: int  # até quantos dias à frente aceita marcar
    cancelar_ate_min: int  # o cliente cancela até X minutos antes
    semana: Mapping[int, tuple[Faixa, ...]]  # 0 = segunda ... 6 = domingo

    @property
    def tz(self) -> ZoneInfo:
        return carregar_fuso(self.fuso)


@dataclass(frozen=True)
class Servico:
    id: str
    duracao_min: int
    folga_min: int  # tempo de arrumar depois, também ocupa a agenda
    vagas: int  # 1 = atendimento individual; N > 1 = aula com N vagas


@dataclass(frozen=True)
class Ocupada:
    """Reserva ativa. `ocupa_ate` já inclui a folga do serviço."""

    servico_id: str
    inicio: datetime
    ocupa_ate: datetime


@dataclass(frozen=True)
class Intervalo:
    inicio: datetime
    fim: datetime


@dataclass(frozen=True)
class Horario:
    inicio: datetime  # UTC
    fim: datetime  # UTC
    vagas_total: int
    vagas_livres: int
    motivo: str | None  # None = dá para marcar

    @property
    def reservavel(self) -> bool:
        return self.motivo is None


def _cruza(a_ini: datetime, a_fim: datetime, b_ini: datetime, b_fim: datetime) -> bool:
    return a_ini < b_fim and b_ini < a_fim


def _unir(faixas: Iterable[Faixa]) -> list[Faixa]:
    """Ordena e junta faixas que se tocam ou se sobrepõem."""
    unidas: list[Faixa] = []
    for ini, fim in sorted(faixas):
        if unidas and ini <= unidas[-1][1]:
            unidas[-1] = (unidas[-1][0], max(unidas[-1][1], fim))
        else:
            unidas.append((ini, fim))
    return unidas


def inicios_do_dia(regras: Regras, servico: Servico, dia: date) -> list[datetime]:
    """Instantes (UTC) em que um atendimento deste serviço pode começar no dia `dia`.

    Anda de `passo_min` em `passo_min` em UTC, da abertura da faixa até o último início em que o
    atendimento ainda termina dentro dela. Assim um dia de troca de horário de verão tem uma hora
    a menos (ou a mais) de grade, em vez de produzir horários que não existem ou que se repetem.
    Horário local inexistente na abertura vale como o primeiro instante depois da lacuna do
    relógio; local repetido, como a primeira ocorrência.
    """
    tz = regras.tz
    passo = timedelta(minutes=regras.passo_min)
    duracao = timedelta(minutes=servico.duracao_min)
    achados: set[datetime] = set()
    for ini, fim in _unir(regras.semana.get(dia.weekday(), ())):
        comeco = datetime.combine(dia, ini, tzinfo=tz).astimezone(UTC)
        fecha = datetime.combine(dia, fim, tzinfo=tz).astimezone(UTC)
        while comeco + duracao <= fecha:
            achados.add(comeco)
            comeco += passo
    return sorted(achados)


def horarios_do_dia(
    regras: Regras,
    servico: Servico,
    dia: date,
    agora: datetime,
    ocupadas: Iterable[Ocupada] = (),
    bloqueios: Iterable[Intervalo] = (),
) -> list[Horario]:
    """Todos os inícios possíveis do dia, cada um com vagas livres e, se não der, o motivo.

    Motivos: `passou`, `antecedencia`, `alem_do_horizonte`, `bloqueado` (folga do profissional),
    `ocupado` (cruza outra reserva) e `lotado` (aula sem vaga; é o que admite lista de espera).
    """
    ocupadas = list(ocupadas)
    bloqueios = list(bloqueios)
    duracao = timedelta(minutes=servico.duracao_min)
    folga = timedelta(minutes=servico.folga_min)
    saida = []
    for inicio in inicios_do_dia(regras, servico, dia):
        fim = inicio + duracao
        ocupa_ate = fim + folga
        mesma_aula = [o for o in ocupadas if o.servico_id == servico.id and o.inicio == inicio]
        livres = max(servico.vagas - len(mesma_aula), 0)
        saida.append(
            Horario(
                inicio,
                fim,
                servico.vagas,
                livres,
                _motivo(regras, servico, agora, inicio, ocupa_ate, ocupadas, bloqueios, livres),
            )
        )
    return saida


def _motivo(
    regras: Regras,
    servico: Servico,
    agora: datetime,
    inicio: datetime,
    ocupa_ate: datetime,
    ocupadas: list[Ocupada],
    bloqueios: list[Intervalo],
    livres: int,
) -> str | None:
    if inicio < agora + timedelta(minutes=regras.antecedencia_min):
        return "passou" if inicio <= agora else "antecedencia"
    if inicio > agora + timedelta(days=regras.dias_a_frente):
        return "alem_do_horizonte"
    if any(_cruza(inicio, ocupa_ate, b.inicio, b.fim) for b in bloqueios):
        return "bloqueado"
    if servico.vagas == 1:
        if any(_cruza(inicio, ocupa_ate, o.inicio, o.ocupa_ate) for o in ocupadas):
            return "ocupado"
        return None
    # Aula: só divide o horário quem é da mesma aula (mesmo serviço, mesmo início).
    for o in ocupadas:
        da_mesma_aula = o.servico_id == servico.id and o.inicio == inicio
        if not da_mesma_aula and _cruza(inicio, ocupa_ate, o.inicio, o.ocupa_ate):
            return "ocupado"
    return "lotado" if livres == 0 else None


def pode_cancelar(regras: Regras, inicio: datetime, agora: datetime) -> bool:
    """O cliente cancela até `cancelar_ate_min` antes do início, inclusive no limite exato."""
    return agora <= inicio - timedelta(minutes=regras.cancelar_ate_min)
