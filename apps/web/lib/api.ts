export type Fixture = {
  id: string; sport: string; competition: string | null; home: string; away: string;
  kickoff_at: string | null; status: string; status_detail: string | null;
  home_score: number | null; away_score: number | null; period: string | null; clock: string | null;
  provider: string; observed_at: string | null; provider_updated_at: string | null; ingested_at: string; freshness: string; data_age_seconds: number | null;
};
export type ProviderStatus = { provider: string; configured: boolean; healthy: boolean; last_success_at: string | null; last_error: string | null; latency_ms: number | null; calls_today: number; capabilities: Record<string, boolean> };
export type FixtureDetail = { fixture_id: string; provider: string; available: boolean; availability: "available" | "unsupported" | "not_covered" | "temporarily_unavailable" | "provider_failure"; data: unknown; stale: boolean; message: string | null };
export type Prediction = { available: boolean; fixture_id: string; sport?: string; generated_at?: string; data_cutoff_at?: string; model_version?: string; model?: string; expected_home_goals?: number; expected_away_goals?: number; expected_home_score?: number; expected_away_score?: number; expected_margin?: number; expected_total?: number; markets: Record<string, number | { win: number; push: number; lose: number }>; data_quality: Record<string, number>; model_confidence_score?: number; warnings: string[]; reason?: string };
export type MarketValue = { fixture_id: string; sport: string; bookmaker: string; provider: string; market_family: string; selection: string; line: number | null; bookmaker_odds: number | null; model_probability: number; fair_odds: number | null; raw_implied_probability: number | null; no_vig_probability: number | null; raw_probability_edge: number | null; novig_probability_edge: number | null; expected_value: number | null; confidence: number; data_quality: number; market_reliability?: number | null; freshness: { status: string; age_seconds: number | null }; status: string; compatibility?: string; ranking_score?: number };
export type ModelVersion = { id: string; name: string; version: string; sport?: string; algorithm?: string; trained_at?: string; feature_version?: string; metrics: Record<string, number>; sample_count?: number; status: string };

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`API request failed (${response.status})`);
  return response.json() as Promise<T>;
}
export const api = {
  fixtures: (path = "/api/fixtures/today") => request<Fixture[]>(path),
  fixture: (id: string) => request<Fixture>(`/api/fixtures/${encodeURIComponent(id)}`),
  detail: (id: string, kind: "stats" | "events" | "lineups" | "player-stats") => request<FixtureDetail>(`/api/fixtures/${encodeURIComponent(id)}/${kind}`),
  prediction: (id: string) => request<Prediction>(`/api/fixtures/${encodeURIComponent(id)}/prediction`),
  providers: () => request<ProviderStatus[]>("/api/providers/status"),
  models: () => request<ModelVersion[]>("/api/models"),
  backtests: () => request<Record<string, unknown>[]>("/api/backtests"),
  marketValues: (id: string) => request<{ fixture_id: string; values: MarketValue[]; opportunities: MarketValue[] }>(`/api/fixtures/${encodeURIComponent(id)}/market-values`),
  opportunities: (profile = "balanced") => request<MarketValue[]>(`/api/opportunities?profile=${profile}`),
  movement: (id: string) => request<Record<string, unknown>[]>(`/api/odds/movement?fixture_id=${encodeURIComponent(id)}`),
  sources: () => request<Record<string, unknown>[]>("/api/data-sources"),
};
