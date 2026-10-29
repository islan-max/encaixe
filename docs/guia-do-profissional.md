# Guia do profissional

Para quem vai usar o Encaixe no dia a dia: barbeiro, cabeleireira, manicure, personal, psicólogo, nutricionista, fotógrafo… Não precisa entender de computador. Se algo não bater com o que está aqui, abra uma conversa em [github.com/islan-max/encaixe/issues](https://github.com/islan-max/encaixe/issues) (sem dados pessoais).

## O que você vai ter no fim

Um endereço seu, como `encaixe.exemplo/rafa-barbeiro`. Você divulga esse endereço (ou o QR code dele). O cliente abre no celular, escolhe o serviço, o dia e o horário, e pronto. Você vê tudo numa agenda e lembra cada cliente com um toque.

## 1. Criar a conta

1. Toque em **Criar minha página** e escreva seu e-mail e uma senha de pelo menos 10 caracteres. Uma frase fácil de lembrar é melhor que símbolos.
2. O Encaixe mostra **8 códigos de recuperação**. **Anote ou tire foto agora.** Eles são a única forma de voltar para a conta se você esquecer a senha, porque o Encaixe não manda e-mail. Cada código vale uma vez. Dá para gerar códigos novos em *Perfil*.
3. Prefere não ter senha? Use **Entrar com o Google** (quando a instalação oferecer).

## 2. Montar a página

Diga seu **nome** (o que o cliente vê), o **endereço** da página (letras minúsculas, números e hífen), seu **WhatsApp com DDD** e escolha o que você faz: *Beleza*, *Treino e aulas*, *Saúde* ou *Outro*. O Encaixe já deixa serviços e horários de exemplo prontos; você ajusta nas telas abaixo.

> **Saúde:** a página é discreta, não tem campo para contar o motivo do atendimento e o lembrete não cita o nome do serviço. Peça ao cliente para não escrever nada de saúde no nome.

## 3. Ajustar o que o cliente escolhe

Use o menu do painel: **Serviços**, **Horários**, **Regras**, **Folgas**.

- **Serviços:** nome, duração em minutos, *folga depois* (tempo para arrumar, que ninguém consegue marcar) e *vagas por horário*. Com 1 vaga é atendimento individual; com 2 ou mais é **aula em grupo**: várias pessoas no mesmo horário. O valor é opcional e só aparece na página (o Encaixe não cobra).
- **Horários:** para cada dia da semana, até dois períodos (por exemplo, manhã e tarde; o almoço é o intervalo entre eles). Deixe em branco o dia em que não atende.
- **Regras:**
  - *De quanto em quanto tempo um horário pode começar* (30 min: 9:00, 9:30, 10:00…).
  - *Antecedência mínima:* evita marcação em cima da hora.
  - *Até quanto à frente* o cliente pode marcar.
  - *Prazo para cancelar ou trocar:* depois dele, o cliente é mandado para o seu WhatsApp.
- **Folgas:** dia inteiro ou só algumas horas. Os horários somem da página. Se já houver reservas nesse período, o Encaixe avisa; ele **não cancela sozinho** (veja o item 6).

## 4. Divulgar

Em **Divulgação** você já tem três links: *Instagram*, *WhatsApp* e *Cartão e QR code*. Cada um tem:

- um endereço curto (`…/r/Ab3xK9q`) para colar na bio do Instagram, na descrição do WhatsApp Business, na legenda de um story;
- um **QR code** para baixar (PNG para imprimir, SVG para gráfica) e colar no cartão, na vitrine ou no espelho.

Cada link conta **quantas vezes foi aberto** e **quantas reservas** vieram dele. Assim você descobre de onde os clientes chegam. A contagem não guarda nenhum dado de quem abriu. Você pode criar outros links (por exemplo, "Panfleto do bairro") e esconder os que não quer ver; um link escondido continua funcionando para quem já tem o cartão impresso.

## 5. Ver o dia e lembrar o cliente

A tela **Início** é a sua agenda: horários em ordem, com o nome, o serviço e o WhatsApp de cada cliente. Em cima, os próximos 7 dias com quantos horários marcados.

- **Lembrar no WhatsApp:** abre o WhatsApp do seu celular com a mensagem pronta para aquele cliente. **Você toca em enviar.** O Encaixe não manda nada sozinho, e por isso não custa nada. Depois aparece "lembrete enviado às 08:12".
- Para mudar o texto do lembrete, vá em *Perfil*. Você pode usar `{nome}`, `{dia}`, `{hora}`, `{link}` (a reserva do cliente), `{servico}` e `{profissional}`. O *lembrete discreto* troca o nome do serviço por "atendimento".
- Depois que o horário começa, os botões viram **Atendeu** e **Faltou**. Dá para corrigir depois.

## 6. Quando o cliente (ou você) precisa cancelar

- **O cliente cancela ou troca** pelo link da reserva dele, dentro do prazo que você definiu. O horário volta para a página na hora.
- **Você cancela** tocando em *Cancelar* no horário. O Encaixe pergunta se tem certeza e, depois, oferece o botão **Avisar o cliente no WhatsApp** com a mensagem pronta.
- **Lista de espera:** quando um dia de aula fica cheio, o cliente pode deixar nome e WhatsApp. Esses nomes aparecem embaixo da agenda daquele dia, com o botão **Chamar**.

## 7. Seus dados e os dos seus clientes

- O Encaixe guarda do cliente só **nome e WhatsApp** (e e-mail, se ele quiser). Esses dados ficam anonimizados 90 dias depois do horário. Use-os apenas para o atendimento.
- O cliente pode apagar os próprios dados pela página da reserva.
- Em *Perfil → Excluir minha conta* você apaga tudo na hora: página, reservas, dados dos clientes e links.
- A política de privacidade e os termos de uso estão no rodapé do site (`/privacidade` e `/termos`).

## Perguntas frequentes

**O cliente não recebeu e-mail nenhum.** É de propósito: não existe e-mail no Encaixe. Depois de marcar, o cliente fica numa página com o estado da reserva e um botão para te avisar no WhatsApp. Peça para ele salvar o link (ou tirar um print).

**O cliente perdeu o link da reserva.** Você pode mandar de novo: em *Início*, **Lembrar no WhatsApp** já leva o link dentro da mensagem.

**Esqueci a senha.** Em *Entrar → Perdi minha senha*, use um dos 8 códigos. Sem eles e sem a senha não há como provar que a conta é sua; crie uma nova.

**Dois clientes tentaram o mesmo horário.** Só um consegue. O outro vê "esse horário acabou de ser ocupado" e escolhe outro com um toque, sem digitar de novo.

**O horário está errado por causa do fuso.** Em *Perfil*, escolha o fuso da sua cidade. O horário de verão é tratado sozinho.

**A página demorou para abrir.** A hospedagem gratuita "dorme" quando ninguém acessa e leva cerca de 1 minuto para acordar na primeira vez. Quem precisa de garantia deve [hospedar o próprio Encaixe](instalacao.md).
