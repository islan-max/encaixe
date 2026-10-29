# Encaixe

**Agenda para autônomos.** Cada profissional (barbeiro, manicure, personal, psicólogo, nutricionista…) tem uma página de agendamento própria, com link curto e QR code. O cliente vê os horários livres e marca **sem criar conta**. O profissional vê o dia e manda o lembrete **com um toque no WhatsApp**. Grátis, sem mensalidade e de código aberto.

> "Dá pra encaixar às 15h?" é a frase que o autônomo responde o dia inteiro no WhatsApp. O Encaixe responde por ele.

## O que ele faz

**Para o cliente** (sem cadastro, no celular, sem JavaScript obrigatório)
- Escolhe o serviço, o dia e o horário numa sequência de telas simples.
- Recebe um link próprio da reserva, que mostra o estado dela (confirmada, cancelada, trocada, atendida), com botão "Avisar no WhatsApp" e mensagem pronta.
- Cancela ou troca o horário por esse link, dentro do prazo que o profissional definiu. Se o horário acabou de ser ocupado, escolhe outro sem digitar tudo de novo.
- Pode apagar o próprio nome e WhatsApp depois do atendimento.

**Para o profissional**
- Monta a página em um minuto: o cadastro já traz serviços e horários de exemplo para beleza, treino, saúde ou outro.
- Define serviços (duração, folga entre atendimentos, aula com várias vagas), horários por dia da semana, antecedência mínima, prazo de cancelamento, folgas e férias.
- Vê a agenda do dia, **lembra o cliente com um toque** (abre o WhatsApp com a mensagem pronta), marca quem veio ou faltou, cancela avisando o cliente e chama quem está na lista de espera.
- Cria links de divulgação (Instagram, WhatsApp, cartão) com **QR code** e vê **de onde vieram os clientes**, sem guardar IP, user agent nem cookie.

**Qualidade de produto**
- Duas pessoas escolhendo a última vaga ao mesmo tempo: uma ganha, a outra é avisada (garantido pelo banco, com teste de corrida).
- Fuso e horário de verão corretos. Atendimento individual ou aula com N vagas.
- Acessibilidade WCAG 2.2 AA conferida com axe nos temas claro e escuro, teclado, zoom e celular, em cada alteração (CI).
- Privacidade: guarda só nome e WhatsApp do cliente (e-mail opcional), anonimiza 90 dias depois do horário, sem rastreadores.

## Documentação

| Para quem | Documento |
| --- | --- |
| Profissional que vai usar | [Guia do profissional](docs/guia-do-profissional.md) |
| Quem quer hospedar o próprio Encaixe, de graça | [Instalação](docs/instalacao.md) |
| Quem vai mexer no código | [Arquitetura](docs/arquitetura.md) e [identidade](docs/identidade.md) |
| Quem quer saber o que foi testado | [Relatório de verificação](docs/VERIFICACAO.md) |
| O que ficou para depois | [Fase 2](docs/fase-2.md) |

## Rodar na sua máquina

Precisa de Python 3.12 e [uv](https://docs.astral.sh/uv/). Não precisa instalar banco: o Postgres vem embutido (`pgserver`).

```bash
uv sync
uv run python scripts/dev.py        # http://localhost:8000
```

Testes e checagens:

```bash
uv run ruff check && uv run ruff format --check
uv run pytest                        # 220+ testes, incluindo corrida de threads pelo mesmo horário
npm ci --prefix e2e && npm run --prefix e2e test:a11y   # navegador: axe, teclado, celular (precisa de Chrome ou Chromium)
```

## Limites desta versão

- É uma **demonstração gratuita**, sem garantia de disponibilidade: o plano gratuito da hospedagem hiberna sem acesso e pode demorar cerca de 1 minuto na primeira abertura. Para um negócio que depende da agenda, hospede o seu.
- **Não manda e-mail nem mensagens** (provedores gratuitos de e-mail exigem domínio próprio). A confirmação é o link da reserva mais o botão do WhatsApp; quem envia a mensagem é o profissional.
- Não cobra nem recebe pagamento; um profissional por conta (sem equipe); lembrete automático fica para a [fase 2](docs/fase-2.md).

## Licença

[MIT](LICENSE). Feito por Islan Max.
