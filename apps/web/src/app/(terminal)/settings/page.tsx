import { Suspense } from "react";
import { Settings } from "@/components/screens";
export default function Page(){return <Suspense fallback={<p>Carregando…</p>}><Settings/></Suspense>;}
