"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Activity, Bell, ChartNoAxesCombined, ChevronRight, CircleHelp, Globe2, LayoutDashboard, LogOut, Menu, Newspaper, PanelLeftClose, RadioTower, Search, Settings2, SlidersHorizontal, Star, Landmark, X } from "lucide-react";
import type { Session } from "@capital-intelligence/shared-types";
import { api, useResource } from "@/lib/api";
import { SessionContext } from "@/lib/session";
import { messages } from "@/lib/messages";
import { ErrorState, Loading } from "./ui";
const navigation = [
  {label:"MERCADOS",links:[{id:"dashboard",icon:LayoutDashboard},{id:"markets",icon:ChartNoAxesCombined},{id:"scanner",icon:SlidersHorizontal}]},
  {label:"INTELIGÊNCIA",links:[{id:"macro",icon:Globe2},{id:"news",icon:Newspaper},{id:"institutional",icon:Landmark}]},
  {label:"WORKSPACE",links:[{id:"watchlists",icon:Star},{id:"alerts",icon:Bell}]},
  {label:"SISTEMA",links:[{id:"sources",icon:RadioTower},{id:"settings",icon:Settings2}]},
] as const;
export function Brand({compact=false}: {compact?:boolean}) { return <span className="brand"><span className="brand-mark"><span/><span/><span/></span>{!compact && <span>capital<span className="brand-sub">INTELLIGENCE</span></span>}</span>; }
export function TerminalShell({children}: {children:React.ReactNode}) {
  const pathname = usePathname();
  const router = useRouter();
  const [mobileOpen,setMobileOpen] = useState(false);
  const [query,setQuery] = useState("");
  const [loggingOut,setLoggingOut] = useState(false);
  const [logoutError,setLogoutError] = useState("");
  const session = useResource<Session>("/auth/session");
  const current = pathname.split("/")[1] as keyof typeof messages["pt-BR"];
  function search(event:FormEvent) { event.preventDefault(); router.push("/markets?q=" + encodeURIComponent(query.trim())); }
  async function logout() {
    setLoggingOut(true); setLogoutError("");
    try { await api("/auth/logout", {method:"POST", body:"{}"}); window.location.replace("/login"); }
    catch (error) { setLogoutError(error instanceof Error ? error.message : "Não foi possível encerrar a sessão. Tente novamente."); setLoggingOut(false); }
  }
  return <SessionContext.Provider value={session.data}><div className="terminal">
    <a className="skip-link" href="#main-content">Pular para o conteúdo</a>
    {mobileOpen && <button className="sidebar-backdrop" aria-label="Fechar navegação" onClick={()=>setMobileOpen(false)}/>}
    <aside className={"sidebar " + (mobileOpen?"is-open":"")} aria-label="Navegação principal">
      <Link href="/dashboard" className="brand-link" aria-label="Capital Intelligence, visão geral"><Brand/></Link>
      <button className="icon-button mobile-close" aria-label="Fechar menu" onClick={()=>setMobileOpen(false)}><X size={19}/></button>
      <div className="workspace-switch"><span className="workspace-icon">CI</span><span>Meu workspace<small>{session.data?.role === "viewer" ? "Somente leitura" : session.data?.mode === "AUTHENTICATED" ? "Workspace autenticado" : "Ambiente pessoal"}</small></span><ChevronRight size={14}/></div>
      <nav>{navigation.map(group=><div className="nav-group" key={group.label}><p className="nav-label">{group.label}</p>{group.links.map(({id,icon:Icon})=><Link key={id} href={"/"+id} onClick={()=>setMobileOpen(false)} className={"nav-link "+(current===id?"active":"")} aria-current={current===id?"page":undefined}><Icon size={17}/><span>{messages["pt-BR"][id]}</span>{id==="sources" && <span className="nav-tiny-dot"/>}</Link>)}</div>)}</nav>
      <div className="sidebar-bottom"><Link href="/sources" className="feed-card"><Activity size={16}/><span>Saúde dos conectores<small>Ver cobertura e disponibilidade</small></span><ChevronRight size={13}/></Link><div className="sidebar-footnote"><CircleHelp size={13}/><span>Dados com contexto.</span><PanelLeftClose size={14}/></div></div>
    </aside>
    <div className="terminal-body">
      <header className="topbar">
        <div className="topbar-start"><button className="icon-button mobile-menu" aria-label="Abrir menu" onClick={()=>setMobileOpen(true)}><Menu size={19}/></button><span className="breadcrumb">Workspace <ChevronRight size={12}/> <strong>{messages["pt-BR"][current] ?? "Ativo"}</strong></span></div>
        <form className="global-search" onSubmit={search}><Search size={16}/><input aria-label="Buscar ativos globalmente" placeholder="Buscar ativos, símbolos…" value={query} onChange={event=>setQuery(event.target.value)}/><button type="submit" aria-label="Executar busca">↵</button></form>
        <div className="topbar-actions"><span className="timezone">BRT <span>UTC−3</span></span>{session.data && <><span className={"badge identity-badge " + (session.data.mode === "AUTHENTICATED" ? "identity-authenticated" : "mode-demo")} data-testid="identity-badge">{session.data.mode === "AUTHENTICATED" ? "AUTENTICADO" : "DEMO LOCAL"}</span><Link className="session-user" href="/settings" aria-label={"Conta de " + session.data.user.name}>{session.data.user.name}<small>{session.data.role === "owner" ? "Proprietário" : "Somente leitura"}</small></Link><button className="icon-button" aria-label="Sair da conta" title="Encerrar a sessão deste aplicativo" disabled={loggingOut} onClick={()=>void logout()}><LogOut size={17}/></button></>}<Link className="icon-button" href="/alerts" aria-label="Abrir alertas"><Bell size={17}/></Link></div>
      </header>
      {session.data && <div className="global-banner"><span className="demo-dot"/><strong>{session.data.mode === "AUTHENTICATED" ? "WORKSPACE AUTENTICADO" : "WORKSPACE LOCAL"}</strong><span>Dados demonstrativos são identificados como DEMO. Consulte a fonte de cada informação.</span><Link href="/sources">Ver fontes <ChevronRight size={13}/></Link></div>}
      <main id="main-content" className="main-content" tabIndex={-1}>{logoutError && <p className="form-error" role="alert">{logoutError}</p>}{session.loading ? <Loading label="Verificando sessão"/> : session.error ? <ErrorState error={session.error} retry={session.refresh}/> : session.data ? children : null}</main>
      <footer className="terminal-footer"><span><span className="status-dot"/>Capital Intelligence <span className="footer-version">v0.1</span></span><span>Horários em America/Sao_Paulo · Valores na moeda de origem</span><span>Análise e apoio à decisão</span></footer>
    </div>
  </div></SessionContext.Provider>;
}
