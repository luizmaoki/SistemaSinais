import { test, expect, type Page } from "@playwright/test";
import type { Session } from "../../../packages/shared-types";

const owner: Session = { mode: "AUTHENTICATED", auth_mode: "oidc", user: { id: "alice", name: "Alice" }, tenant_id: "tenant-alice", role: "owner", csrf_token: "initial-csrf" };
const config = { auth_mode: "oidc", configured: true, demo_available: false, login_path: "/api/v1/auth/login" };
async function mockResources(page: Page, session: Session) {
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const body = path.endsWith("/auth/config") ? config : path.endsWith("/auth/session") ? session : path.endsWith("/watchlists") ? { items: [{ id: "list-1", name: "Acompanhamento", asset_ids: [], assets: [] }] } : path.endsWith("/alert-rules") ? { items: [{ id: "rule-1", asset_id: "asset-1", threshold: 1, direction: "above", enabled: true, source_id: "demo" }] } : { items: [], total: 0, page: 1, page_size: 100 };
    await route.fulfill({ json: body });
  });
}

test("viewer sees watchlists and rules without mutation controls", async ({ page }) => {
  await mockResources(page, { ...owner, role: "viewer" });
  await page.goto("/watchlists");
  await expect(page.getByRole("heading", { name: "Acompanhamento", exact: true })).toBeVisible();
  await expect(page.getByText(/Seu perfil permite apenas leitura/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Criar watchlist" })).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: /Adicionar ativo/ })).toHaveCount(0);
  await page.goto("/alerts");
  await expect(page.getByRole("heading", { name: "Regras persistidas" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Criar regra" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Pausar|Ativar/ })).toHaveCount(0);
  await expect(page.getByTestId("identity-badge")).toHaveText("AUTENTICADO");
  await expect(page.getByText(/Regras criadas nesta tela usam a série DEMO/)).toBeVisible();
});

test("401 redirects to login while 403 remains a permission error", async ({ page }) => {
  await mockResources(page, owner);
  await page.route("**/api/v1/watchlists", route => route.fulfill({ status: 403, json: { detail: { code: "FORBIDDEN", message: "Sem permissão neste workspace." } } }));
  await page.goto("/watchlists");
  await expect(page.getByRole("heading", { name: "Acesso negado" })).toBeVisible();
  await expect(page).toHaveURL(/\/watchlists$/);
  await expect(page.getByText(/API indisponível/)).toHaveCount(0);
  await page.route("**/api/v1/auth/session", route => route.fulfill({ status: 401, json: { detail: { code: "SESSION_REQUIRED", message: "Entre novamente." } } }));
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("button", { name: "Entrar com Keycloak" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Entrar no ambiente demo" })).toHaveCount(0);
});

test("writes and logout use freshly fetched CSRF without browser storage", async ({ page }) => {
  await mockResources(page, owner);
  let reads = 0;
  const tokens: string[] = [];
  await page.route("**/api/v1/auth/session", route => route.fulfill({ json: { ...owner, csrf_token: `csrf-${++reads}` } }));
  await page.route("**/api/v1/watchlists", async route => {
    if (route.request().method() === "POST") tokens.push(route.request().headers()["x-csrf-token"]);
    await route.fulfill({ json: route.request().method() === "POST" ? { id: "new-list" } : { items: [] } });
  });
  await page.route("**/api/v1/auth/logout", async route => {
    tokens.push(route.request().headers()["x-csrf-token"]);
    await route.fulfill({ json: { logged_out: true } });
  });
  await page.goto("/watchlists");
  await page.getByRole("textbox", { name: "Nome da watchlist" }).fill("Nova lista");
  await page.getByRole("button", { name: "Criar watchlist" }).click();
  await expect.poll(() => tokens.length).toBe(1);
  expect(tokens[0]).toBe("csrf-2");
  expect(await page.evaluate(() => ({ local: Object.keys(localStorage), session: Object.keys(sessionStorage) }))).toEqual({ local: [], session: [] });
  await page.getByRole("button", { name: "Sair da conta" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect(tokens).toEqual(["csrf-2", "csrf-3"]);
});

test("a changed account cannot submit a mutation from the previous account screen", async ({ page }) => {
  await mockResources(page, owner);
  let reads = 0;
  let writes = 0;
  await page.route("**/api/v1/auth/session", route => route.fulfill({ json: ++reads === 1 ? owner : { ...owner, user: { id: "bob", name: "Bob" }, tenant_id: "tenant-bob", csrf_token: "bob-csrf" } }));
  await page.route("**/api/v1/watchlists", async route => {
    if (route.request().method() === "POST") writes += 1;
    await route.fulfill({ json: { items: [] } });
  });
  await page.goto("/watchlists");
  await page.getByRole("textbox", { name: "Nome da watchlist" }).fill("Alice list");
  await page.getByRole("button", { name: "Criar watchlist" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect(writes).toBe(0);
});
