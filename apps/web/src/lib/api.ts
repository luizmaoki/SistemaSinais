"use client";
import { useCallback, useEffect, useState } from "react";

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) { super(message); this.name = "ApiError"; }
}
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch("/api/v1" + path, { ...init, cache: "no-store", credentials: "same-origin", headers: { "Content-Type": "application/json", ...init.headers } });
  const json = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = json?.detail;
    throw new ApiError(typeof detail === "object" ? detail?.code ?? "API_ERROR" : json?.code ?? "API_ERROR", typeof detail === "string" ? detail : detail?.message ?? json?.message ?? "Não foi possível carregar os dados.", response.status);
  }
  return json as T;
}
export function useResource<T>(path: string | null) {
  const [state, setState] = useState<{data: T | null; loading: boolean; error: ApiError | null}>({ data: null, loading: !!path, error: null });
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    let active = true;
    Promise.resolve().then(() => { if (active) setState({ data: null, loading: true, error: null }); });
    api<T>(path, { signal: controller.signal }).then((data) => {
      if (active) setState({ data, loading: false, error: null });
    }).catch((error) => {
      if (active && error.name !== "AbortError") setState({ data: null, loading: false, error: error instanceof ApiError ? error : new ApiError("NETWORK_ERROR", "Não foi possível conectar à API.", 0) });
    });
    return () => { active = false; controller.abort(); };
  }, [path, revision]);
  return { ...state, refresh };
}

