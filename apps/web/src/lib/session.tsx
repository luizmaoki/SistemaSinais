"use client";
import { createContext, useContext } from "react";
import type { Session } from "@capital-intelligence/shared-types";

export const SessionContext = createContext<Session | null>(null);
export function useSession() { return useContext(SessionContext); }
