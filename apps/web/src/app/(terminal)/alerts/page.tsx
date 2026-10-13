import { Suspense } from "react";
import { Alerts } from "@/components/screens";
export default function Page(){return <Suspense fallback={<p>Carregando…</p>}><Alerts/></Suspense>;}
