import { NextRequest, NextResponse } from "next/server";

const allowedRoots = new Set(["health", "ready", "auth", "assets", "providers", "coverage", "scanner", "macro", "news", "institutional", "watchlists", "alert-rules", "alerts", "signals", "crypto", "derivatives", "liquidity"]);
async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (!path.length || !allowedRoots.has(path[0]) || path.some((segment) => segment === "." || segment === ".." || !/^[a-zA-Z0-9_.-]+$/.test(segment))) {
    return NextResponse.json({ detail: { code: "INVALID_PATH", message: "Rota inválida." } }, { status: 400 });
  }
  if (!["GET", "HEAD"].includes(request.method)) {
    const origin = request.headers.get("origin");
    const permittedOrigins = (process.env.PUBLIC_APP_ORIGINS ?? "http://localhost:3000,http://127.0.0.1:3000,http://web:3000").split(",").map((value) => value.trim());
    const sameHost = origin && permittedOrigins.includes(origin) && new URL(origin).host === request.headers.get("host");
    if (!sameHost) {
      return NextResponse.json({ detail: { code: "INVALID_ORIGIN", message: "Origem inválida." } }, { status: 403 });
    }
    if (!request.headers.get("content-type")?.startsWith("application/json")) {
      return NextResponse.json({ detail: { code: "INVALID_CONTENT_TYPE", message: "Envie JSON." } }, { status: 415 });
    }
  }
  const apiUrl = process.env.API_URL ?? "http://127.0.0.1:8000";
  const url = new URL("/api/v1/" + path.map(encodeURIComponent).join("/") + request.nextUrl.search, apiUrl);
  const headers = new Headers({ accept: "application/json" });
  for (const key of ["content-type", "authorization", "cookie"]) {
    const value = request.headers.get(key);
    if (value) headers.set(key, value);
  }
  try {
    const body = ["GET", "HEAD"].includes(request.method) ? undefined : await request.text();
    if (body && body.length > 65536) return NextResponse.json({ detail: { code: "PAYLOAD_TOO_LARGE", message: "Requisição muito grande." } }, { status: 413 });
    const upstream = await fetch(url, { method: request.method, headers, body, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(15000) });
    const responseHeaders = new Headers({ "Content-Type": "application/json", "Cache-Control": "no-store" });
    const cookie = upstream.headers.get("set-cookie");
    if (cookie) responseHeaders.set("set-cookie", cookie);
    return new NextResponse(await upstream.text(), { status: upstream.status, headers: responseHeaders });
  } catch {
    return NextResponse.json({ detail: { code: "API_UNAVAILABLE", message: "API indisponível. Verifique se o serviço está em execução." } }, { status: 503 });
  }
}
export const GET = forward;
export const POST = forward;
export const PATCH = forward;
export const DELETE = forward;



