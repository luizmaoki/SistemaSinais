import { Suspense } from "react";
import { Filings } from "@/components/screens";
export default function Page(){return <Suspense fallback={<p>Carregando…</p>}><Filings news/></Suspense>;}
