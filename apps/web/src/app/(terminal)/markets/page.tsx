import { Suspense } from "react";
import { Markets } from "@/components/screens";
export default function Page(){return <Suspense fallback={<p>Carregando…</p>}><Markets/></Suspense>;}
