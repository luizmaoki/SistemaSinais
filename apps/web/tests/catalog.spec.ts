import { test, expect, type Page, type Route } from "@playwright/test";
import type { Asset, AssetCalendar, AssetIdentifier, Bar, CorporateActions, SeriesAdjustment, Session } from "../../../packages/shared-types";

const assetId = "11111111-1111-4111-8111-111111111111";
const otherId = "22222222-2222-4222-8222-222222222222";
const knownAt = "2026-10-08T12:00:00Z";
const owner: Session = { mode: "AUTHENTICATED", auth_mode: "oidc", user: { id: "catalog-owner", name: "Catalog Owner" }, tenant_id: "catalog-tenant", role: "owner", csrf_token: "catalog-csrf" };
const baseAsset: Asset = {
  id: assetId, symbol: "SPLIT-DEMO", display_name: "Instrumento de teste simulado", asset_type: "equity",
  venue: "DEMO", currency: "USD", timezone: "America/New_York", calendar_id: "XNYS", mic: null,
  primary_exchange: "DEMO", instrument_kind: "spot", status: "active", metadata_status: "PARTIAL",
  metadata_source_id: "demo", metadata_source_uri: "https://example.invalid/catalog", metadata_available_as_of: knownAt, metadata_ingested_at: knownAt,
  latest_price: 49, source_id: "demo", data_mode: "DEMO", updated_at: knownAt,
};
const baseCalendar: AssetCalendar = {
  calendar_id: "XNYS", timezone: "America/New_York", currency: "USD", status: "AVAILABLE", as_of: knownAt,
  items: [{ session_date: "2026-11-27", open_at: "2026-11-27T14:30:00Z", close_at: "2026-11-27T18:00:00Z" }],
};
const actionLedger: CorporateActions = {
  coverage: { from: "2026-01-30", to: "2026-02-03", source_id: "demo", data_mode: "DEMO" },
  items: [
    { id: "split-event", asset_id: assetId, action_type: "split", effective_at: "2026-02-02T14:30:00Z", details: { split_ratio: 2 }, source_id: "demo", source_uri: "https://example.invalid/actions/split", data_mode: "DEMO", available_as_of: knownAt, ingested_at: knownAt, version: 2 },
    { id: "dividend-event", asset_id: assetId, action_type: "cash_dividend", effective_at: "2026-02-03T14:30:00Z", details: { amount: 1, currency: "USD" }, source_id: "demo", source_uri: "https://example.invalid/actions/dividend", data_mode: "DEMO", available_as_of: knownAt, ingested_at: knownAt, version: 1 },
    { id: "cancelled-event", asset_id: assetId, action_type: "symbol_change", effective_at: "2026-02-03T14:30:00Z", details: { old_symbol: "OLD-DEMO", new_symbol: "CANCELLED-DEMO" }, source_id: "demo", source_uri: "https://example.invalid/actions/cancelled", data_mode: "DEMO", available_as_of: knownAt, ingested_at: knownAt, version: 1, cancelled: true },
  ],
};
function barsFor(adjustment: SeriesAdjustment): Bar[] {
  return ["2026-01-30", "2026-02-02", "2026-02-03"].map((day, index) => {
    const close = adjustment === "split_dividend_adjusted" ? 49 : adjustment === "split_adjusted" ? [50, 50, 49][index] : [100, 50, 49][index];
    return { time: day + "T14:30:00Z", close_time: day + "T21:00:00Z", open: close, high: close, low: close, close, volume: adjustment === "unadjusted" && index === 0 ? 1000 : 2000, source_id: "demo", data_mode: "DEMO" };
  });
}
interface MockOptions {
  asset?: Asset;
  assets?: Asset[];
  calendar?: AssetCalendar;
  identifiers?: AssetIdentifier[];
  actions?: CorporateActions;
  failAdjustment?: boolean;
  seriesCurrency?: string | null;
  returnRawForAdjusted?: boolean;
  waitForAdjustment?: Promise<void>;
  onRequest?: (url: URL) => void;
}
async function mockCatalog(page: Page, options: MockOptions = {}) {
  const asset = options.asset ?? baseAsset;
  await page.route("**/api/v1/**", async (route: Route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/v1", "");
    options.onRequest?.(url);
    if (path === "/auth/config") return route.fulfill({ json: { auth_mode: "oidc", configured: true, demo_available: false, login_path: "/api/v1/auth/login" } });
    if (path === "/auth/session") return route.fulfill({ json: owner });
    if (path === "/assets") {
      const assets = (options.assets ?? [asset]).filter(item => (!url.searchParams.get("venue") || item.venue === url.searchParams.get("venue")) && (!url.searchParams.get("currency") || item.currency === url.searchParams.get("currency")));
      return route.fulfill({ json: { items: assets, total: assets.length, page: 1, page_size: 100 } });
    }
    if (path === "/assets/" + asset.id) return route.fulfill({ json: asset });
    if (path.endsWith("/calendar")) return route.fulfill({ json: options.calendar ?? baseCalendar });
    if (path.endsWith("/identifiers")) return route.fulfill({ json: { items: options.identifiers ?? [{ id: "identifier-1", asset_id: asset.id, identifier_type: "ticker", value: asset.symbol, effective_from: "2026-01-01", effective_to: null, source_id: "demo", source_uri: "https://example.invalid/identifiers/1", version: 1, available_as_of: knownAt, ingested_at: knownAt }] } });
    if (path.endsWith("/corporate-actions")) return route.fulfill({ json: options.actions ?? actionLedger });
    if (path === "/watchlists") return route.fulfill({ json: { items: [{ id: "list-1", name: "Catálogo", assets: [], asset_ids: [] }] } });
    if (/\/(bars|returns|metrics)$/.test(path)) {
      const requested = (url.searchParams.get("adjustment") ?? "unadjusted") as SeriesAdjustment;
      if (requested !== "unadjusted" && options.waitForAdjustment) await options.waitForAdjustment;
      if ((requested !== "unadjusted" && options.failAdjustment) || url.searchParams.get("source") === "coinbase") return route.fulfill({ status: 409, json: { detail: { code: "ADJUSTMENT_UNAVAILABLE", message: "Cobertura de eventos insuficiente para o ajuste solicitado." } } });
      const adjustment = options.returnRawForAdjusted ? "unadjusted" : requested;
      const currency = options.seriesCurrency === undefined ? asset.currency : options.seriesCurrency;
      const provenance = { currency, calculation_status: currency == null ? "UNAVAILABLE" : "AVAILABLE", source_id: url.searchParams.get("source"), data_mode: "DEMO", adjustment, adjustment_methodology: "Fatores de preço retroativos; volume ajustado apenas por desdobramentos.", action_source_id: "demo", calendar_id: "XNYS", as_of: url.searchParams.get("as_of") };
      const content = path.endsWith("/bars") ? { items: barsFor(adjustment) } : path.endsWith("/returns") ? { items: [{ month: "2026-02", return_pct: adjustment === "split_dividend_adjusted" ? 0 : adjustment === "split_adjusted" ? -2 : -51, partial: false }] } : { sma_20: 49, sma_50: null, rsi_14: null, max_drawdown_pct: adjustment === "unadjusted" ? -51 : 0 };
      return route.fulfill({ json: { ...provenance, ...content } });
    }
    return route.fulfill({ json: { items: [] } });
  });
}
const chart = (page: Page) => page.getByRole("img", { name: /Gráfico de preços e volume/ });
const catalogue = (page: Page) => page.locator("summary").filter({ hasText: "Identificação, calendário e eventos corporativos" });

test("mock: ausência de metadados e calendário desconhecido permanecem explícitos", async ({ page }) => {
  const asset = { ...baseAsset, currency: null, primary_exchange: null, timezone: null, calendar_id: null, metadata_source_id: null, metadata_source_uri: null };
  await mockCatalog(page, { asset, identifiers: [], actions: { items: [], coverage: null }, calendar: { calendar_id: null, timezone: null, currency: null, status: "UNAVAILABLE", reason: "Venue sem calendário validado.", items: [] } });
  await page.goto("/markets/" + assetId);
  await expect(chart(page)).toBeVisible();
  await expect(page.locator(".chart-top")).toContainText("49,00 (moeda não informada)");
  await expect(page.locator(".chart-top")).not.toContainText("US$");
  await catalogue(page).click();
  await expect(page.getByTestId("catalog-metadata")).toContainText(assetId);
  await expect(page.getByTestId("catalog-metadata")).toContainText("Não informado");
  await expect(page.getByRole("heading", { name: "Calendário indisponível" })).toBeVisible();
  await expect(page.getByText("Venue sem calendário validado.")).toBeVisible();
  await expect(page.locator(".asset-catalog")).not.toContainText("XNYS");
  await expect(page.getByRole("heading", { name: "Histórico não disponível" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Nenhum evento corporativo disponível" })).toBeVisible();
});

test("mock: moeda ausente na série não herda a moeda do catálogo", async ({ page }) => {
  await mockCatalog(page, { seriesCurrency: null });
  await page.goto("/markets/" + assetId);
  await expect(chart(page)).toBeVisible();
  await expect(page.locator(".chart-top")).toContainText("49,00 (moeda não informada)");
  await expect(page.locator(".chart-top")).not.toContainText("US$");
  await expect(page.getByText(/Indicadores indisponíveis:/)).toBeVisible();
  await expect(page.locator(".metrics-grid strong")).toHaveText(["—", "—", "—", "—"]);
  await expect(page.getByRole("heading", { name: "Retornos indisponíveis", exact: true })).toBeVisible();
});
test("mock: ajuste usa a mesma fonte e disponibilidade e não exibe valores antigos", async ({ page }) => {
  const requests: URL[] = [];
  let release = () => {};
  const waitForAdjustment = new Promise<void>(resolve => { release = resolve; });
  await mockCatalog(page, { waitForAdjustment, onRequest: url => { if (/\/(bars|returns|metrics)$/.test(url.pathname)) requests.push(url); } });
  await page.goto("/markets/" + assetId);
  await expect(chart(page)).toBeVisible();
  await expect(chart(page).locator("title").first()).toContainText("100,00");
  await page.getByRole("combobox", { name: "Ajuste da série" }).selectOption("split_dividend_adjusted");
  await expect(chart(page)).toHaveCount(0);
  await expect(page.locator(".metrics-grid strong")).toHaveText(["—", "—", "—", "—"]);
  release();
  await expect(chart(page)).toHaveAccessibleName(/Ajustada por desdobramentos e dividendos/);
  await expect(chart(page).locator("title").first()).toContainText("49,00");
  await expect(page.getByText(/Dividendos em dinheiro não são reinvestidos/)).toBeVisible();
  await page.locator("summary").filter({ hasText: "Referência de disponibilidade" }).click();
  await page.getByLabel("Disponível até (UTC)").fill("2026-10-09T12:15");
  await page.getByRole("button", { name: "Aplicar referência" }).click();
  await expect(chart(page)).toBeVisible();
  await expect.poll(() => requests.filter(url => url.searchParams.get("as_of") === "2026-10-09T12:15:00.000Z").length).toBe(3);
  const selected = requests.filter(url => url.searchParams.get("as_of") === "2026-10-09T12:15:00.000Z");
  expect(new Set(selected.map(url => url.pathname.split("/").at(-1)))).toEqual(new Set(["bars", "returns", "metrics"]));
  for (const url of selected) {
    expect(url.searchParams.get("source")).toBe("demo");
    expect(url.searchParams.get("corporate_action_source")).toBe("demo");
    expect(url.searchParams.get("adjustment")).toBe("split_dividend_adjusted");
  }
  await expect(page.getByTestId("identity-badge")).toHaveText("AUTENTICADO");
  await expect(chart(page)).toHaveAccessibleName(/Modo DEMO/);
});

test("mock: ajuste indisponível oferece retorno explícito à série sem ajuste", async ({ page }) => {
  await mockCatalog(page, { failAdjustment: true });
  await page.goto("/markets/" + assetId);
  await expect(chart(page)).toBeVisible();
  await page.getByRole("combobox", { name: "Ajuste da série" }).selectOption("split_adjusted");
  await expect(page.getByText("ADJUSTMENT_UNAVAILABLE", { exact: true })).toBeVisible();
  await expect(chart(page)).toHaveCount(0);
  await expect(page.locator(".metrics-grid strong")).toHaveText(["—", "—", "—", "—"]);
  await expect(page.getByText("Retornos indisponíveis para a seleção atual.")).toBeVisible();
  await page.getByRole("button", { name: "Voltar à série sem ajuste" }).click();
  await expect(page.getByRole("combobox", { name: "Ajuste da série" })).toHaveValue("unadjusted");
  await expect(chart(page)).toHaveAccessibleName(/Sem ajuste/);
  await expect(chart(page).locator("title").first()).toContainText("100,00");
});

test("mock: resposta bruta não pode receber rótulo de série ajustada", async ({ page }) => {
  await mockCatalog(page, { returnRawForAdjusted: true });
  await page.goto("/markets/" + assetId);
  await expect(chart(page)).toBeVisible();
  await page.getByRole("combobox", { name: "Ajuste da série" }).selectOption("split_adjusted");
  await expect(page.getByText("SERIES_PROVENANCE_MISMATCH", { exact: true })).toBeVisible();
  await expect(chart(page)).toHaveCount(0);
});

test("mock: calendário usa fuso local e ledger preserva versões e origem", async ({ page }) => {
  const requests: URL[] = [];
  await mockCatalog(page, { onRequest: url => requests.push(url) });
  await page.goto("/markets/" + assetId);
  await catalogue(page).click();
  const calendar = page.locator("section").filter({ has: page.getByRole("heading", { name: "Calendário de negociação", exact: true }) });
  await expect(calendar).toContainText("America/New_York");
  await expect(calendar.locator("tbody")).toContainText("09:30");
  await expect(calendar.locator("tbody")).toContainText("13:00");
  await page.getByLabel("Calendário de", { exact: true }).fill("2026-11-26");
  await page.getByLabel("Calendário até", { exact: true }).fill("2026-11-27");
  await page.getByRole("button", { name: "Consultar sessões" }).click();
  await expect.poll(() => requests.some(url => url.pathname.endsWith("/calendar") && url.searchParams.get("from") === "2026-11-26" && url.searchParams.get("to") === "2026-11-27")).toBe(true);
  const ledger = page.getByTestId("corporate-actions");
  await expect(ledger).toContainText("v2");
  await expect(ledger).toContainText("Cancelado · não aplicado ao ajuste");
  await expect(ledger).toContainText("Disponível ao sistema:");
  await expect(ledger).toContainText("Ingerido:");
  const cutoff = requests.find(url => url.pathname.endsWith("/bars"))?.searchParams.get("as_of");
  expect(requests.find(url => url.pathname.endsWith("/identifiers"))?.searchParams.get("known_at")).toBe(cutoff);
  expect(requests.find(url => url.pathname.endsWith("/corporate-actions"))?.searchParams.get("as_of")).toBe(cutoff);
  await expect(ledger.locator('a[href="https://example.invalid/actions/split"]')).toHaveCount(1);
  await expect(page.locator('a[href="https://example.invalid/identifiers/1"]')).toHaveCount(1);
  await expect(page.locator('a[href="https://example.invalid/catalog"]')).toHaveCount(1);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: "test-results/catalog-details.png", fullPage: true });
});

test("mock: moeda de origem, UUIDs e tickers duplicados em tela estreita", async ({ page }) => {
  const euroAsset: Asset = { ...baseAsset, symbol: "DUP", currency: "EUR", venue: "XPAR", display_name: "Instrumento europeu", latest_price: 123.45 };
  const other: Asset = { ...baseAsset, id: otherId, symbol: "DUP", currency: "USD", venue: "XNYS", display_name: "Instrumento americano" };
  const requests: URL[] = [];
  await mockCatalog(page, { asset: euroAsset, assets: [euroAsset, other], onRequest: url => requests.push(url) });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/markets");
  await expect(page.locator("tbody tr")).toHaveCount(2);
  await expect(page.locator("tbody tr").first()).toContainText("€");
  await expect(page.locator("tbody tr").first()).toContainText("XPAR · EUR");
  await expect(page.locator('a[href="/markets/' + assetId + '"]')).toHaveCount(1);
  await expect(page.locator('a[href="/markets/' + otherId + '"]')).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByLabel("Filtrar por venue").fill("XPAR");
  await page.getByLabel("Filtrar por moeda").fill("eur");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect.poll(() => requests.some(url => url.searchParams.get("venue") === "XPAR" && url.searchParams.get("currency") === "EUR")).toBe(true);
  await page.goto("/watchlists");
  const select = page.getByRole("combobox", { name: "Adicionar ativo a Catálogo" });
  await expect(select.locator('option[value="' + assetId + '"]')).toContainText("DUP · XPAR");
  await expect(select.locator('option[value="' + otherId + '"]')).toContainText("DUP · XNYS");
  await page.goto("/markets/" + assetId);
  await expect(chart(page)).toBeVisible();
  await expect(page.locator(".chart-top")).toContainText("€");
  await catalogue(page).click();
  await expect(page.getByTestId("catalog-metadata")).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: "test-results/catalog-mobile.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("mock: mudar a fonte conserva o contrato comum sem preencher falhas", async ({ page }) => {
  const requests: URL[] = [];
  await mockCatalog(page, { asset: { ...baseAsset, asset_type: "crypto", timezone: "UTC", calendar_id: "24/7" }, onRequest: url => { if (/\/(bars|returns|metrics)$/.test(url.pathname)) requests.push(url); } });
  await page.goto("/markets/" + assetId);
  await expect(chart(page)).toBeVisible();
  await page.getByRole("combobox", { name: "Fonte da série" }).selectOption("coinbase");
  await expect(page.getByText("ADJUSTMENT_UNAVAILABLE", { exact: true })).toBeVisible();
  await expect(chart(page)).toHaveCount(0);
  const selected = requests.filter(url => url.searchParams.get("source") === "coinbase");
  expect(selected).toHaveLength(3);
  expect(new Set(selected.map(url => url.searchParams.get("as_of"))).size).toBe(1);
  expect(selected.every(url => url.searchParams.get("adjustment") === "unadjusted" && url.searchParams.get("corporate_action_source") === "coinbase")).toBe(true);
});

test("DEMO real: desdobramento, dividendo, calendário e ledger coerentes", async ({ page, request }) => {
  test.skip(process.env.E2E_AUTH_MODE === "oidc", "Fixture sintética validada no ambiente de autenticação demo.");
  const catalogueResponse = await request.get("/api/v1/assets?q=SPLIT-DEMO");
  expect(catalogueResponse.ok()).toBe(true);
  const assets = (await catalogueResponse.json()).items as Asset[];
  expect(assets).toHaveLength(1);
  const asset = assets[0];
  const query = "source=demo&as_of=2026-10-09T12%3A00%3A00Z&corporate_action_source=demo&from=2026-01-30T00%3A00%3A00Z&to=2026-02-04T00%3A00%3A00Z";
  const rawResponse = await request.get("/api/v1/assets/" + asset.id + "/bars?" + query + "&adjustment=unadjusted");
  const adjustedResponse = await request.get("/api/v1/assets/" + asset.id + "/bars?" + query + "&adjustment=split_dividend_adjusted");
  expect(rawResponse.ok()).toBe(true);
  expect(adjustedResponse.ok()).toBe(true);
  const raw = await rawResponse.json();
  const adjusted = await adjustedResponse.json();
  expect(raw.items.map((bar: Bar) => bar.close)).toEqual([100, 50, 49]);
  expect(adjusted.items.map((bar: Bar) => bar.close)).toEqual([49, 49, 49]);
  expect(adjusted.items.map((bar: Bar) => bar.volume)).toEqual([2000, 2000, 2000]);
  expect(adjusted.data_mode).toBe("DEMO");
  await page.goto("/markets/" + asset.id);
  await expect(chart(page)).toHaveAccessibleName(/Modo DEMO/);
  await expect(chart(page).locator("title").first()).toContainText("100,00");
  await page.getByRole("combobox", { name: "Ajuste da série" }).selectOption("split_dividend_adjusted");
  await expect(chart(page)).toHaveAccessibleName(/Ajustada por desdobramentos e dividendos/);
  await expect(chart(page).locator("title").first()).toContainText("49,00");
  await expect(page.getByText(/Dividendos em dinheiro não são reinvestidos/)).toBeVisible();
  await catalogue(page).click();
  await expect(page.getByTestId("catalog-metadata")).toContainText(asset.id);
  await expect(page.getByTestId("corporate-actions")).toContainText("Desdobramento");
  await expect(page.getByTestId("corporate-actions")).toContainText("Dividendo");
  await expect(page.getByRole("heading", { name: "Calendário de negociação" })).toBeVisible();
});