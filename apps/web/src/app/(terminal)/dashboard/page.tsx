import { Suspense } from "react";
import { Dashboard } from "@/components/screens";
export default function Page(){return <Suspense fallback={<p>Carregando…</p>}><Dashboard/></Suspense>;}
