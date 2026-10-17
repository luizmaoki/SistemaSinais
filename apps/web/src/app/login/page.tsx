"use client";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, Check, Globe2, Layers3, ShieldCheck } from "lucide-react";
import type { AuthConfig, Session } from "@capital-intelligence/shared-types";
import { api, useResource } from "@/lib/api";
import { Brand } from "@/components/terminal";
import { ErrorState, Loading } from "@/components/ui";

function Login() {
  const router = useRouter();
  const params = useSearchParams();
  const config = useResource<AuthConfig>("/auth/config");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const authError = params.get("auth_error");
  const demo = config.data?.auth_mode === "demo" && config.data.demo_available;
  const oidc = config.data?.auth_mode === "oidc" && config.data.configured;
  async function enter() {
    setLoading(true); setError("");
    try {
      if (oidc) { window.location.assign("/api/v1/auth/login"); return; }
      if (!demo) throw new Error("O acesso não está configurado neste ambiente.");
      const session = await api<Session>("/auth/session");
      if (session.mode !== "DEMO") throw new Error("O acesso demo está desabilitado neste ambiente.");
      router.push("/dashboard");
    } catch (error) {
      setError(error instanceof Error ? error.message : "Não foi possível conectar à API.");
      setLoading(false);
    }
  }
  return <main className="login-page">
    <div className="login-grid" aria-hidden="true"/>
    <header className="login-header"><Brand/><span className="eyebrow">SEU TERMINAL DE INTELIGÊNCIA</span></header>
    <div className="login-content">
      <div className="login-editorial"><div className="login-kicker"><span className="status-dot"/> MERCADOS CONECTADOS. DECISÕES INFORMADAS.</div><h1>O mercado, com<br/><em>mais contexto.</em></h1><p>Preço, macroeconomia e informações institucionais em um único lugar. Com evidências que você pode verificar.</p><div className="login-features"><span><Globe2 size={17}/>Perspectiva multmercado</span><span><Layers3 size={17}/>Fontes e dados rastreáveis</span><span><ShieldCheck size={17}/>Transparência sobre incertezas</span></div></div>
      <section className="login-card"><span className="eyebrow">BEM-VINDO AO WORKSPACE</span><h2>{oidc ? "Entre no seu workspace" : "Explore o terminal"}</h2><p>Seu acesso e a origem dos dados são identificados separadamente.</p>
        {config.loading && <Loading label="Verificando acesso"/>}
        {config.error && <ErrorState error={config.error} retry={config.refresh}/>}
        {config.data && <>
          <div className="demo-explanation"><span className={"badge " + (oidc ? "identity-authenticated" : "mode-demo")}>{oidc ? "ACESSO AUTENTICADO" : demo ? "DEMO LOCAL" : "ACESSO NÃO CONFIGURADO"}</span><h3>{oidc ? "Identidade protegida pelo Keycloak" : "Uma visão completa da experiência"}</h3><p>{oidc ? "Entre com sua conta para acessar watchlists e regras do seu workspace. Séries simuladas continuam identificadas como DEMO." : "Explore séries simuladas, crie watchlists e configure regras de alerta. As integrações reais aparecem com sua própria fonte e classificação."}</p><span><Check size={15}/> Nenhuma credencial financeira necessária</span></div>
          <button className="button primary login-enter" onClick={enter} disabled={loading || (!demo && !oidc)}>{loading ? "Conectando…" : oidc ? "Entrar com Keycloak" : demo ? "Entrar no ambiente demo" : "Acesso indisponível"}<ArrowRight size={18}/></button>
          <p className="login-note">{oidc ? "O login ocorre no provedor de identidade. Ao sair, a sessão deste aplicativo é encerrada; a sessão do Keycloak pode continuar ativa." : demo ? "Acesso demonstrativo disponível somente no ambiente local de desenvolvimento." : "Configure o provedor de identidade no backend para habilitar o acesso."}</p>
        </>}
        {(error || authError) && <p className="form-error" role="alert">{error || (authError === "access_denied" ? "O login foi cancelado. Você pode tentar novamente." : "Não foi possível concluir o login. Inicie uma nova tentativa.")}</p>}
      </section>
    </div>
    <footer className="login-footer"><span>© 2026 Capital Intelligence</span><span>Inteligência financeira com proveniência.</span></footer>
  </main>;
}
export default function LoginPage() { return <Suspense fallback={<Loading label="Carregando acesso"/>}><Login/></Suspense>; }
