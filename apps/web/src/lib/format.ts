import type { DataMode, SeriesAdjustment } from "@capital-intelligence/shared-types";
export const locale = "pt-BR";
export const timezone = "America/Sao_Paulo";
export const number = (value: number | null | undefined, digits = 2) => value == null || !Number.isFinite(value) ? "—" : new Intl.NumberFormat(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
export const price = (value: number | null | undefined, currency?: string | null) => value == null || !Number.isFinite(value) ? "—" : currency && /^[a-z]{3}$/i.test(currency) ? new Intl.NumberFormat(locale, { style: "currency", currency, maximumFractionDigits: 2 }).format(value) : number(value) + " (moeda não informada)";
export const adjustmentLabel: Record<SeriesAdjustment, string> = { unadjusted: "Sem ajuste", split_adjusted: "Ajustada por desdobramentos", split_dividend_adjusted: "Ajustada por desdobramentos e dividendos" };
export const percent = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? "—" : (value > 0 ? "+" : "") + number(value) + "%";
export function date(value?: string | null, withTime = true) {
  if (!value || !Number.isFinite(Date.parse(value))) return "Sem atualização";
  return new Intl.DateTimeFormat(locale, { day: "2-digit", month: "short", year: "numeric", ...(withTime ? {hour: "2-digit", minute: "2-digit", timeZone: timezone} : {timeZone: "UTC"}) }).format(new Date(value));
}
export function month(value: string) { return new Intl.DateTimeFormat(locale, {month: "short", year: "2-digit", timeZone: "UTC"}).format(new Date(value + (value.length === 7 ? "-01T00:00:00Z" : ""))); }
export function safeUrl(value?: string | null) { try { const url = new URL(value ?? ""); return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : null; } catch { return null; } }
export const modeLabel: Record<DataMode, string> = {LIVE:"LIVE",DELAYED:"DELAYED",END_OF_DAY:"FECHAMENTO",DEMO:"DEMO",STALE:"DESATUALIZADO",NOT_CONFIGURED:"NÃO CONFIGURADO",UNAVAILABLE:"INDISPONÍVEL"};
export const assetClass: Record<string, string> = {equity:"Ação",stock:"Ação",crypto:"Cripto",etf:"ETF",index:"Índice",forex:"Câmbio",commodity:"Commodity",future:"Futuro",bond:"Renda fixa",reit:"REIT",adr:"ADR",option:"Opção"};

