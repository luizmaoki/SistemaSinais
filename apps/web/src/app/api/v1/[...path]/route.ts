import { NextRequest, NextResponse } from "next/server";

const allowedRoots = new Set(["health", "ready", "auth", "assets", "providers", "coverage", "scanner", "macro", "news", "institutional", "watchlists", "alert-rules", "alerts", "signals", "crypto", "derivatives", "liquidity"]);
const allowedCookies = new Set(["ci_session", "ci_oidc_flow"]);
const redirectStatuses = new Set([301, 302, 303, 307, 308]);
function failure(code: string, message: string, status: number) {
  return NextResponse.json({ detail: { code, message } }, { status, headers: { "Cache-Control": "no-store" } });
}
function permittedOrigin(request: NextRequest) {
  const origin = request.headers.get("origin");
  const origins = (process.env.PUBLIC_APP_ORIGINS ?? "http://localhost:3000,http://127.0.0.1:3000,http://web:3000").split(",").map(value => value.trim());
  if (!origin || !origins.includes(origin)) return false;
  try { return new URL(origin).host === request.headers.get("host"); } catch { return false; }
}
function permittedRedirect(path: string[], location: string) {
  if (path.length !== 2 || path[0] !== "auth") return false;
  if (path[1] === "callback") return location === "/dashboard" || /^\/login\?auth_error=[a-zA-Z0-9_-]{1,80}$/.test(location);
  if (path[1] !== "login") return false;
  if (location === "/dashboard" || location === "/login?auth_error=login_failed") return true;
  try {
    // The API validates the configured provider endpoint. The proxy only allows
    // an absolute HTTP(S) navigation here, never a fetch of the provider URL.
    const target = new URL(location);
    const authority = /^https?:\/\/([^/?#]+)/i.exec(location)?.[1];
    return !!authority && !authority.includes("@") && !/[\u0000-\u0020\u007f\\#]/.test(location) && ["https:", "http:"].includes(target.protocol) && !target.username && !target.password;
  } catch { return false; }
}
async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (!path.length || !allowedRoots.has(path[0]) || path.some(segment => segment === "." || segment === ".." || !/^[a-zA-Z0-9_.-]+$/.test(segment))) {
    return failure("INVALID_PATH", "Rota inválida.", 400);
  }
  if (!["GET", "HEAD"].includes(request.method)) {
    if (!permittedOrigin(request)) return failure("INVALID_ORIGIN", "Origem inválida.", 403);
    if (request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") return failure("INVALID_CONTENT_TYPE", "Envie JSON.", 415);
  }
  const apiUrl = process.env.API_URL ?? "http://127.0.0.1:8000";
  const url = new URL("/api/v1/" + path.map(encodeURIComponent).join("/") + request.nextUrl.search, apiUrl);
  const headers = new Headers({ accept: "application/json" });
  for (const key of ["content-type", "origin", "x-csrf-token"]) {
    const value = request.headers.get(key);
    if (value) headers.set(key, value);
  }
  const cookies = (request.headers.get("cookie") ?? "").split(";").map(value => value.trim()).filter(value => allowedCookies.has(value.split("=", 1)[0]));
  if (cookies.length) headers.set("cookie", cookies.join("; "));
  try {
    const body = ["GET", "HEAD"].includes(request.method) ? undefined : await request.text();
    if (body && Buffer.byteLength(body, "utf8") > 65536) return failure("PAYLOAD_TOO_LARGE", "Requisição muito grande.", 413);
    const upstream = await fetch(url, { method: request.method, headers, body, cache: "no-store", redirect: "manual", signal: AbortSignal.timeout(15000) });
    const responseHeaders = new Headers({ "Content-Type": upstream.headers.get("content-type") ?? "application/json", "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" });
    if (upstream.status >= 300 && upstream.status < 400) {
      const location = upstream.headers.get("location");
      if (request.method !== "GET" || !redirectStatuses.has(upstream.status) || !location || !permittedRedirect(path, location)) {
        await upstream.body?.cancel();
        return failure("INVALID_UPSTREAM_REDIRECT", "Redirecionamento da API rejeitado.", 502);
      }
      responseHeaders.set("location", location);
    }
    // getSetCookie preserves individual headers, including Expires commas and
    // the API's HttpOnly, Path, SameSite and Secure attributes.
    for (const cookie of upstream.headers.getSetCookie()) {
      if (allowedCookies.has(cookie.slice(0, cookie.indexOf("=")).trim())) responseHeaders.append("set-cookie", cookie);
    }
    return new NextResponse(request.method === "HEAD" ? null : upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return failure("API_UNAVAILABLE", "API indisponível. Verifique se o serviço está em execução.", 503);
  }
}
export const GET = forward;
export const HEAD = forward;
export const POST = forward;
export const PATCH = forward;
export const DELETE = forward;
