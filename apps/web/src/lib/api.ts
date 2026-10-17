"use client";
import { useCallback, useEffect, useState } from "react";
import type { Session } from "@capital-intelligence/shared-types";

export const SESSION_INVALIDATED_EVENT = "capital-session-invalidated";
// Only the identity is retained between requests. CSRF values are read afresh for
// each mutation and provider tokens never enter the browser application.
let activeIdentity: string | null = null;
let sessionRevision = 0;
const identityOf = (session: Session) => JSON.stringify([session.auth_mode, session.tenant_id, session.user.id]);

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) { super(message); this.name = "ApiError"; }
}
export function clearSession() {
  activeIdentity = null;
  sessionRevision += 1;
  if (typeof window !== "undefined") window.dispatchEvent(new Event(SESSION_INVALIDATED_EVENT));
}
function requireLogin() {
  clearSession();
  if (typeof window !== "undefined" && window.location.pathname !== "/login") window.location.replace("/login");
}
async function requestJSON<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  const response = await fetch("/api/v1" + path, { ...init, cache: "no-store", credentials: "same-origin", redirect: "error", headers });
  const json = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401) requireLogin();
    const detail = json?.detail;
    const fallback = response.status === 403 ? "Você não tem permissão para realizar esta ação." : "Não foi possível carregar os dados.";
    throw new ApiError(typeof detail === "object" ? detail?.code ?? "API_ERROR" : json?.code ?? "API_ERROR", typeof detail === "string" ? detail : detail?.message ?? json?.message ?? fallback, response.status);
  }
  return json as T;
}
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.delete("X-CSRF-Token");
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const expectedIdentity = activeIdentity;
    const expectedRevision = sessionRevision;
    const session = await requestJSON<Session>("/auth/session", { signal: init.signal });
    if (expectedRevision !== sessionRevision || (expectedIdentity !== null && expectedIdentity !== identityOf(session))) {
      requireLogin();
      throw new ApiError("SESSION_CHANGED", "A sessão mudou. Entre novamente antes de salvar alterações.", 401);
    }
    if (path !== "/auth/logout" && session.role !== "owner") {
      throw new ApiError("FORBIDDEN", "Seu perfil permite apenas leitura neste workspace.", 403);
    }
    if (session.mode === "AUTHENTICATED") {
      if (!session.csrf_token) {
        requireLogin();
        throw new ApiError("SESSION_INVALID", "Entre novamente para continuar.", 401);
      }
      headers.set("X-CSRF-Token", session.csrf_token);
    }
  }
  const result = await requestJSON<T>(path, { ...init, method, headers });
  if (path === "/auth/session" && method === "GET") activeIdentity = identityOf(result as Session);
  if (path === "/auth/logout" && method === "POST") clearSession();
  return result;
}
export function useResource<T>(path: string | null) {
  const [state, setState] = useState<{data: T | null; loading: boolean; error: ApiError | null}>({ data: null, loading: !!path, error: null });
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    let active = true;
    const invalidate = () => {
      active = false;
      controller.abort();
      setState({ data: null, loading: false, error: new ApiError("SESSION_REQUIRED", "Entre para acessar seu workspace.", 401) });
    };
    window.addEventListener(SESSION_INVALIDATED_EVENT, invalidate);
    Promise.resolve().then(() => { if (active) setState({ data: null, loading: true, error: null }); });
    api<T>(path, { signal: controller.signal }).then((data) => {
      if (active) setState({ data, loading: false, error: null });
    }).catch((error) => {
      if (active && error.name !== "AbortError") setState({ data: null, loading: false, error: error instanceof ApiError ? error : new ApiError("NETWORK_ERROR", "Não foi possível conectar à API.", 0) });
    });
    return () => { active = false; controller.abort(); window.removeEventListener(SESSION_INVALIDATED_EVENT, invalidate); };
  }, [path, revision]);
  return { ...state, refresh };
}
