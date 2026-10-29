# Fase 2: o que ficou de fora e por quê

Cortado de propósito para fechar um MVP completo e verificado no prazo. Nada abaixo é necessário para marcar, lembrar, cancelar e divulgar.

| Item | Por que ficou de fora | Como entraria |
| --- | --- | --- |
| **E-mail ao cliente e ao profissional** | Provedores de e-mail gratuitos só enviam para terceiros com **domínio próprio verificado** (Resend, Brevo, Mailjet); o Render bloqueia SMTP, então o Gmail não serve. A confirmação ficou no link da reserva + WhatsApp. | Caixa de saída no Postgres (padrão `SKIP LOCKED`) drenada pelo mesmo agendamento da limpeza diária, com adaptador Resend por API HTTP. Ligar só quando houver domínio. |
| **Lembrete automático** | Sem API gratuita de WhatsApp. Hoje o profissional toca em "Lembrar", o que custa zero. | Com e-mail pronto, lembrete automático por e-mail na véspera. |
| **Exportar para o calendário (.ics)** | Fora do escopo escolhido para o MVP. | Botão na página da reserva e feed da agenda do profissional. |
| **Pagamento e sinal (Pix)** | O Encaixe não recebe dinheiro (evita responsabilidade financeira e custo). | Link de Pix copia-e-cola por serviço, só informativo. |
| **Equipe (vários profissionais num salão)** | Um profissional por conta mantém o modelo e o isolamento simples. | Papel de "organização" com vários profissionais; o RLS já separa por `profissional_id`. |
| **Limite de tentativas compartilhado** | Hoje é em memória: vale para uma instância (o caso do Render gratuito). | Contador em Postgres ou Redis gratuito. |
| **Verificação de e-mail da conta** | Depende de enviar e-mail. | Junto com o item de e-mail; permitiria juntar conta de senha e de Google. |
| **Importar agenda existente** | Cada ferramenta exporta de um jeito. | CSV simples. |
| **Leitor de tela e aparelho físico** | Não verificados nesta versão (ver `VERIFICACAO.md`). | Roteiro manual com NVDA/VoiceOver/TalkBack e um celular simples. |
