# Identidade do Encaixe

## Nome e ideia

**Encaixe** vem da frase que todo autônomo responde o dia inteiro: *"Dá pra encaixar às 15h?"* Encaixar é achar o espaço certo na agenda. O símbolo são dois blocos que se encaixam (`src/encaixe/static/favicon.svg`).

## Tom de voz

Fala como um colega que conhece o ofício, não como um sistema.

- **"Você", frase curta, verbo no começo.** "Escolha o dia", "Confirmar horário", "Lembrar no WhatsApp".
- **Sem jargão.** Não existe "slot", "tenant", "token", "erro 422". Existe horário, página, link da reserva.
- **Diz o que aconteceu e o que fazer.** "Esse horário acabou de ser ocupado por outra pessoa. Escolha outro: seus dados continuam aqui."
- **Honesto sobre o que não faz.** "O Encaixe não manda mensagens: quem envia é você." "Isso não é uma reserva: nada está garantido."
- **Sem pressão e sem exclamação de sistema.** Confirmações são calmas ("Horário confirmado"); erros não culpam ("Não deu para criar a conta com esses dados").
- **Cuidado extra em saúde:** nada de motivo de consulta, mensagem neutra, "atendimento" no lugar do nome do serviço.

## Visual (direção "Zap")

Escolhida entre dez direções por simplicidade e familiaridade para quem chega do Instagram ou do WhatsApp.

- **Fonte do sistema** (`system-ui`): carrega na hora na 4G, não depende de nada de fora e combina com o celular de quem usa.
- **Verde próprio**, sem usar a marca nem o logotipo do WhatsApp (só o texto "Avisar no WhatsApp").
- Superfícies cinza-claro e cantos arredondados; botões grandes (48 px) e alvos de toque de 44 px.

| | Claro | Escuro |
| --- | --- | --- |
| Fundo | `#ffffff` | `#111b21` |
| Superfície | `#f0f2f5` | `#1f2c34` |
| Texto | `#111b21` | `#e9edef` |
| Texto secundário | `#4b5a64` | `#a6b4bc` |
| Marca (botão) | `#0b6b3a` com texto branco | `#25d366` com texto `#111b21` |
| Link | `#0b6b3a` | `#4fe08a` |
| Erro | `#b3261e` | `#ff9a92` |

Todos os pares de texto passam de 4,5:1; bordas de campo e anel de foco passam de 3:1 (conferido pelo axe nos dois temas a cada alteração).

## Onde ficam as peças

- Marca e favicon: `src/encaixe/static/favicon.svg` (o mesmo desenho aparece no topo das páginas, em `templates/base.html`).
- Imagem de compartilhamento e ícone do iPhone: `src/encaixe/static/og.png` e `apple-touch-icon.png`, geradas por `scripts/gerar_imagens.py`.
- Cores e componentes: `src/encaixe/static/estilo.css`.
