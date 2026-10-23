"use client";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import type { Asset, AssetPage, Bars, Returns, SeriesAdjustment, SeriesMetrics, SeriesProvenance, Collection, Provider, MacroEvent, Filing, Watchlist, AlertRule, Alert } from "@capital-intelligence/shared-types";
import { ApiError, api, useResource } from "@/lib/api";
import { useSession } from "@/lib/session";
import { adjustmentLabel, assetClass, date, month, number, percent, price } from "@/lib/format";
import { AssetMark, EmptyState, ErrorState, ExternalLink, Loading, ModeBadge, Notice, PageHeading, Panel, SourceLine } from "./ui";

import { AssetCatalog } from "./asset-catalog";

function Failure({resource}: {resource: {loading: boolean; error: Error | null; refresh: ()=>void}}) { return resource.loading ? <Loading/> : resource.error ? <ErrorState error={resource.error} retry={resource.refresh}/> : null; }

export function AssetTable({assets}: {assets:Asset[]}) {
  return <div className="table-scroll"><table><thead><tr><th>Instrumento</th><th>Classe / venue / moeda</th><th>Último fechamento</th><th>Variação diária</th><th>Fonte / atualização</th></tr></thead><tbody>{assets.map(a=><tr key={a.id}><td><Link aria-label={a.symbol+" · "+a.venue+" · "+(assetClass[a.asset_type]??a.asset_type)+" · "+a.display_name} className="asset-name" href={"/markets/"+a.id}><AssetMark symbol={a.symbol}/><span><strong>{a.symbol}</strong><small>{a.display_name}</small></span></Link></td><td>{assetClass[a.asset_type] ?? a.asset_type}<small>{a.venue} · {a.currency ?? "Moeda não informada"}</small></td><td>{price(a.latest_price,a.currency)}</td><td className={(a.change_pct??0)>=0?"positive":"negative"}>{percent(a.change_pct)}</td><td><SourceLine source={a.source_id ?? "Sem feed de preços"} at={a.updated_at} mode={a.data_mode}/></td></tr>)}</tbody></table></div>;
}

export function Chart({bars,currency}: {bars:Bars;currency:string|null}) {
  if(!bars.items.length) return <EmptyState title="Série indisponível" description="Esta fonte não tem barras persistidas para o instrumento. Nenhum dado demonstrativo foi usado para preencher a lacuna."/>;
  const values=bars.items.slice(-120); const max=Math.max(...values.map(b=>b.high)),min=Math.min(...values.map(b=>b.low)); const spread=max-min || 1;
  const x=(i:number)=>50+i*850/Math.max(1,values.length-1); const y=(v:number)=>30+220*(max-v)/spread;
  const maxVol=Math.max(...values.map(b=>b.volume),1);
  const sma=values.map((_,i)=>i<19?null:values.slice(i-19,i+1).reduce((s,b)=>s+b.close,0)/20);
  return <div className="chart-wrap"><div className="chart-top"><span>{price(values.at(-1)?.close,currency)}</span><span className="muted">Candles diários · SMA 20 · volume</span><ModeBadge mode={bars.data_mode}/></div>
    <svg className="price-chart" viewBox="0 0 980 340" role="img" aria-label={"Gráfico de preços e volume. Fonte "+bars.source_id+". Modo "+bars.data_mode+". "+adjustmentLabel[bars.adjustment]}>
      {[0,1,2,3,4].map(i=><g key={i}><line x1="50" x2="900" y1={30+i*55} y2={30+i*55} stroke="var(--border)"/><text x="914" y={34+i*55} fill="var(--muted)" fontSize="11">{number(max-i*spread/4)}</text></g>)}
      {values.map((b,i)=><g key={b.time}><title>{date(b.close_time,false)}: {price(b.close,currency)} · volume {number(b.volume,0)}</title><line x1={x(i)} x2={x(i)} y1={y(b.high)} y2={y(b.low)} stroke={b.close>=b.open?"var(--positive)":"var(--negative)"}/><rect x={x(i)-2} y={Math.min(y(b.open),y(b.close))} width="4" height={Math.max(1,Math.abs(y(b.open)-y(b.close)))} fill={b.close>=b.open?"var(--positive)":"var(--negative)"}/><rect x={x(i)-2} y={310-40*b.volume/maxVol} width="4" height={40*b.volume/maxVol} fill="var(--teal)" opacity=".25"/></g>)}
      <polyline points={sma.flatMap((v,i)=>v==null?[]:[x(i)+","+y(v)]).join(" ")} fill="none" stroke="#e8c277" strokeWidth="1.7"/>
      <text x="50" y="332" fontSize="11" fill="var(--muted)">{date(values[0].time,false)}</text><text x="740" y="332" fontSize="11" fill="var(--muted)">{date(values.at(-1)?.time,false)}</text>
      {bars.data_mode==="DEMO" && <text x="480" y="160" textAnchor="middle" fill="var(--muted)" opacity=".25" fontSize="44" fontWeight="700">DEMO · SIMULADO</text>}
    </svg><SourceLine source={bars.source_id} at={values.at(-1)?.close_time} mode={bars.data_mode} scope={adjustmentLabel[bars.adjustment]}/></div>;
}

function AssetSeries({ asset, source, adjustment, asOf, onRaw }: { asset: Asset; source: string; adjustment: SeriesAdjustment; asOf: string; onRaw: () => void }) {
  const query = new URLSearchParams({ source, adjustment, as_of: asOf, corporate_action_source: source }).toString();
  const prefix = "/assets/" + asset.id;
  const bars = useResource<Bars>(prefix + "/bars?" + query);
  const returns = useResource<Returns>(prefix + "/returns?" + query);
  const metrics = useResource<SeriesMetrics>(prefix + "/metrics?" + query);
  const events = useResource<Collection<Filing>>(prefix + "/events");
  const loading = bars.loading || returns.loading || metrics.loading;
  const matches = (value: SeriesProvenance | null) => value != null && value.source_id === source && value.adjustment === adjustment && Date.parse(value.as_of ?? "") === Date.parse(asOf) && (adjustment === "unadjusted" || value.action_source_id === source);
  const complete = !!bars.data && !!returns.data && !!metrics.data;
  const mismatch = complete && (!matches(bars.data) || !matches(returns.data) || !matches(metrics.data));
  const error = bars.error ?? returns.error ?? metrics.error ?? (mismatch ? new ApiError("SERIES_PROVENANCE_MISMATCH", "A resposta não confirma a fonte, o ajuste e a disponibilidade selecionados. A série foi ocultada para evitar uma identificação incorreta.", 502) : null);
  const ready = !loading && !error && complete;
  function retry() { bars.refresh(); returns.refresh(); metrics.refresh(); }
  return <>
    <Panel title="Preço e volume" subtitle={adjustmentLabel[adjustment] + " · Fonte " + source}>
      {error ? <><ErrorState error={error} retry={retry} />{adjustment !== "unadjusted" && <div className="series-recovery"><button className="button" onClick={onRaw}>Voltar à série sem ajuste</button></div>}</> : loading ? <Loading /> : null}
      {ready && bars.data && <Chart bars={bars.data} currency={bars.data.currency} />}
      {ready && adjustment !== "unadjusted" && <Notice>Ajuste retroativo dos preços por fatores de eventos corporativos. Dividendos em dinheiro não são reinvestidos; esta série não representa retorno total. Fonte dos eventos: {bars.data?.action_source_id ?? "Não informada"}.</Notice>}
      {ready && bars.data?.adjustment_methodology && <details className="methodology"><summary>Metodologia do ajuste</summary><p>{bars.data.adjustment_methodology}</p></details>}
    </Panel>
    {ready && metrics.data?.calculation_status === "UNAVAILABLE" && <Notice kind="warning">Indicadores indisponíveis: a série não tem moeda ou calendário válidos, ou apresenta sessões e preços incompatíveis com o cálculo. {metrics.data.frequency_quality}</Notice>}
    <div className="metrics-grid">{([["SMA 20", "sma_20"], ["SMA 50", "sma_50"], ["RSI 14 simples", "rsi_14"], ["Drawdown máximo (%)", "max_drawdown_pct"]] as const).map(([label, key]) => <div className="metric-card" key={key}><span>{label}</span><strong>{number(ready && metrics.data?.calculation_status !== "UNAVAILABLE" ? metrics.data?.[key] : null)}</strong>{ready && metrics.data && <SourceLine source={metrics.data.source_id} at={metrics.data.as_of} mode={metrics.data.data_mode} scope={adjustmentLabel[metrics.data.adjustment]} />}</div>)}</div>
    <div className="two-columns">
      <Panel title="Retorno mês a mês" subtitle="Meses consecutivos; base anterior obrigatória">
        {ready && returns.data?.calculation_status === "UNAVAILABLE" ? <EmptyState title="Retornos indisponíveis" description="Calendário ou moeda da série não disponíveis para calcular retornos." /> : ready && returns.data ? <><SourceLine source={returns.data.source_id} at={returns.data.as_of} mode={returns.data.data_mode} scope={adjustmentLabel[returns.data.adjustment]} /><div className="table-scroll"><table><thead><tr><th>Mês</th><th>Retorno</th><th>Qualidade</th></tr></thead><tbody>{returns.data.items.map(item => <tr key={item.month}><td>{month(item.month)}</td><td className={(item.return_pct ?? 0) >= 0 ? "positive" : "negative"}>{percent(item.return_pct)}</td><td>{item.partial ? "Parcial" : "Fechado"}<small>{item.reason ?? "Sessões completas"}</small></td></tr>)}</tbody></table></div></> : <p className="muted">{loading && !error ? "Carregando a mesma série selecionada…" : "Retornos indisponíveis para a seleção atual."}</p>}
      </Panel>
      <Panel title="Eventos relacionados" subtitle="O que foi reportado; causalidade não presumida"><Failure resource={events} />{events.data?.items.length ? <FilingsList items={events.data.items} /> : !events.loading && !events.error && <EmptyState title="Nenhum filing ingerido" description="Configure SEC_USER_AGENT no backend e execute a sincronização." />}</Panel>
    </div>
  </>;
}
function AssetDetail({ assetId }: { assetId: string }) {
  const asset = useResource<Asset>("/assets/" + assetId);
  const [source, setSource] = useState("demo");
  const [adjustment, setAdjustment] = useState<SeriesAdjustment>("unadjusted");
  const [asOf, setAsOf] = useState(() => new Date().toISOString());
  const [draftAsOf, setDraftAsOf] = useState("");
  function applyAsOf(event: FormEvent) {
    event.preventDefault();
    const selected = draftAsOf ? new Date(draftAsOf + "Z") : new Date();
    if (Number.isFinite(selected.getTime())) setAsOf(selected.toISOString());
  }
  if (!asset.data) return <Failure resource={asset} />;
  const a = asset.data;
  return <>
    <PageHeading eyebrow="INSTRUMENTO / CONTEXTO" title={a.symbol + " · " + a.display_name} description={(assetClass[a.asset_type] ?? a.asset_type) + " · " + a.venue + " · " + (a.currency ?? "Moeda não informada")} actions={<Link className="button" href="/watchlists">Adicionar à watchlist</Link>} />
    <div className="toolbar series-controls">
      <label>Fonte da série <select value={source} onChange={event => setSource(event.target.value)}><option value="demo">DEMO — série simulada</option>{a.asset_type === "crypto" && <option value="coinbase">Coinbase — histórico real configurado</option>}</select></label>
      <label>Ajuste da série <select aria-label="Ajuste da série" value={adjustment} onChange={event => setAdjustment(event.target.value as SeriesAdjustment)}>{Object.entries(adjustmentLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <span className="muted">Preços na moeda de origem. Não há conversão fixa para BRL.</span>
    </div>
    <details className="as-of-options"><summary>Referência de disponibilidade</summary><form className="toolbar" onSubmit={applyAsOf}><label>Disponível até (UTC) <input aria-label="Disponível até (UTC)" type="datetime-local" value={draftAsOf} onChange={event => setDraftAsOf(event.target.value)} /></label><button className="button small">Aplicar referência</button><span className="muted">Campo vazio atualiza a consulta para agora.</span></form></details>
    <p className="catalog-caption series-selection">Seleção: {adjustmentLabel[adjustment]} · fonte {source} · disponível até {asOf.replace("T", " ").replace("Z", " UTC")}</p>
    <AssetCatalog asset={a} asOf={asOf} source={source} />
    <AssetSeries key={assetId + ":" + source + ":" + adjustment + ":" + asOf} asset={a} source={source} adjustment={adjustment} asOf={asOf} onRaw={() => setAdjustment("unadjusted")} />
  </>;
}
export function AssetView({ assetId }: { assetId: string }) { return <AssetDetail key={assetId} assetId={assetId} />; }

export function Dashboard() {
  const assets=useResource<AssetPage>("/assets?page_size=100"); const providers=useResource<Collection<Provider>>("/providers"); const watchlists=useResource<Collection<Watchlist>>("/watchlists");
  const dashboardAssets = [["NVDA","NASDAQ","equity"],["SPY","NYSE ARCA","etf"],["BTC-USD","Coinbase","crypto"],["ETH-USD","Coinbase","crypto"]];
  const findAsset = (symbol: string, venue: string, kind: string) => { const matches = assets.data?.items.filter(a => a.symbol === symbol && a.venue === venue && a.asset_type === kind); return matches?.length === 1 ? matches[0] : undefined; };
  const selected=findAsset("NVDA","NASDAQ","equity");
  return <><PageHeading eyebrow="CAPITAL INTELLIGENCE / WORKSPACE" title="Uma visão conectada do mercado" description="Preço, contexto e informações verificáveis. Cada dado conserva sua origem." actions={<Link href="/sources" className="button">Ver cobertura</Link>}/>
    <div className="metrics-grid">{dashboardAssets.map(([symbol,venue,kind])=>{const a=findAsset(symbol,venue,kind);return <Link href={a?"/markets/"+a.id:"/markets"} className="metric-card" key={symbol}><span><AssetMark symbol={symbol}/> {symbol}</span><strong>{price(a?.latest_price,a?.currency)}</strong><span className={(a?.change_pct??0)>=0?"positive":"negative"}>{percent(a?.change_pct)} diário</span><SourceLine source={a?.source_id} at={a?.updated_at} mode={a?.data_mode}/></Link>;})}</div>
    <div className="dashboard-strip"><span>Fontes habilitadas: {providers.data?.items.filter(p=>p.configured).length ?? "—"}</span><span>Watchlists persistidas: {watchlists.data?.items.length??"—"}</span><span>IA: não configurada</span></div>
    <Failure resource={assets}/>{selected&&<AssetView assetId={selected.id}/>}
    <Panel title="Universo acompanhado" actions={<Link href="/markets" className="text-link">Explorar mercados →</Link>}>{assets.data&&<AssetTable assets={assets.data.items.slice(0,8)}/>}</Panel></>;
}

function MarketsInner({scanner=false, initialQuery=""}: {scanner?:boolean; initialQuery?:string}) {
  const [query,setQuery]=useState(initialQuery); const [kind,setKind]=useState(""); const [venue,setVenue]=useState(""); const [currency,setCurrency]=useState(""); const [page,setPage]=useState(1);
  const path=(scanner?"/scanner":"/assets")+"?q="+encodeURIComponent(query)+"&class="+kind+"&page="+page+"&page_size=10"+(!scanner&&venue?"&venue="+encodeURIComponent(venue):"")+(!scanner&&currency?"&currency="+encodeURIComponent(currency):"");
  const resource=useResource<AssetPage>(path);
  return <><PageHeading eyebrow="UNIVERSO / CATÁLOGO" title={scanner?"Market Scanner":"Mercados"} description="Catálogo e cobertura de preços são distintos. Instrumentos sem feed não exibem valores inventados."/><div className="toolbar"><input aria-label="Pesquisar ativos" placeholder="Pesquisar NVDA, BTC…" value={query} onChange={e=>{setQuery(e.target.value);setPage(1);}}/><select aria-label="Classe do ativo" value={kind} onChange={e=>{setKind(e.target.value);setPage(1);}}><option value="">Todas as classes</option>{Object.entries(assetClass).filter(([id])=>id!=="stock").map(([id,label])=><option key={id} value={id}>{label}</option>)}</select>{!scanner&&<><input aria-label="Filtrar por venue" placeholder="Venue, ex.: NASDAQ" value={venue} onChange={e=>{setVenue(e.target.value);setPage(1);}}/><input aria-label="Filtrar por moeda" placeholder="Moeda, ex.: USD" maxLength={8} value={currency} onChange={e=>{setCurrency(e.target.value.toUpperCase());setPage(1);}}/></>}</div>
  {scanner&&<Notice>Indicadores diários básicos disponíveis na página do ativo. Scanner avançado, filtros salvos e RVOL intradiário ainda não implementados.</Notice>}<Panel title="Instrumentos" subtitle={resource.data?resource.data.total+" registros":"Consulta server-side"}><Failure resource={resource}/>{resource.data&&(resource.data.items.length?<AssetTable assets={resource.data.items}/>:<EmptyState/>)}<div className="pagination"><button className="button small" disabled={page<=1} onClick={()=>setPage(page-1)}>Anterior</button><span>Página {page}</span><button className="button small" disabled={!resource.data||page*10>=resource.data.total} onClick={()=>setPage(page+1)}>Próxima</button></div></Panel></>;
}

export function Markets({scanner=false}: {scanner?:boolean}) { const params=useSearchParams(); const q=params.get("q")??""; return <MarketsInner key={q} scanner={scanner} initialQuery={q}/>; }
export function Macro() {
  const resource=useResource<Collection<MacroEvent>>("/macro/calendar");
  return <><PageHeading eyebrow="CONTEXTO / MACRO" title="Calendário econômico" description="Datas demo ilustram o fluxo. Calendário oficial e consenso licenciado ainda não configurados."/><Notice kind="warning">DEMO — eventos simulados. Actual, consenso e anterior ausentes são mostrados sem números fabricados.</Notice><Panel title="Agenda econômica"><Failure resource={resource}/>{resource.data&&<div className="table-scroll"><table><thead><tr><th>Evento</th><th>Horário BRT</th><th>Realizado</th><th>Consenso</th><th>Anterior</th><th>Fonte</th></tr></thead><tbody>{resource.data.items.map(e=><tr key={e.id}><td><strong>{e.title??e.name}</strong><small>{e.country} · {e.importance}</small></td><td>{date(e.scheduled_at)}</td><td>{number(e.actual)} {e.unit}</td><td>{number(e.consensus)}</td><td>{number(e.previous)}</td><td><SourceLine source={e.source_id} at={e.scheduled_at} mode={e.data_mode}/></td></tr>)}</tbody></table></div>}</Panel></>;
}

function FilingsList({items}: {items:Filing[]}) {
  return <div className="event-list">{items.map(f=><article key={f.id} className="event-item"><div className="event-meta"><span className="tag">{f.form}</span><span>{f.symbol}</span><ModeBadge mode={f.data_mode}/><span className="muted">REPORTADO · v{f.version}</span></div><h3><ExternalLink href={f.source_uri}>{f.title??f.form}</ExternalLink></h3><p className="muted">Período reportado: {f.filing_period_end?date(f.filing_period_end,false):"Não informado"} · Filing: {date(f.filing_date,false)}</p><SourceLine source={f.source_id} dateOnly={f.publication_precision==="date"} at={f.publication_precision==="date"?f.filing_date:f.published_at} mode={f.data_mode}/><small>Ingerido: {date(f.ingested_at)} · Disponível ao sistema: {date(f.available_as_of)}</small></article>)}</div>;
}
export function Filings({news=false}: {news?:boolean}) {
  const resource=useResource<Collection<Filing>>(news?"/news":"/institutional/filings");
  return <><PageHeading eyebrow="INTELIGÊNCIA / DISCLOSURES" title={news?"Publicações e eventos":"Institucional · SEC EDGAR"} description="Metadados públicos com links originais e versões preservadas. Não representam posições atuais ou negócios na data de publicação."/><Notice>Análise por IA não configurada. {news?"Cobertura reduzida a filings públicos; feed de notícias premium não configurado.":"Extração de holdings 13F e transações Form 4 ainda pendente."}</Notice><Panel title="Filings capturados" actions={<Link className="text-link" href="/sources">Saúde da SEC →</Link>}><Failure resource={resource}/>{resource.data&&(resource.data.items.length?<FilingsList items={resource.data.items}/>:<EmptyState title="Nenhum filing real ingerido" description="Configure SEC_USER_AGENT no backend e rode python -m app.cli sync --provider sec_edgar. Falhas não são substituídas por fixtures."/>)}</Panel></>;
}

function assetOption(asset: Asset, assets: Asset[]) {
  return assets.filter(candidate => candidate.symbol === asset.symbol).length > 1 ? asset.symbol + " · " + asset.venue + " · " + (assetClass[asset.asset_type] ?? asset.asset_type) + " · " + asset.id : asset.symbol;
}
export function Watchlists() {
  const session = useSession();
  const canWrite = session?.role === "owner";
  const resource = useResource<Collection<Watchlist>>("/watchlists");
  const assets = useResource<AssetPage>("/assets?page_size=100");
  const [name,setName] = useState(""); const [error,setError] = useState(""); const [busy,setBusy] = useState(false);
  async function create(e:FormEvent) {
    e.preventDefault(); if (!canWrite) return;
    setBusy(true); setError("");
    try { await api("/watchlists",{method:"POST",body:JSON.stringify({name})}); setName(""); resource.refresh(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function add(id:string, asset_id:string) {
    if (!asset_id || !canWrite) return;
    setError(""); setBusy(true);
    try { await api("/watchlists/"+id+"/assets",{method:"POST",body:JSON.stringify({asset_id})}); resource.refresh(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <><PageHeading eyebrow="WORKSPACE / PERSISTÊNCIA" title="Suas watchlists" description="Listas salvas no workspace da sua sessão. Cada ativo mantém a identificação da sua fonte."/>
    {canWrite ? <form className="toolbar" onSubmit={create}><input aria-label="Nome da watchlist" required maxLength={80} placeholder="Nome da nova watchlist" value={name} onChange={e=>setName(e.target.value)} disabled={busy}/><button className="button primary" disabled={busy}>Criar watchlist</button></form> : <Notice>Seu perfil permite apenas leitura. Um proprietário pode editar as watchlists deste workspace.</Notice>}
    {error && <p className="form-error" role="alert">{error}</p>}<Failure resource={resource}/>
    {resource.data?.items.map(list=><Panel key={list.id} title={list.name} actions={canWrite ? <select aria-label={"Adicionar ativo a "+list.name} value="" disabled={busy} onChange={e=>void add(list.id,e.target.value)}><option value="">Adicionar ativo…</option>{assets.data?.items.map(a=><option key={a.id} value={a.id}>{assetOption(a, assets.data?.items ?? [])}</option>)}</select> : undefined}>{list.assets.length ? <AssetTable assets={list.assets}/> : <EmptyState description={canWrite ? "Selecione um ativo para começar." : "Esta watchlist ainda não tem ativos."}/>}</Panel>)}
  </>;
}

export function Alerts() {
  const canWrite = useSession()?.role === "owner";
  const assets = useResource<AssetPage>("/assets?page_size=100"); const rules = useResource<Collection<AlertRule>>("/alert-rules"); const alerts = useResource<Collection<Alert>>("/alerts");
  const [assetId,setAssetId] = useState(""); const [threshold,setThreshold] = useState(""); const [direction,setDirection] = useState("above"); const [error,setError] = useState(""); const [busy,setBusy] = useState(false);
  async function create(e:FormEvent) {
    e.preventDefault(); if (!canWrite) return;
    setBusy(true); setError("");
    try { await api("/alert-rules",{method:"POST",body:JSON.stringify({asset_id:assetId,threshold:Number(threshold),direction})}); rules.refresh(); alerts.refresh(); setThreshold(""); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function toggle(rule:AlertRule) {
    if (!canWrite) return;
    setBusy(true); setError("");
    try { await api("/alert-rules/"+rule.id,{method:"PATCH",body:JSON.stringify({enabled:!rule.enabled})}); rules.refresh(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <><PageHeading eyebrow="WORKSPACE / REGRAS" title="Alertas analíticos" description="Regras de preço determinísticas. Não executam ordens nem prometem retorno."/><Notice>Regras criadas nesta tela usam a série DEMO. Alertas incluem a evidência da barra utilizada e são deduplicados.</Notice>
    {canWrite ? <Panel title="Nova regra"><form className="toolbar" onSubmit={create}><select aria-label="Ativo do alerta" value={assetId} onChange={e=>setAssetId(e.target.value)} required disabled={busy}><option value="">Selecione um ativo</option>{assets.data?.items.filter(a=>a.latest_price!=null).map(a=><option value={a.id} key={a.id}>{assetOption(a, assets.data?.items ?? [])}</option>)}</select><select aria-label="Condição" value={direction} onChange={e=>setDirection(e.target.value)} disabled={busy}><option value="above">Preço acima de</option><option value="below">Preço abaixo de</option></select><input type="number" step="any" min="0.00000001" required aria-label="Limiar do alerta" placeholder="Limiar em moeda de origem" value={threshold} onChange={e=>setThreshold(e.target.value)} disabled={busy}/><button className="button primary" disabled={busy}>Criar regra</button></form></Panel> : <Notice>Seu perfil permite apenas leitura. Um proprietário pode criar e alterar regras deste workspace.</Notice>}
    {error && <p role="alert" className="form-error">{error}</p>}
    <div className="two-columns"><Panel title="Regras persistidas"><Failure resource={rules}/>{rules.data?.items.map(r=><div className="rule-item" key={r.id}><span><strong>{assets.data?.items.find(a=>a.id===r.asset_id)?.symbol??r.asset_id}</strong> {r.direction==="above"?"acima de":"abaixo de"} {number(r.threshold)}<small>{r.source_id === "demo" ? "DEMO" : r.source_id} · {r.enabled?"Ativa":"Pausada"}</small></span>{canWrite && <button className="button small" disabled={busy} onClick={()=>void toggle(r)}>{r.enabled?"Pausar":"Ativar"}</button>}</div>)}</Panel>
    <Panel title="Eventos de alerta"><Failure resource={alerts}/>{alerts.data?.items.length ? alerts.data.items.map(a=><div key={a.id} className="event-item"><h3>{assets.data?.items.find(item=>item.id===a.asset_id)?.symbol??a.asset_id}</h3><p>{a.message}</p><p>Preço observado: {price(a.observed_price,a.observed_currency)} · Limiar: {number(a.threshold)}</p><SourceLine source={a.source_id} at={a.event_time} mode={a.data_mode}/><small>Disponível ao sistema: {date(a.available_as_of)} · Alerta criado: {date(a.created_at)}</small></div>) : !alerts.loading && !alerts.error && <EmptyState description="Nenhuma regra acionada."/>}</Panel></div>
  </>;
}
export function Sources(){const resource=useResource<Collection<Provider>>("/providers");return <><PageHeading eyebrow="SISTEMA / QUALIDADE" title="Fontes de dados" description="Saúde operacional, cobertura e licença. Uma fonte configurada pode estar indisponível."/><Notice>Não configurado significa que nenhum feed está ativo. DEMO não conta como cobertura real. Consulte os termos antes de habilitar novos datasets.</Notice><Failure resource={resource}/><div className="source-grid">{resource.data?.items.map(p=><Panel key={p.id} title={p.name} subtitle={p.dataset} actions={<ModeBadge mode={p.data_mode}/> }><dl><dt>Status</dt><dd>{p.status}</dd><dt>Último sucesso</dt><dd>{date(p.last_success_at)}</dd><dt>Latência</dt><dd>{p.latency_ms!=null?number(p.latency_ms,0)+" ms":"—"}</dd><dt>Licença</dt><dd>{p.license_type??"UNKNOWN"}</dd><dt>Limites</dt><dd>{p.rate_limit}</dd><dt>Redistribuição / IA</dt><dd>{p.allowed_redistribution===true?"Permitida":"Bloqueada ou não verificada"} / {p.ai_processing_allowed===true?"Permitida":"Bloqueada ou não verificada"}</dd></dl>{p.last_error&&<p className="form-error">{p.last_error}</p>}<ExternalLink href={p.documentation_url}>Documentação oficial</ExternalLink></Panel>)}</div></>}
export function Settings(){const session=useSession();return <><PageHeading eyebrow="SISTEMA / CONFIGURAÇÃO" title="Preferências e integrações" description="A configuração de fornecedores pertence ao backend."/><Panel title="Ambiente local"><dl><dt>Idioma</dt><dd>Português (pt-BR); termos centrais preparados para en-US.</dd><dt>Timezone de exibição</dt><dd>America/Sao_Paulo</dd><dt>Autenticação</dt><dd>{session?.mode === "AUTHENTICATED" ? "Conta autenticada com Keycloak." : "Acesso demo local."}</dd><dt>Conta e acesso</dt><dd>{session?.user.name} · {session?.role === "owner" ? "Proprietário" : "Somente leitura"}</dd><dt>SEC EDGAR</dt><dd>Configure SEC_USER_AGENT no .env local e execute a CLI de sync.</dd><dt>Coinbase</dt><dd>Desativada. Uso pessoal depende de aceite dos termos; IA e redistribuição não permitidas.</dd><dt>IA / feeds premium</dt><dd>Não configurados; contratação e implementação pendentes.</dd></dl><Notice>Tokens do provedor não são expostos ao aplicativo. A sessão é mantida em cookie HttpOnly; sair encerra a sessão deste aplicativo. Leia o runbook e docs/licensing.md antes de configurar fontes.</Notice><Link className="button" href="/sources">Ver status dos conectores</Link></Panel></>}
