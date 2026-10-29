// Acessibilidade e fluxo no navegador: axe (WCAG 2.2 AA) nos temas claro e escuro em todas as
// páginas principais, reflow a 200% e 400% de zoom, teclado, celular e privacidade do visitante.
//
// Sobe o próprio Encaixe (scripts/dev.py: com DATABASE_URL usa esse banco, sem ela sobe um
// Postgres embutido), semeia dados pelo próprio site e fala com ele como um navegador.
// Local: ENCAIXE_BROWSER=chrome npm run test:a11y   Na CI: o Chromium do Playwright.
import AxeBuilder from "@axe-core/playwright";
import assert from "node:assert/strict";
import { execSync, spawn } from "node:child_process";
import { resolve } from "node:path";
import { after, before, describe, test } from "node:test";
import { fileURLToPath } from "node:url";
import { chromium, devices, request } from "playwright";

const RAIZ = resolve(fileURLToPath(new URL("../..", import.meta.url)));
// ENCAIXE_E2E_URL aponta a suíte para um site já publicado (em vez de subir o app local). Nesse
// modo os dados de teste levam um sufixo único e as contas com página são apagadas no fim.
const REMOTO = process.env.ENCAIXE_E2E_URL?.replace(/\/$/, "");
const PORTA = Number(process.env.ENCAIXE_E2E_PORTA || 8123);
const ORIGEM = REMOTO || `http://localhost:${PORTA}`;
const RUN = Date.now().toString(36);
const SUFIXO = REMOTO ? `-${RUN}` : "";
const SLUG_RAFA = `${REMOTO ? "demo-barbeiro" : "rafa-barbeiro"}${SUFIXO}`;
const SLUG_LU = `${REMOTO ? "demo-personal" : "lu-fit"}${SUFIXO}`;
const EMAIL_RAFA = REMOTO ? `rafa+${RUN}@exemplo.com` : "rafa@exemplo.com";
const EMAIL_LU = REMOTO ? `lu+${RUN}@exemplo.com` : "lu@exemplo.com";
const EMAIL_NOVO = REMOTO ? `novo+${RUN}@exemplo.com` : "novo@exemplo.com";
const SENHA = "uma frase longa e boa";
const ESQUEMAS = ["dark", "light"];
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];

let servidor, navegador;
const sessoes = {}; // storageState por conta
const S = {}; // dados semeados

// --- servidor e semente --------------------------------------------------------------------

async function subirServidor() {
  if (REMOTO) {
    const r = await fetch(`${ORIGEM}/saude`, { signal: AbortSignal.timeout(90_000) });
    assert.ok(r.ok, "o site publicado não respondeu em /saude");
    return;
  }
  servidor = spawn("uv", ["run", "python", "scripts/dev.py", "--porta", String(PORTA)], {
    cwd: RAIZ,
    env: { ...process.env, BASE_URL: ORIGEM, PYTHONUTF8: "1" },
    stdio: ["ignore", "pipe", "pipe"],
    detached: process.platform !== "win32",
  });
  let saida = "";
  servidor.stdout.on("data", (d) => (saida += d));
  servidor.stderr.on("data", (d) => (saida += d));
  const limite = Date.now() + 120_000;
  while (Date.now() < limite) {
    try {
      if ((await fetch(`${ORIGEM}/saude`)).ok) return;
    } catch {
      /* ainda subindo */
    }
    if (servidor.exitCode !== null) throw new Error(`o servidor saiu:\n${saida}`);
    await new Promise((ok) => setTimeout(ok, 500));
  }
  throw new Error(`o servidor não subiu em 120 s:\n${saida}`);
}

function derrubarServidor() {
  if (REMOTO || !servidor || servidor.exitCode !== null) return;
  try {
    if (process.platform === "win32") execSync(`taskkill /pid ${servidor.pid} /T /F`, { stdio: "ignore" });
    else process.kill(-servidor.pid, "SIGTERM");
  } catch {
    /* já saiu */
  }
}

const decodificar = (s) => s.replaceAll("&amp;", "&");
const links = (html, padrao) => [...html.matchAll(padrao)].map((m) => decodificar(m[1]));

async function criarConta(email, slug, categoria, nome) {
  const api = await request.newContext({ baseURL: ORIGEM });
  let r = await api.post("/cadastrar", { form: { email, senha: SENHA } });
  assert.ok(r.ok(), `cadastro de ${email}: ${r.status()}`);
  const csrf = (await r.text()).match(/name="csrf" value="([0-9a-f]+)"/)[1];
  if (slug) {
    r = await api.post("/painel/comecar", {
      form: { csrf, nome, slug, whatsapp: "(11) 98888-7777", categoria },
    });
    assert.ok(r.ok(), `perfil de ${slug}: ${r.status()}`);
  }
  sessoes[email] = await api.storageState();
  return { api, csrf };
}

async function diaComMuitosHorarios(api, slug, servicoLink) {
  const dias = links(await (await api.get(servicoLink)).text(), new RegExp(`href="(/${slug}\\?[^"]*dia=\\d{4}-\\d{2}-\\d{2}[^"]*)"`, "g"));
  for (const dia of dias) {
    const hs = links(await (await api.get(dia)).text(), new RegExp(`href="(/${slug}\\?[^"]*h=\\d+[^"]*)"`, "g"));
    if (hs.length >= 14) return { dia, hs };
  }
  throw new Error("nenhum dia com horários suficientes");
}

async function reservar(api, slug, link, nome) {
  const q = new URL(link, ORIGEM).searchParams;
  const r = await api.post(`/${slug}/reservar`, {
    form: { s: q.get("s"), h: q.get("h"), nome, whatsapp: "(11) 97777-6666" },
    maxRedirects: 0,
  });
  assert.equal(r.status(), 303, `reserva de ${nome}: ${r.status()}`);
  return r.headers().location.split("?")[0].replace("/reserva/", "");
}

async function semear() {
  // Rafa: barbeiro, com reservas e uma cancelada.
  const rafa = await criarConta(EMAIL_RAFA, SLUG_RAFA, "beleza", "Rafa Barbeiro");
  const home = await (await rafa.api.get(`/${SLUG_RAFA}`)).text();
  const servico = links(home, new RegExp(`href="(/${SLUG_RAFA}\\?s=[^"]+)"`, "g"))[0];
  assert.ok(servico, `sem link de serviço em /${SLUG_RAFA}: ${home.replace(/\s+/g, " ").slice(0, 400)}`);
  const { dia, hs } = await diaComMuitosHorarios(rafa.api, SLUG_RAFA, servico);
  Object.assign(S, { servico, dia, hs, diaIso: new URL(dia, ORIGEM).searchParams.get("dia"), proximo: 0 });
  S.slot = (i) => new URL(hs[i], ORIGEM).searchParams.get("h"); // o `h` do i-ésimo horário do dia
  S.tokenA = await reservar(rafa.api, SLUG_RAFA, hs[0], "Dona Maria");
  S.tokenB = await reservar(rafa.api, SLUG_RAFA, hs[1], "Seu João");
  const cancelada = await rafa.api.post(`/reserva/${S.tokenB}/cancelar`);
  assert.ok(cancelada.ok());
  const agenda = await (await rafa.api.get(`/painel?dia=${S.diaIso}`)).text();
  S.reservaId = agenda.match(/\/painel\/reservas\/([0-9a-f-]{36})\/cancelar/)[1];
  S.rafa = rafa;

  // Lu: personal com aula de 2 vagas, já cheia.
  const lu = await criarConta(EMAIL_LU, SLUG_LU, "treino", "Lu Fit");
  const servicos = await (await lu.api.get("/painel/servicos")).text();
  const aulaId = servicos.match(/href="\/painel\/servicos\/([0-9a-f-]{36})">Editar<span class="sr-only"> Aula em grupo<\/span>/)[1];
  const salvou = await lu.api.post(`/painel/servicos/${aulaId}`, {
    form: { csrf: lu.csrf, nome: "Aula em grupo", duracao: "60", folga: "0", vagas: "2", preco: "" },
  });
  assert.ok(salvou.ok());
  const aula = links(await (await lu.api.get(`/${SLUG_LU}`)).text(), new RegExp(`href="(/${SLUG_LU}\\?s=[^"]+)"`, "g"))[0];
  S.lu = lu;
  const diaAula = await diaComMuitosHorarios(lu.api, SLUG_LU, aula).catch(async () => {
    const dias = links(await (await lu.api.get(aula)).text(), new RegExp(`href="(/${SLUG_LU}\\?[^"]*dia=[^"]+)"`, "g"));
    const hs = links(await (await lu.api.get(dias[0])).text(), new RegExp(`href="(/${SLUG_LU}\\?[^"]*h=\\d+[^"]*)"`, "g"));
    return { dia: dias[0], hs };
  });
  await reservar(lu.api, SLUG_LU, diaAula.hs[0], "Aluna Ana");
  await reservar(lu.api, SLUG_LU, diaAula.hs[0], "Aluno Beto");
  S.aulaDia = diaAula.dia;

  // Conta nova, sem página ainda.
  await criarConta(EMAIL_NOVO, null, null, null);
}

function proximoHorario() {
  // Cada uso consome um horário diferente do dia semeado (a partir do terceiro).
  return S.hs[2 + S.proximo++];
}

// --- páginas -------------------------------------------------------------------------------

const preencher = (campos) => async (p) => {
  for (const [seletor, valor] of Object.entries(campos)) await p.fill(seletor, valor);
};
const enviar = (botao) => async (p) => {
  await p.click(botao);
  await p.waitForLoadState("load");
};

const PAGINAS = [
  { nome: "início", url: "/" },
  { nome: "entrar", url: "/entrar" },
  { nome: "cadastrar", url: "/cadastrar" },
  { nome: "recuperar", url: "/recuperar" },
  { nome: "privacidade", url: "/privacidade" },
  { nome: "termos", url: "/termos" },
  { nome: "página não encontrada", url: "/nada-aqui-9x", status: 404 },
  {
    nome: "entrar com erro",
    url: "/entrar",
    antes: async (p) => {
      await preencher({ "#email": "ninguem@exemplo.com", "#senha": "senha errada de novo" })(p);
      await enviar("button[type=submit]")(p);
      await p.waitForSelector(".aviso.erro");
    },
  },
  {
    nome: "cadastrar com erro",
    url: "/cadastrar",
    antes: async (p) => {
      await preencher({ "#email": "sem-arroba", "#senha": "curta" })(p);
      await enviar("button[type=submit]")(p);
      await p.waitForSelector(".erro-campo");
    },
  },
  {
    nome: "códigos de recuperação",
    url: "/cadastrar",
    antes: async (p) => {
      await preencher({ "#email": `codigos-${Date.now()}-${Math.random().toString(36).slice(2, 6)}@exemplo.com`, "#senha": SENHA })(p);
      await enviar("button[type=submit]")(p);
      await p.waitForSelector(".codigos");
    },
  },
  // Cliente, sem conta
  { nome: "cliente: serviços", url: () => `/${SLUG_RAFA}` },
  { nome: "cliente: dias", url: () => S.servico },
  { nome: "cliente: horários", url: () => S.dia },
  { nome: "cliente: dados", url: () => proximoHorario() },
  {
    nome: "cliente: dados com erro",
    url: () => proximoHorario(),
    antes: async (p) => {
      await preencher({ "#nome": "A", "#whatsapp": "123", "#email": "x" })(p);
      await enviar("button[type=submit]")(p);
      await p.waitForSelector(".erro-campo");
    },
  },
  {
    nome: "cliente: horário perdido",
    url: () => S.conflito,
    antes: async (p) => {
      const q = new URL(p.url()).searchParams;
      await preencher({ "#nome": "Dona Pressa", "#whatsapp": "(11) 96666-5555" })(p);
      // Outra pessoa pega o horário antes de ela confirmar.
      const ladrao = await request.newContext({ baseURL: ORIGEM });
      const r = await ladrao.post(`/${SLUG_RAFA}/reservar`, {
        form: { s: q.get("s"), h: q.get("h"), nome: "Seu Rápido", whatsapp: "(11) 95555-4444" },
        maxRedirects: 0,
      });
      assert.equal(r.status(), 303);
      await enviar("button[type=submit]")(p);
      await p.waitForSelector(".aviso.erro");
    },
    prepara: () => (S.conflito = proximoHorario()),
  },
  { nome: "cliente: aula cheia e lista de espera", url: () => S.aulaDia },
  { nome: "reserva confirmada", url: () => `/reserva/${S.tokenA}` },
  { nome: "reserva cancelada", url: () => `/reserva/${S.tokenB}` },
  { nome: "reserva: confirmar cancelamento", url: () => `/reserva/${S.tokenA}/cancelar` },
  { nome: "reserva: trocar horário (dias)", url: () => `/reserva/${S.tokenA}/remarcar` },
  { nome: "reserva: trocar horário (horários)", url: () => `/reserva/${S.tokenA}/remarcar?dia=${S.diaIso}` },
  // Profissional
  { nome: "painel: agenda de hoje", url: "/painel", login: EMAIL_RAFA },
  { nome: "painel: agenda com reservas", url: () => `/painel?dia=${S.diaIso}`, login: EMAIL_RAFA },
  { nome: "painel: serviços", url: "/painel/servicos", login: EMAIL_RAFA },
  {
    nome: "painel: serviços com erro",
    url: "/painel/servicos",
    login: EMAIL_RAFA,
    antes: async (p) => {
      await preencher({ "#nome": "X", "#duracao": "1", "#preco": "caro" })(p);
      await enviar("form[action='/painel/servicos'] button[type=submit]")(p);
      await p.waitForSelector(".erro-campo");
    },
  },
  { nome: "painel: horários", url: "/painel/horarios", login: EMAIL_RAFA },
  {
    nome: "painel: horários com erro",
    url: "/painel/horarios",
    login: EMAIL_RAFA,
    antes: async (p) => {
      await preencher({ "[name=d0a_ini]": "12:00", "[name=d0a_fim]": "09:00" })(p);
      await enviar("form[action='/painel/horarios'] button[type=submit]")(p);
      await p.waitForSelector(".aviso.erro");
    },
  },
  { nome: "painel: regras", url: "/painel/regras", login: EMAIL_RAFA },
  { nome: "painel: folgas", url: "/painel/folgas", login: EMAIL_RAFA },
  {
    nome: "painel: folgas com erro",
    url: "/painel/folgas",
    login: EMAIL_RAFA,
    antes: async (p) => {
      await enviar("form[action='/painel/folgas'] button[type=submit]")(p);
      await p.waitForSelector(".erro-campo");
    },
  },
  { nome: "painel: divulgação", url: "/painel/divulgacao", login: EMAIL_RAFA },
  { nome: "painel: perfil", url: "/painel/perfil", login: EMAIL_RAFA },
  { nome: "painel: excluir conta", url: "/painel/excluir-conta", login: EMAIL_RAFA },
  { nome: "painel: cancelar horário", url: () => `/painel/reservas/${S.reservaId}/cancelar?dia=${S.diaIso}`, login: EMAIL_RAFA },
  { nome: "painel: sem página ainda", url: "/painel", login: EMAIL_NOVO },
  { nome: "painel: montar página", url: "/painel/comecar", login: EMAIL_NOVO },
  {
    nome: "painel: montar página com erro",
    url: "/painel/comecar",
    login: EMAIL_NOVO,
    antes: async (p) => {
      await enviar("form[action='/painel/comecar'] button[type=submit]")(p);
      await p.waitForSelector(".erro-campo");
    },
  },
];

const resolver = (u) => (typeof u === "function" ? u() : u);

async function abrir(pagina, esquema, largura = 1280, extra = {}) {
  const ctx = await navegador.newContext({
    colorScheme: esquema,
    viewport: { width: largura, height: 900 },
    storageState: pagina.login ? sessoes[pagina.login] : undefined,
    ...extra,
  });
  const p = await ctx.newPage();
  const erros = [];
  const externas = [];
  p.on("pageerror", (e) => erros.push(String(e)));
  p.on("console", (m) => m.type() === "error" && !/status of (4|5)\d\d/.test(m.text()) && erros.push(m.text()));
  p.on("request", (r) => !r.url().startsWith(ORIGEM) && !r.url().startsWith("data:") && externas.push(r.url()));
  pagina.prepara?.();
  const resposta = await p.goto(`${ORIGEM}${resolver(pagina.url)}`);
  if (pagina.status) assert.equal(resposta.status(), pagina.status);
  if (pagina.antes) await pagina.antes(p);
  return { ctx, p, erros, externas };
}

const resumo = (violacoes) =>
  violacoes
    .map((v) => `${v.id} (${v.impact}): ${v.help}\n   ${v.nodes.map((n) => n.target.join(" ") + " — " + n.failureSummary.split("\n")[1]).join("\n   ")}`)
    .join("\n");

before(async () => {
  await subirServidor();
  navegador = await chromium.launch({ channel: process.env.ENCAIXE_BROWSER || undefined });
  await semear();
});

after(async () => {
  if (REMOTO) {
    for (const [conta, slug] of [[S.rafa, SLUG_RAFA], [S.lu, SLUG_LU]]) {
      if (!conta) continue;
      const r = await conta.api.post("/painel/excluir-conta", { form: { csrf: conta.csrf, confirmacao: slug } });
      console.log(`limpeza: conta ${slug} ${r.ok() ? "apagada" : "NÃO apagada (" + r.status() + ")"}`);
      await conta.api.dispose();
    }
  }
  await navegador?.close();
  await S.rafa?.api.dispose();
  derrubarServidor();
});

// --- os testes -----------------------------------------------------------------------------

describe("axe, WCAG 2.2 AA, nos dois temas", () => {
  for (const esquema of ESQUEMAS) {
    for (const pagina of PAGINAS) {
      test(`${pagina.nome} (${esquema})`, async () => {
        const { ctx, p, erros, externas } = await abrir(pagina, esquema);
        const r = await new AxeBuilder({ page: p }).withTags(TAGS).analyze();
        await ctx.close();
        assert.equal(r.violations.length, 0, resumo(r.violations));
        assert.deepEqual(erros, [], "erros no console");
        assert.deepEqual(externas, [], "requisição para fora do site");
      });
    }
  }
});

describe("reflow: 200% de zoom equivale a 640 px e 400%, a 320 px", () => {
  const AMOSTRA = PAGINAS.filter((p) =>
    ["início", "cadastrar", "privacidade", "cliente: serviços", "cliente: dias", "cliente: horários", "cliente: dados",
      "reserva confirmada", "painel: agenda com reservas", "painel: serviços", "painel: horários", "painel: folgas",
      "painel: divulgação", "painel: perfil"].includes(p.nome));
  for (const largura of [640, 320]) {
    for (const pagina of AMOSTRA) {
      test(`${pagina.nome} sem rolagem horizontal a ${largura}px`, async () => {
        const { ctx, p } = await abrir(pagina, "dark", largura);
        const [rolagem, janela] = await p.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
        await ctx.close();
        assert.ok(rolagem <= janela, `scrollWidth ${rolagem} > ${janela}`);
      });
    }
  }

  test("o texto cresce até 200% sem perder conteúdo nem criar rolagem horizontal", async () => {
    for (const pagina of AMOSTRA.slice(0, 8)) {
      const { ctx, p } = await abrir(pagina, "light", 1280);
      await p.evaluate(() => (document.documentElement.style.fontSize = "200%")); // pelo CSSOM: a CSP não aceita <style> inline
      const [rolagem, janela] = await p.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
      await ctx.close();
      assert.ok(rolagem <= janela, `${pagina.nome}: scrollWidth ${rolagem} > ${janela}`);
    }
  });
});

describe("teclado", () => {
  test("o primeiro Tab leva ao link 'Pular para o conteúdo', que funciona", async () => {
    const { ctx, p } = await abrir({ url: "/privacidade" }, "dark");
    await p.keyboard.press("Tab");
    assert.equal(await p.evaluate(() => document.activeElement.textContent.trim()), "Pular para o conteúdo");
    await p.keyboard.press("Enter");
    assert.equal(await p.evaluate(() => document.activeElement.id), "conteudo");
    await ctx.close();
  });

  for (const esquema of ESQUEMAS) {
    for (const nome of ["cliente: dados", "painel: agenda com reservas", "painel: horários", "painel: divulgação"]) {
      test(`todo elemento que recebe foco mostra o foco: ${nome} (${esquema})`, async () => {
        const pagina = PAGINAS.find((x) => x.nome === nome);
        const { ctx, p } = await abrir(pagina, esquema);
        const total = await p.evaluate(
          () => document.querySelectorAll("a[href], button, input:not([type=hidden]), select, textarea").length,
        );
        for (let i = 0; i < Math.min(total + 2, 60); i++) {
          await p.keyboard.press("Tab");
          const visivel = await p.evaluate(() => {
            const e = document.activeElement;
            if (!e || e === document.body) return null;
            const c = getComputedStyle(e);
            const r = e.getBoundingClientRect();
            return {
              nome: e.tagName + (e.id ? `#${e.id}` : "") + ` "${(e.textContent || e.name || "").trim().slice(0, 30)}"`,
              ok: c.outlineStyle !== "none" && parseFloat(c.outlineWidth) >= 2,
              tamanho: r.width >= 24 && r.height >= 24,
            };
          });
          if (visivel) {
            assert.ok(visivel.ok, `${visivel.nome} sem indicador de foco`);
            assert.ok(visivel.tamanho, `${visivel.nome} menor que 24x24 px`);
          }
        }
        await ctx.close();
      });
    }
  }

  test("dá para marcar um horário só com o teclado", async () => {
    const { ctx, p } = await abrir({ url: `/${SLUG_RAFA}` }, "dark");
    await p.getByRole("link", { name: /^Corte \d/ }).focus();
    await p.keyboard.press("Enter");
    await p.waitForURL(/dia|s=/);
    const dia = p.locator(`ul.dias a[href*="dia=${S.diaIso}"]`);
    await dia.focus();
    await p.keyboard.press("Enter");
    await p.waitForSelector("ul.chips");
    const horario = p.locator(`a.chip[href*="h=${S.slot(13)}"]`);
    await horario.focus();
    await p.keyboard.press("Enter");
    await p.waitForSelector("#nome");
    await p.focus("#nome");
    await p.keyboard.type("Teclado Teste");
    await p.keyboard.press("Tab");
    await p.keyboard.type("(11) 94444-3333");
    await p.keyboard.press("Enter"); // envia o formulário
    await p.waitForSelector(".estado.ok");
    assert.match(await p.textContent(".estado-titulo"), /Horário confirmado/);
    assert.match(await p.evaluate(() => location.pathname), /^\/reserva\//);
    await ctx.close();
  });

  test("campo vazio avisa em palavras, perto do campo", async () => {
    const pagina = PAGINAS.find((x) => x.nome === "cadastrar com erro");
    const { ctx, p } = await abrir(pagina, "dark");
    assert.match(await p.textContent("#email-erro"), /e-mail/i);
    assert.equal(await p.getAttribute("#email", "aria-invalid"), "true");
    assert.ok((await p.getAttribute("#email", "aria-describedby")).includes("email-erro"));
    await ctx.close();
  });
});

describe("celular", () => {
  for (const esquema of ESQUEMAS) {
    test(`marcar um horário tocando, num Pixel 5 (${esquema})`, async () => {
      const dispositivo = devices["Pixel 5"];
      const ctx = await navegador.newContext({ ...dispositivo, colorScheme: esquema });
      const p = await ctx.newPage();
      await p.goto(`${ORIGEM}/${SLUG_RAFA}`);
      await p.getByRole("link", { name: /^Corte \d/ }).tap();
      await p.locator(`ul.dias a[href*="dia=${S.diaIso}"]`).tap();
      await p.waitForSelector("ul.chips");
      await p.locator(`a.chip[href*="h=${S.slot(esquema === "dark" ? 12 : 9)}"]`).tap();
      await p.fill("#nome", "Celular Teste");
      await p.fill("#whatsapp", "(11) 93333-2222");
      const axe = await new AxeBuilder({ page: p }).withTags(TAGS).analyze();
      assert.equal(axe.violations.length, 0, resumo(axe.violations));
      await p.getByRole("button", { name: "Confirmar horário" }).tap();
      await p.waitForSelector(".estado.ok");
      const rolagem = await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
      assert.ok(rolagem, "rolagem horizontal no celular");
      await ctx.close();
    });
  }
});

describe("conteúdo e privacidade", () => {
  test("toda página tem idioma, título, um só h1 e permite zoom", async () => {
    for (const pagina of PAGINAS.filter((x) => !x.antes)) {
      const { ctx, p } = await abrir(pagina, "dark");
      const d = await p.evaluate(() => ({
        lang: document.documentElement.lang,
        titulo: document.title,
        h1: document.querySelectorAll("h1").length,
        viewport: document.querySelector('meta[name="viewport"]')?.content ?? "",
      }));
      await ctx.close();
      assert.equal(d.lang, "pt-BR", pagina.nome);
      assert.ok(d.titulo.length > 5, `${pagina.nome}: título vazio`);
      assert.equal(d.h1, 1, `${pagina.nome}: precisa de exatamente um h1 (tem ${d.h1})`);
      assert.ok(!/user-scalable\s*=\s*(no|0)|maximum-scale\s*=\s*[01](\.|$|,)/.test(d.viewport), `${pagina.nome}: bloqueia o zoom`);
    }
  });

  test("quem só marca horário não recebe cookie, não grava nada no navegador e nada sai do site", async () => {
    const { ctx, p, externas } = await abrir({ url: `/${SLUG_RAFA}` }, "dark");
    await p.getByRole("link", { name: /^Corte \d/ }).click();
    await p.locator(`ul.dias a[href*="dia=${S.diaIso}"]`).click();
    await p.locator(`a.chip[href*="h=${S.slot(11)}"]`).click();
    await p.fill("#nome", "Visitante Privado");
    await p.fill("#whatsapp", "(11) 92222-1111");
    await p.getByRole("button", { name: "Confirmar horário" }).click();
    await p.waitForSelector(".estado.ok");
    const [cookies, local, sessao] = await p.evaluate(() => [document.cookie, localStorage.length, sessionStorage.length]);
    const doContexto = await ctx.cookies();
    await ctx.close();
    assert.deepEqual(externas, []);
    assert.deepEqual(doContexto, []);
    assert.equal(cookies, "");
    assert.equal(local + sessao, 0);
  });

  test("a URL nunca leva nome nem WhatsApp", async () => {
    const { ctx, p } = await abrir({ url: `/${SLUG_RAFA}` }, "dark");
    const urls = [];
    p.on("framenavigated", (f) => urls.push(f.url()));
    await p.getByRole("link", { name: /^Corte \d/ }).click();
    await p.locator(`ul.dias a[href*="dia=${S.diaIso}"]`).click();
    await p.locator(`a.chip[href*="h=${S.slot(10)}"]`).click();
    await p.fill("#nome", "Fulano Secreto");
    await p.fill("#whatsapp", "(11) 91111-0000");
    await p.getByRole("button", { name: "Confirmar horário" }).click();
    await p.waitForSelector(".estado.ok");
    await ctx.close();
    for (const url of urls) {
      assert.ok(!/Fulano|Secreto|91111|11911/i.test(decodeURIComponent(url)), `dado pessoal na URL: ${url}`);
    }
  });
});
