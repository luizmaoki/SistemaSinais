import { Suspense } from "react";
import { Watchlists } from "@/components/screens";
export default function Page(){return <Suspense fallback={<p>Carregando…</p>}><Watchlists/></Suspense>;}
