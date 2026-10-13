import { Suspense } from "react";
import { Sources } from "@/components/screens";
export default function Page(){return <Suspense fallback={<p>Carregando…</p>}><Sources/></Suspense>;}
