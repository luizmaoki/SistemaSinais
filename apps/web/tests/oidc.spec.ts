import { test, expect, request as requestContext, type Page } from "@playwright/test";
import type { AlertRule, AssetPage, Collection, Session, Watchlist } from "../../../packages/shared-types";

test.skip(process.env.E2E_AUTH_MODE !== "oidc", "Requer o stack OIDC local com Keycloak e usuários sintéticos.");

async function login(page: Page, username: "alice" | "bob") {
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Entrar no ambiente demo" })).toHaveCount(0);
  const loginResponse = page.waitForResponse(response => new URL(response.url()).pathname === "/api/v1/auth/login" && response.status() === 302);
  await page.getByRole("button", { name: "Entrar com Keycloak" }).click();
  const flowCookies = await (await loginResponse).headerValues("set-cookie");
  expect(flowCookies.some(cookie => cookie.startsWith("ci_oidc_flow=") && cookie.includes("HttpOnly") && cookie.includes("Path=/api/v1/auth") && cookie.toLowerCase().includes("samesite=lax"))).toBe(true);
  await expect(page).toHaveURL(/\/realms\/capital\/protocol\/openid-connect\/auth/);
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(username === "alice" ? "Alice-local-only-2026!" : "Bob-local-only-2026!");
  const callbackResponse = page.waitForResponse(response => new URL(response.url()).pathname === "/api/v1/auth/callback" && response.status() === 302);
  await page.locator("#kc-login").click();
  const cookies = await (await callbackResponse).headerValues("set-cookie");
  expect(cookies.some(cookie => cookie.startsWith("ci_session=") && cookie.includes("HttpOnly") && cookie.includes("Path=/api/v1"))).toBe(true);
  expect(cookies.some(cookie => cookie.startsWith("ci_oidc_flow=") && cookie.includes("Max-Age=0"))).toBe(true);
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByTestId("identity-badge")).toHaveText("AUTENTICADO");
}

test("OIDC real: persisted DEMO resources, CSRF, logout revocation and Alice/Bob isolation", async ({ page, browser, baseURL }) => {
  test.setTimeout(90000);
  const origin = new URL(baseURL!).origin;
  const authConfig = await page.request.get("/api/v1/auth/config");
  expect(authConfig.status()).toBe(200);
  expect(await authConfig.json()).toMatchObject({ auth_mode: "oidc", configured: true, demo_available: false });
  for (const path of ["auth/session", "watchlists", "assets"]) expect((await page.request.get("/api/v1/" + path)).status()).toBe(401);
  await login(page, "alice");
  const alice = await (await page.request.get("/api/v1/auth/session")).json() as Session;
  expect(alice).toMatchObject({ mode: "AUTHENTICATED", auth_mode: "oidc", role: "owner" });
  expect(alice.csrf_token).toBeTruthy();
  await expect(page.getByRole("link", { name: "Conta de " + alice.user.name })).toBeVisible();
  await expect(page.getByRole("img", { name: /Gráfico de preços e volume.*Modo DEMO/ })).toBeVisible();
  const storage = await page.evaluate(() => ({ local: Object.keys(localStorage), session: Object.keys(sessionStorage), visibleCookies: document.cookie }));
  expect(storage).toEqual({ local: [], session: [], visibleCookies: "" });
  const appCookies = await page.context().cookies(origin + "/api/v1/auth/session");
  expect(appCookies.map(cookie => cookie.name)).toEqual(["ci_session"]);
  const sessionCookie = appCookies[0];
  expect(sessionCookie).toMatchObject({ httpOnly: true, sameSite: "Lax", path: "/api/v1" });
  expect(sessionCookie.value.split(".")).toHaveLength(1);

  const name = "OIDC Alice " + Date.now();
  await page.goto("/watchlists");
  await page.getByRole("textbox", { name: "Nome da watchlist" }).fill(name);
  const createdWatchlist = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/watchlists");
  await page.getByRole("button", { name: "Criar watchlist" }).click();
  const createResponse = await createdWatchlist;
  expect(createResponse.status()).toBe(201);
  expect(await createResponse.request().headerValue("x-csrf-token")).toBeTruthy();
  const watchlist = await createResponse.json() as Watchlist;
  const panel = page.locator("section").filter({ has: page.getByRole("heading", { name, exact: true }) });
  await panel.getByRole("combobox", { name: "Adicionar ativo a " + name }).selectOption({ label: "NVDA" });
  await expect(panel.locator("tbody")).toContainText("NVDA");
  await page.reload();
  await expect(panel.locator("tbody")).toContainText("NVDA");
  const assets = await (await page.request.get("/api/v1/assets?q=NVDA")).json() as AssetPage;
  const nvda = assets.items.find(asset => asset.symbol === "NVDA")!;
  expect(nvda.data_mode).toBe("DEMO");

  await page.goto("/alerts");
  await page.getByRole("combobox", { name: "Ativo do alerta" }).selectOption({ label: "NVDA" });
  await page.getByRole("spinbutton", { name: "Limiar do alerta" }).fill("1");
  const createdRule = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/alert-rules");
  await page.getByRole("button", { name: "Criar regra" }).click();
  const ruleResponse = await createdRule;
  expect(ruleResponse.status()).toBe(201);
  const rule = await ruleResponse.json() as AlertRule;
  expect(rule.data_mode).toBe("DEMO");
  await expect(page.getByText("Preço observado atende ao limiar da regra; não é recomendação.").first()).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "Pausar" }).first()).toBeVisible();
  const persistedRules = await (await page.request.get("/api/v1/alert-rules")).json() as Collection<AlertRule>;
  expect(persistedRules.items.some(item => item.id === rule.id)).toBe(true);

  for (const csrf of [undefined, "incorrect-csrf"]) {
    const denied = await page.request.post("/api/v1/watchlists", { headers: { origin, ...(csrf ? { "x-csrf-token": csrf } : {}) }, data: { name: "Must not exist" } });
    expect(denied.status()).toBe(403);
  }
  const foreign = await page.request.post("/api/v1/watchlists", { headers: { origin: "https://attacker.example", "x-csrf-token": alice.csrf_token! }, data: { name: "Foreign origin" } });
  expect(foreign.status()).toBe(403);
  expect((await foreign.json()).detail.code).toBe("INVALID_ORIGIN");
  const listsAfterDenied = await (await page.request.get("/api/v1/watchlists")).json() as Collection<Watchlist>;
  expect(listsAfterDenied.items.some(item => ["Must not exist", "Foreign origin"].includes(item.name))).toBe(false);

  await page.getByRole("button", { name: "Sair da conta" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect((await page.request.get("/api/v1/auth/session")).status()).toBe(401);
  expect((await page.context().cookies(origin + "/api/v1/auth/session")).some(cookie => cookie.name === "ci_session")).toBe(false);
  const replay = await requestContext.newContext({ baseURL, extraHTTPHeaders: { cookie: "ci_session=" + sessionCookie.value } });
  try { expect((await replay.get("/api/v1/auth/session")).status()).toBe(401); } finally { await replay.dispose(); }
  await page.goto("/watchlists");
  await expect(page).toHaveURL(/\/login$/);

  const bobContext = await browser.newContext({ baseURL });
  try {
    const bobPage = await bobContext.newPage();
    await login(bobPage, "bob");
    const bob = await (await bobPage.request.get("/api/v1/auth/session")).json() as Session;
    expect(bob.user.id).not.toBe(alice.user.id);
    expect(bob.tenant_id).not.toBe(alice.tenant_id);
    const bobLists = await (await bobPage.request.get("/api/v1/watchlists")).json() as Collection<Watchlist>;
    const bobRules = await (await bobPage.request.get("/api/v1/alert-rules")).json() as Collection<AlertRule>;
    expect(bobLists.items.some(item => item.id === watchlist.id || item.name === name)).toBe(false);
    expect(bobRules.items.some(item => item.id === rule.id)).toBe(false);
    const headers = { origin, "x-csrf-token": bob.csrf_token! };
    expect((await bobPage.request.post(`/api/v1/watchlists/${watchlist.id}/assets`, { headers, data: { asset_id: nvda.id } })).status()).toBe(404);
    expect((await bobPage.request.delete(`/api/v1/watchlists/${watchlist.id}/assets/${nvda.id}`, { headers, data: {} })).status()).toBe(404);
    expect((await bobPage.request.patch(`/api/v1/alert-rules/${rule.id}`, { headers, data: { enabled: false } })).status()).toBe(404);
    await bobPage.goto("/watchlists");
    await expect(bobPage.getByRole("heading", { name, exact: true })).toHaveCount(0);
    await bobPage.getByRole("button", { name: "Sair da conta" }).click();
    await expect(bobPage).toHaveURL(/\/login$/);
  } finally { await bobContext.close(); }
});

test("OIDC rejects an unsolicited callback and shows a recoverable login error", async ({ page }) => {
  await page.goto("/api/v1/auth/callback?code=invalid-synthetic-code&state=invalid-synthetic-state");
  await expect(page).toHaveURL(/\/login\?auth_error=/);
  await expect(page.getByRole("alert").filter({ hasText: "Não foi possível concluir o login" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Entrar com Keycloak" })).toBeEnabled();
  expect((await page.request.get("/api/v1/auth/session")).status()).toBe(401);
});
