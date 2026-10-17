import { test, expect } from "@playwright/test";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { NextRequest } from "next/server";
import { GET, POST, HEAD } from "../src/app/api/v1/[...path]/route";

async function withUpstream(handler: (req: IncomingMessage, res: ServerResponse) => void, check: () => Promise<void>) {
  const upstream = createServer(handler);
  await new Promise<void>(resolve => upstream.listen(0, "127.0.0.1", resolve));
  const address = upstream.address();
  if (!address || typeof address === "string") throw new Error("Test upstream unavailable");
  const oldAPI = process.env.API_URL;
  const oldOrigins = process.env.PUBLIC_APP_ORIGINS;
  process.env.API_URL = `http://127.0.0.1:${address.port}`;
  process.env.PUBLIC_APP_ORIGINS = "http://localhost:3000";
  try { await check(); }
  finally {
    if (oldAPI === undefined) delete process.env.API_URL; else process.env.API_URL = oldAPI;
    if (oldOrigins === undefined) delete process.env.PUBLIC_APP_ORIGINS; else process.env.PUBLIC_APP_ORIGINS = oldOrigins;
    upstream.closeAllConnections();
    await new Promise<void>((resolve, reject) => upstream.close(error => error ? reject(error) : resolve()));
  }
}
function proxy(path: string, method = "GET", headers: Record<string, string> = {}, body?: string) {
  const req = new NextRequest("http://localhost:3000/api/v1/" + path, { method, headers: { host: "localhost:3000", ...headers }, body });
  const forward = method === "POST" ? POST : method === "HEAD" ? HEAD : GET;
  return forward(req, { params: Promise.resolve({ path: path.split("?")[0].split("/") }) });
}
const writeHeaders = { origin: "http://localhost:3000", "content-type": "application/json" };

test("proxy preserves individual auth cookies and sends a provider redirect without following it", async () => {
  let hits = 0;
  await withUpstream((_req, res) => {
    hits += 1;
    res.writeHead(302, {
      location: "https://identity.example/authorize?state=synthetic",
      "set-cookie": [
        "ci_oidc_flow=flow-value; Path=/api/v1/auth; HttpOnly; SameSite=Lax; Secure",
        "ci_session=session-value; Path=/api/v1; HttpOnly; SameSite=Lax; Secure; Expires=Thu, 15 Oct 2026 12:00:00 GMT",
        "provider_access_token=must-not-pass; Path=/",
      ],
    }); res.end();
  }, async () => {
    const result = await proxy("auth/login");
    expect(result.status).toBe(302);
    expect(result.headers.get("location")).toBe("https://identity.example/authorize?state=synthetic");
    expect(result.headers.get("cache-control")).toBe("no-store");
    expect(result.headers.get("referrer-policy")).toBe("no-referrer");
    expect(result.headers.getSetCookie()).toEqual([
      "ci_oidc_flow=flow-value; Path=/api/v1/auth; HttpOnly; SameSite=Lax; Secure",
      "ci_session=session-value; Path=/api/v1; HttpOnly; SameSite=Lax; Secure; Expires=Thu, 15 Oct 2026 12:00:00 GMT",
    ]);
    expect(hits).toBe(1);
  });
});

test("proxy accepts only fixed callback destinations and safe provider URLs", async () => {
  let location = "/dashboard";
  await withUpstream((_req, res) => { res.writeHead(302, { location }); res.end(); }, async () => {
    for (const target of ["/dashboard", "/login?auth_error=access_denied", "/login?auth_error=OIDC_INVALID_STATE"]) {
      location = target;
      const result = await proxy("auth/callback?code=synthetic&state=synthetic");
      expect(result.status).toBe(302); expect(result.headers.get("location")).toBe(target);
    }
    for (const target of ["https://attacker.example", "//attacker.example", "/dashboard?next=evil", "/login?auth_error=bad&next=https://attacker.example", "/login?auth_error=%2f%2fexample.com", "/login?auth_error=bad#fragment", "/dashboard/../other"]) {
      location = target;
      const result = await proxy("auth/callback");
      expect(result.status).toBe(502); expect(result.headers.has("location")).toBe(false);
    }
    for (const target of ["javascript:alert(1)", "https://user:password@identity.example/authorize", "https://@identity.example/authorize", "https://identity.example/authorize#", "https://identity.example/authorize#fragment", "//identity.example/authorize", "/authorize"]) {
      location = target;
      expect((await proxy("auth/login")).status).toBe(502);
    }
    location = "http://localhost:18080/realms/capital/protocol/openid-connect/auth";
    expect((await proxy("auth/login")).status).toBe(302);
  });
});

test("proxy blocks redirects outside GET login and callback", async () => {
  await withUpstream((_req, res) => { res.writeHead(307, { location: "https://identity.example/authorize" }); res.end(); }, async () => {
    for (const path of ["watchlists", "assets", "auth/session", "auth/login/extra"]) expect((await proxy(path)).status).toBe(502);
    expect((await proxy("auth/login", "POST", writeHeaders, "{}")).status).toBe(502);
    expect((await proxy("auth/login", "HEAD")).status).toBe(502);
  });
});

test("proxy forwards origin and CSRF, filters cookies, strips bearer authorization and preserves cookie deletion", async () => {
  let received: IncomingMessage["headers"] = {};
  await withUpstream((req, res) => {
    received = req.headers;
    res.writeHead(200, { "content-type": "application/json", "set-cookie": [
      "ci_session=; Path=/api/v1; HttpOnly; SameSite=Lax; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT",
      "ci_oidc_flow=; Path=/api/v1/auth; HttpOnly; SameSite=Lax; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT",
    ] }); res.end('{"logged_out":true}');
  }, async () => {
    const result = await proxy("auth/logout", "POST", { ...writeHeaders, authorization: "Bearer must-not-pass", "x-csrf-token": "fresh-csrf", cookie: "unrelated=private; ci_session=opaque; provider_token=secret; ci_oidc_flow=flow" }, "{}");
    expect(result.status).toBe(200);
    expect(received.authorization).toBeUndefined();
    expect(received.cookie).toBe("ci_session=opaque; ci_oidc_flow=flow");
    expect(received.origin).toBe("http://localhost:3000");
    expect(received["x-csrf-token"]).toBe("fresh-csrf");
    expect(received["content-type"]).toBe("application/json");
    expect(result.headers.getSetCookie()).toHaveLength(2);
    for (const cookie of result.headers.getSetCookie()) expect(cookie).toContain("Expires=Thu, 01 Jan 1970 00:00:00 GMT");
  });
});

test("proxy rejects foreign or mismatched origins, non-JSON and oversized writes before upstream", async () => {
  let hits = 0;
  await withUpstream((_req, res) => { hits += 1; res.end("{}"); }, async () => {
    for (const headers of [
      { ...writeHeaders, origin: "https://attacker.example" },
      { ...writeHeaders, host: "attacker.example" },
      { "content-type": "application/json" },
      { ...writeHeaders, origin: "null" },
    ]) expect((await proxy("watchlists", "POST", headers, "{}")).status).toBe(403);
    expect((await proxy("watchlists", "POST", { ...writeHeaders, "content-type": "text/plain" }, "{}")).status).toBe(415);
    expect((await proxy("watchlists", "POST", writeHeaders, "é".repeat(32769))).status).toBe(413);
    expect(hits).toBe(0);
  });
});

test("proxy preserves fixed login failure and demo destinations without broadening local redirects", async () => {
  let location = "/login?auth_error=login_failed";
  await withUpstream((_req, res) => { res.writeHead(302, { location }); res.end(); }, async () => {
    for (const target of ["/login?auth_error=login_failed", "/dashboard"]) {
      location = target;
      const result = await proxy("auth/login");
      expect(result.status).toBe(302);
      expect(result.headers.get("location")).toBe(target);
    }
    for (const target of ["/login", "/login?auth_error=other", "/login?auth_error=login_failed&next=//attacker.example", "/dashboard?next=//attacker.example"]) {
      location = target;
      expect((await proxy("auth/login")).status).toBe(502);
    }
  });
});
