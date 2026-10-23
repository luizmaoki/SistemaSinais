"use client";
import Link from "next/link";
import { useState, type FormEvent, type ReactNode } from "react";
import type { Asset, AssetCalendar, AssetIdentifier, Collection, CorporateActions } from "@capital-intelligence/shared-types";
import { useResource } from "@/lib/api";
import { date, locale, number, price } from "@/lib/format";
import { EmptyState, ErrorState, ExternalLink, Loading, ModeBadge, Notice, Panel } from "./ui";

const missing = "Não informado";
const day = (value?: string | null) => value ? date(value, false) : "Não informada";
function Field({ label, children }: { label: string; children?: ReactNode }) {
  return <div><dt>{label}</dt><dd>{children == null || children === "" ? missing : children}</dd></div>;
}
function ResourceState({ resource }: { resource: { loading: boolean; error: Error | null; refresh: () => void } }) {
  return resource.loading ? <Loading /> : resource.error ? <ErrorState error={resource.error} retry={resource.refresh} /> : null;
}
function sessionTime(value: string, timezone: string | null) {
  if (!timezone || !Number.isFinite(Date.parse(value))) return "Horário indisponível";
  try {
    return new Intl.DateTimeFormat(locale, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: timezone, timeZoneName: "short" }).format(new Date(value));
  } catch { return "Fuso indisponível"; }
}
function CalendarPanel({ asset }: { asset: Asset }) {
  const [range, setRange] = useState(() => {
    const from = new Date();
    const to = new Date(from);
    to.setUTCDate(to.getUTCDate() + 14);
    return { from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) };
  });
  const [draft, setDraft] = useState(range);
  const [error, setError] = useState("");
  const resource = useResource<AssetCalendar>("/assets/" + asset.id + "/calendar?" + new URLSearchParams(range));
  function submit(event: FormEvent) {
    event.preventDefault();
    const span = Date.parse(draft.to) - Date.parse(draft.from);
    if (!Number.isFinite(span) || span < 0 || span > 365 * 86400000) {
      setError("Selecione um intervalo de até 366 dias, com o fim igual ou posterior ao início.");
      return;
    }
    setError("");
    setRange(draft);
  }
  const calendar = resource.data;
  return <Panel title="Calendário de negociação" subtitle="Abertura e fechamento no fuso do calendário">
    <form className="toolbar calendar-controls" onSubmit={submit}>
      <label>De <input aria-label="Calendário de" type="date" required value={draft.from} onChange={event => setDraft({ ...draft, from: event.target.value })} /></label>
      <label>Até <input aria-label="Calendário até" type="date" required value={draft.to} onChange={event => setDraft({ ...draft, to: event.target.value })} /></label>
      <button className="button small">Consultar sessões</button>
    </form>
    {error && <p role="alert" className="form-error">{error}</p>}
    <ResourceState resource={resource} />
    {calendar && <><p className="catalog-caption">{calendar.calendar_id ?? "Calendário não informado"} · {calendar.timezone ?? "Fuso não informado"} · {calendar.currency ?? "Moeda não informada"}</p>
      {calendar.status === "UNAVAILABLE" ? <EmptyState title="Calendário indisponível" description={calendar.reason ?? "Não há calendário configurado para este instrumento."} /> : <>
        {["NASDAQ", "XNAS", "NYSE ARCA", "ARCX", "NYSE AMERICAN", "XASE"].includes(asset.venue) && calendar.calendar_id === "XNYS" && <Notice>{asset.venue} usa as sessões de XNYS disponíveis na biblioteca de calendários. Particularidades exclusivas do venue não são confirmadas por esta cobertura.</Notice>}
        {calendar.items.length ? <div className="table-scroll catalog-scroll"><table><thead><tr><th>Sessão</th><th>Abertura</th><th>Fechamento</th></tr></thead><tbody>{calendar.items.map(session => <tr key={session.session_date}><td>{date(session.session_date, false)}</td><td><time dateTime={session.open_at}>{sessionTime(session.open_at, calendar.timezone)}</time></td><td><time dateTime={session.close_at}>{sessionTime(session.close_at, calendar.timezone)}</time></td></tr>)}</tbody></table></div> : <EmptyState title="Nenhuma sessão no intervalo" description="O calendário não retornou sessões para as datas selecionadas." />}
      </>}
      <small>Consultado em: {date(calendar.as_of)} · Horários exibidos em {calendar.timezone ?? "fuso não informado"}.</small>
    </>}
  </Panel>;
}
const actionLabels: Record<string, string> = { split: "Desdobramento", reverse_split: "Grupamento", dividend: "Dividendo em dinheiro", cash_dividend: "Dividendo em dinheiro", symbol_change: "Alteração de ticker", merger: "Fusão", spin_off: "Cisão" };
const detailLabels: Record<string, string> = { ratio: "Razão", split_ratio: "Razão do desdobramento", cash_amount: "Valor em dinheiro", amount: "Valor", currency: "Moeda", reference_price: "Preço de referência", old_symbol: "Ticker anterior", new_symbol: "Novo ticker", numerator: "Numerador", denominator: "Denominador" };
function detailValue(value: unknown) { return value == null ? missing : typeof value === "object" ? JSON.stringify(value) : String(value); }

function CatalogContent({ asset, asOf, source }: { asset: Asset; asOf: string; source: string }) {
  const identifiers = useResource<Collection<AssetIdentifier>>("/assets/" + asset.id + "/identifiers?" + new URLSearchParams({ known_at: asOf }));
  const actions = useResource<CorporateActions>("/assets/" + asset.id + "/corporate-actions?" + new URLSearchParams({ as_of: asOf, source }));
  return <div className="catalog-content">
    <Panel title="Metadados do instrumento" subtitle="Campos ausentes permanecem explicitamente não informados">
      <dl className="catalog-fields" data-testid="catalog-metadata">
        <Field label="ID estável"><code>{asset.id}</code></Field>
        <Field label="Ticker">{asset.symbol}</Field>
        <Field label="Venue">{asset.venue || missing}</Field>
        <Field label="Bolsa principal">{asset.primary_exchange}</Field>
        <Field label="MIC">{asset.mic}</Field>
        <Field label="Moeda">{asset.currency}</Field>
        <Field label="Fuso">{asset.timezone}</Field>
        <Field label="Calendário">{asset.calendar_id}</Field>
        <Field label="Identificador do instrumento">{asset.instrument_identifier}</Field>
        <Field label="Tipo de instrumento">{asset.instrument_kind}</Field>
        <Field label="Estado do instrumento">{asset.status}</Field>
        <Field label="Estado dos metadados">{asset.metadata_status}</Field>
        <Field label="Ativo subjacente">{asset.underlying_asset_id ? <Link className="text-link" href={"/markets/" + asset.underlying_asset_id}>{asset.underlying_asset_id}</Link> : missing}</Field>
        <Field label="Multiplicador">{asset.contract_multiplier == null ? missing : number(asset.contract_multiplier, 4)}</Field>
        <Field label="Vencimento">{day(asset.expiration)}</Field>
        <Field label="Tipo da opção">{asset.option_type}</Field>
        <Field label="Preço de exercício">{asset.strike == null ? missing : price(asset.strike, asset.currency)}</Field>
        <Field label="Rede / chain">{asset.chain_id}</Field>
        <Field label="Endereço do contrato">{asset.contract_address}</Field>
        <Field label="Listagem">{day(asset.listed_at)}</Field>
        <Field label="Fim da listagem">{day(asset.delisted_at)}</Field>
      </dl>
      <p className="catalog-caption">Fonte do catálogo: {asset.metadata_source_id ?? missing} · <ExternalLink href={asset.metadata_source_uri}>Documento de origem</ExternalLink></p>
      <small>Disponível ao sistema: {date(asset.metadata_available_as_of)} · Ingerido: {date(asset.metadata_ingested_at)}</small>
    </Panel>
    <div className="two-columns">
      <Panel title="Histórico de identificadores" subtitle="Validade inclui o início e exclui o fim">
        <ResourceState resource={identifiers} />
        {identifiers.data && (identifiers.data.items.length ? <div className="table-scroll catalog-scroll"><table><thead><tr><th>Tipo / valor</th><th>Validade</th><th>Origem</th></tr></thead><tbody>{identifiers.data.items.map(identifier => <tr key={identifier.id}><td><strong>{identifier.value}</strong><small>{identifier.identifier_type}{identifier.venue ? " · " + identifier.venue : ""}</small>{identifier.cancelled && <small>Cancelado</small>}</td><td>{day(identifier.effective_from)}<small>Até: {identifier.effective_to ? day(identifier.effective_to) : "Em aberto"}</small></td><td><ExternalLink href={identifier.source_uri}>{identifier.source_id}</ExternalLink>{identifier.version != null && <small>Versão {identifier.version}</small>}<small>Disponível: {date(identifier.available_as_of)}<br />Ingerido: {date(identifier.ingested_at)}</small></td></tr>)}</tbody></table></div> : <EmptyState title="Histórico não disponível" description="Nenhum identificador com proveniência foi informado para este instrumento." />)}
      </Panel>
      <CalendarPanel asset={asset} />
    </div>
    <Panel title="Eventos corporativos" subtitle={"Fonte " + source + " · Registro versionado limitado à disponibilidade selecionada"}>
      <ResourceState resource={actions} />
      {actions.data && <><p className="catalog-caption">{actions.data.coverage ? <>Cobertura: {day(actions.data.coverage.from)} a {day(actions.data.coverage.to)} · {actions.data.coverage.source_id} <ModeBadge mode={actions.data.coverage.data_mode} /></> : "Cobertura de eventos corporativos não informada."}</p>
        {actions.data.items.length ? <div className="event-list catalog-scroll" data-testid="corporate-actions">{actions.data.items.map(action => <article key={action.id + ":" + action.version} className="event-item">
          <div className="event-meta"><strong>{actionLabels[action.action_type] ?? action.action_type}</strong><span>{action.version == null ? "Versão não informada" : "v" + action.version}</span>{action.cancelled && <span className="tag">Cancelado · não aplicado ao ajuste</span>}<ModeBadge mode={action.data_mode} /></div>
          <p>Efetivo em: {action.effective_date ? day(action.effective_date) : date(action.effective_at)} · <ExternalLink href={action.source_uri}>{action.source_id}</ExternalLink></p>
          <dl className="catalog-fields action-details">{Object.entries(action.details).map(([key, value]) => <Field key={key} label={detailLabels[key] ?? key}>{detailValue(value)}</Field>)}</dl>
          <small>Disponível ao sistema: {date(action.available_as_of)} · Ingerido: {date(action.ingested_at)}</small>
        </article>)}</div> : <EmptyState title="Nenhum evento corporativo disponível" description="A ausência de registros não confirma ausência de eventos sem cobertura declarada." />}
      </>}
    </Panel>
  </div>;
}

export function AssetCatalog({ asset, asOf, source }: { asset: Asset; asOf: string; source: string }) {
  const [expanded, setExpanded] = useState(false);
  return <details className="panel asset-catalog" onToggle={event => setExpanded(event.currentTarget.open)}>
    <summary><strong>Identificação, calendário e eventos corporativos</strong><span>{asset.currency ?? "Moeda não informada"} · {asset.venue || "Venue não informado"} · {asset.mic ?? "MIC não informado"}</span></summary>
    {expanded && <CatalogContent key={asset.id + ":" + source + ":" + asOf} asset={asset} asOf={asOf} source={source} />}
  </details>;
}