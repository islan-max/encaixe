"""O que o cadastro preenche sozinho conforme o tipo de profissional."""

from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True)
class Categoria:
    codigo: str
    rotulo: str
    exemplos: str
    servicos: tuple[tuple[str, int, int, int], ...]  # nome, duração, folga, vagas
    discreto: bool  # lembrete sem o nome do serviço


CATEGORIAS = {
    c.codigo: c
    for c in (
        Categoria(
            "beleza",
            "Beleza",
            "Barbeiro, cabeleireira, manicure, sobrancelha",
            (("Corte", 30, 0, 1), ("Barba", 20, 0, 1), ("Corte e barba", 50, 0, 1)),
            False,
        ),
        Categoria(
            "treino",
            "Treino e aulas",
            "Personal, professor, instrutor (aula com várias vagas)",
            (("Aula em grupo", 60, 0, 6), ("Treino individual", 60, 0, 1)),
            False,
        ),
        Categoria(
            "saude",
            "Saúde",
            "Psicólogo, nutricionista, fisioterapeuta",
            (("Consulta", 50, 10, 1), ("Retorno", 30, 10, 1)),
            True,  # o nome do serviço pode revelar um tratamento
        ),
        Categoria(
            "outro", "Outro", "Qualquer outro atendimento", (("Atendimento", 60, 0, 1),), False
        ),
    )
}

# Segunda a sexta, de manhã e à tarde. O profissional ajusta na tela de horários.
HORARIO_PADRAO = {dia: ((time(9), time(12)), (time(14), time(18))) for dia in range(5)}

FUSOS = {
    "America/Sao_Paulo": "Brasília (SP, RJ, MG, sul, nordeste e GO)",
    "America/Manaus": "Amazonas (Manaus)",
    "America/Cuiaba": "Mato Grosso (Cuiabá, Campo Grande)",
    "America/Rio_Branco": "Acre (Rio Branco)",
    "America/Noronha": "Fernando de Noronha",
    "Europe/Lisbon": "Portugal (Lisboa)",
}
