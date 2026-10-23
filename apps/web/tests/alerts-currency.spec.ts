import { test, expect } from "@playwright/test";
import type { Alert, Asset, Session } from "../../../packages/shared-types";

test("alertas preservam a moeda observada mesmo com catálogo atual em USD", async ({ page }) => {
  const session: Session = { mode: "AUTHENTICATED", auth_mode: "oidc", user: { id: "currency-viewer", name: "Leitor" }, tenant_id: "currency-tenant", role: "viewer", csrf_token: "unused-viewer-token" };
  const asset: Asset = { id: "11111111-1111-4111-8111-111111111111", symbol: "CATALOG-USD", display_name: "Catálogo atual em dólar", asset_type: "equity", currency: "USD", venue: "DEMO", latest_price: 999, data_mode: "DEMO", source_id: "demo" };
  const alerts: Alert[] = [
    { id: "alert-usd", asset_id: asset.id, message: "Observação histórica USD", observed_price: 123.45, observed_currency: "USD", threshold: 100, data_mode: "DEMO", source_id: "demo" },
    { id: "alert-eur", asset_id: asset.id, message: "Observação histórica EUR", observed_price: 123.45, observed_currency: "EUR", threshold: 100, data_mode: "DEMO", source_id: "demo" },
    { id: "alert-unknown", asset_id: asset.id, message: "Observação histórica sem moeda", observed_price: 123.45, observed_currency: null, threshold: 100, data_mode: "DEMO", source_id: "demo" },
  ];
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const body = path.endsWith("/auth/config") ? { auth_mode: "oidc", configured: true, demo_available: false, login_path: "/api/v1/auth/login" }
      : path.endsWith("/auth/session") ? session
      : path.endsWith("/assets") ? { items: [asset], total: 1, page: 1, page_size: 100 }
      : path.endsWith("/alerts") ? { items: alerts }
      : { items: [] };
    await route.fulfill({ json: body });
  });
  await page.goto("/alerts");
  // Confirm the current USD catalogue has loaded before checking historical denominations.
  await expect(page.getByRole("heading", { name: "CATALOG-USD", exact: true })).toHaveCount(3);
  const usd = page.locator(".event-item").filter({ hasText: "Observação histórica USD" });
  const eur = page.locator(".event-item").filter({ hasText: "Observação histórica EUR" });
  const unknown = page.locator(".event-item").filter({ hasText: "Observação histórica sem moeda" });
  await expect(usd).toContainText(/Preço observado: US\$\s123,45/);
  await expect(eur).toContainText(/Preço observado: €\s123,45/);
  await expect(eur).not.toContainText("US$");
  await expect(unknown).toContainText("Preço observado: 123,45 (moeda não informada)");
  await expect(unknown).not.toContainText(/US\$|€/);
});