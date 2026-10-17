/** Wire contracts for the versioned API. Monetary values retain their original currency. */
export type DataMode = "LIVE" | "DELAYED" | "END_OF_DAY" | "DEMO" | "STALE" | "NOT_CONFIGURED" | "UNAVAILABLE";
export type EvidenceKind = "OBSERVED" | "REPORTED" | "ESTIMATED" | "INFERRED" | "SIMULATED" | "UNAVAILABLE";
export interface Collection<T> { items: T[]; data_mode?: DataMode; source_id?: string; }
export interface Asset {
  id: string; symbol: string; display_name: string; name?: string; asset_type: string;
  currency: string; venue: string; timezone?: string; latest_price?: number | null;
  change_pct?: number | null; data_mode?: DataMode; source_id?: string; updated_at?: string | null;
}
export interface AssetPage extends Collection<Asset> { total: number; page: number; page_size: number; }
export interface Bar { close_time: string; time: string; open: number; high: number; low: number; close: number; volume: number; source_id: string; data_mode: DataMode; }
export interface Bars extends Collection<Bar> { data_mode: DataMode; source_id: string; as_of?: string; adjustment?: string; }
export interface MonthlyReturn { month: string; return_pct: number | null; partial: boolean; reason?: string | null; observations?: number; expected_observations?: number; gaps?: string[]; }
export interface Returns extends Collection<MonthlyReturn> { data_mode: DataMode; source_id: string; as_of?: string; methodology?: string; }
export interface Provider {
  id: string; provider_id?: string; name: string; dataset: string; status: string; data_mode: DataMode;
  last_success_at?: string | null; last_error?: string | null; documentation_url?: string;
  license_type?: string; allowed_redistribution?: string | boolean; ai_processing_allowed?: string | boolean;
  rate_limit?: string; configured: boolean; latency_ms?: number | null;
}
export interface Watchlist { id: string; name: string; asset_ids: string[]; assets: Asset[]; }
export interface AlertRule { source_id?: string; id: string; asset_id: string; threshold: number; direction: "above" | "below"; enabled?: boolean; created_at?: string; data_mode?: DataMode; }
export interface Alert { observed_price?: number; threshold?: number; event_time?: string; available_as_of?: string; id: string; asset_id?: string; title?: string; message?: string; created_at?: string; triggered_at?: string; data_mode?: DataMode; source_id?: string; evidence_kind?: EvidenceKind; }
export interface Filing {
  id: string; asset_id?: string | null; company_name?: string; symbol?: string; form: string; cik: string;
  accession_number?: string; source_id: string; source_uri: string; published_at?: string;
  filed_at?: string; filing_date?: string; filing_period_end?: string | null; report_date?: string | null;
  ingested_at?: string; available_as_of?: string; data_mode: DataMode; evidence_kind?: EvidenceKind;
  publication_precision?: "date" | "timestamp"; primary_document?: string; title?: string; version?: number;
}
export interface News {
  id: string; title: string; summary?: string; source_id: string; source_uri: string; published_at: string;
  ingested_at?: string; data_mode: DataMode; evidence_kind?: EvidenceKind; asset_id?: string | null;
}
export interface MacroEvent {
  id: string; name?: string; title?: string; country: string; scheduled_at: string; released_at?: string | null;
  actual?: number | null; consensus?: number | null; previous?: number | null; revised_previous?: number | null;
  unit?: string; importance?: string | number; source_id: string; source_uri?: string; data_mode: DataMode;
}
/** Authentication describes identity only; financial data keeps its own DataMode. */
export type AuthMode = "demo" | "oidc";
export interface AuthConfig { auth_mode: AuthMode; configured: boolean; demo_available: boolean; login_path: "/api/v1/auth/login"; }
export interface Session {
  mode: "DEMO" | "AUTHENTICATED";
  auth_mode: AuthMode;
  user: { id: string; name: string };
  tenant_id: string;
  role: "owner" | "viewer";
  csrf_token: string | null;
  expires_at?: string;
}



