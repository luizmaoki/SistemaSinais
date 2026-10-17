import { test, expect } from "@playwright/test";

test.skip(process.env.E2E_AUTH_MODE === "oidc", "Fluxos demonstrativos usam a configuração de autenticação demo.");

test("demo, busca repetida, gráfico e retornos", async ({page})=>{
  await page.goto("/login");
  await page.getByRole("button",{name:"Entrar no ambiente demo"}).click();
  await expect(page).toHaveURL(/dashboard/);
  await expect(page.getByRole("img",{name:/Gráfico de preços e volume/})).toBeVisible();
  await expect(page.getByRole("heading",{name:"Retorno mês a mês"})).toBeVisible();
  await page.getByRole("textbox",{name:"Buscar ativos globalmente"}).fill("NVDA");
  await page.getByRole("button",{name:"Executar busca"}).click();
  await expect(page).toHaveURL(/markets\?q=NVDA/);
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(page.locator("tbody")).toContainText("NVDA");
  await page.getByRole("textbox",{name:"Buscar ativos globalmente"}).fill("BTC");
  await page.getByRole("button",{name:"Executar busca"}).click();
  await expect(page).toHaveURL(/markets\?q=BTC/);
  await expect(page.locator("tbody")).toContainText("BTC-USD");
  await expect(page.locator("tbody")).not.toContainText("NVDA");
  await page.getByRole("link",{name:/BTC-USD/}).click();
  await expect(page.getByRole("img",{name:/Modo DEMO/})).toBeVisible();
  await page.getByRole("combobox",{name:"Fonte da série"}).selectOption("coinbase");
  await expect(page.getByText("Coinbase não configurada; aceite pessoal necessário.").first()).toBeVisible();
  await expect(page.getByRole("img",{name:/Gráfico de preços/})).toHaveCount(0);
});

test("watchlist e regra persistem após reload", async ({page})=>{
  const name="E2E "+Date.now();
  await page.goto("/watchlists");
  await page.getByRole("textbox",{name:"Nome da watchlist"}).fill(name);
  await page.getByRole("button",{name:"Criar watchlist"}).click();
  const panel=page.locator("section").filter({has:page.getByRole("heading",{name,exact:true})});
  await expect(panel).toBeVisible();
  await panel.getByRole("combobox",{name:"Adicionar ativo a "+name}).selectOption({label:"NVDA"});
  await expect(panel.locator("tbody")).toContainText("NVDA");
  await page.reload();
  await expect(panel.locator("tbody")).toContainText("NVDA");
  await page.goto("/alerts");
  await page.getByRole("combobox",{name:"Ativo do alerta"}).selectOption({label:"NVDA"});
  await page.getByRole("spinbutton",{name:"Limiar do alerta"}).fill("1");
  await page.getByRole("button",{name:"Criar regra"}).click();
  await expect(page.getByText("Preço observado atende ao limiar da regra; não é recomendação.").first()).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button",{name:"Pausar"}).first()).toBeVisible();
});

test("macro, fontes e publicações com estados honestos", async ({page})=>{
  await page.goto("/macro");
  await expect(page.locator("tbody")).toContainText("CPI — evento demonstrativo");
  await expect(page.getByText(/DEMO — eventos simulados/)).toBeVisible();
  await page.goto("/sources");
  await expect(page.getByRole("heading",{name:"SEC EDGAR",exact:true})).toBeVisible();
  await expect(page.getByRole("heading",{name:"Coinbase Exchange",exact:true})).toBeVisible();
  const coinbase=page.locator("section").filter({has:page.getByRole("heading",{name:"Coinbase Exchange",exact:true})});
  await expect(coinbase).toContainText("NOT_CONFIGURED");
  await page.goto("/institutional");
  if(process.env.E2E_EXPECT_SEC==="true"){
    await expect(page.locator("a[href^='https://www.sec.gov/Archives/']").first()).toBeVisible();
    await expect(page.getByText(/REPORTADO · v/).first()).toBeVisible();
  } else {
    await expect(page.getByRole("heading",{name:"Filings capturados"})).toBeVisible();
  }
  await page.goto("/news");
  await expect(page.getByText(/Análise por IA não configurada/)).toBeVisible();
});

test("falha de API não cria cotações", async ({page})=>{
  await page.route("**/api/v1/assets**",route=>route.fulfill({status:503,contentType:"application/json",body:JSON.stringify({detail:{code:"UPSTREAM_UNAVAILABLE",message:"Fonte indisponível no teste"}})}));
  await page.goto("/markets");
  await expect(page.getByRole("heading",{name:"Dados indisponíveis"})).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(0);
});

test("navegação mobile e screenshot desktop", async ({page})=>{
  await page.setViewportSize({width:390,height:844});
  await page.goto("/dashboard");
  await page.getByRole("button",{name:"Abrir menu"}).click();
  await page.getByRole("link",{name:"Fontes de dados",exact:true}).click();
  await expect(page.getByRole("heading",{name:"Fontes de dados",exact:true})).toBeVisible();
  await page.setViewportSize({width:1440,height:1000});
  await page.goto("/dashboard");
  await expect(page.getByRole("img",{name:/Gráfico de preços/})).toBeVisible();
  if (process.env.E2E_EXPECT_SEC === "true") await page.locator(".event-item").first().waitFor();
  expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBeLessThan(4000);
  await page.screenshot({path:"test-results/dashboard.png",fullPage:true});
});

test("proxy rejeita origem externa", async ({request}) => {
  const response = await request.post("/api/v1/watchlists", {
    headers: {origin: "https://attacker.example"}, data: {name: "Origem rejeitada"}
  });
  expect(response.status()).toBe(403);
  expect((await response.json()).detail.code).toBe("INVALID_ORIGIN");
});
