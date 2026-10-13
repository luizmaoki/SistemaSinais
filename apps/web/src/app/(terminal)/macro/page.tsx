import { Suspense } from "react";
import { Macro } from "@/components/screens";
export default function Page(){return <Suspense fallback={<p>Carregando…</p>}><Macro/></Suspense>;}
