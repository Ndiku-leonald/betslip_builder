export type Fixture = {
  id: string; sport: string; competition: string | null; home: string; away: string;
  kickoff_at: string | null; status: string; status_detail: string | null;
  home_score: number | null; away_score: number | null; period: string | null; clock: string | null;
  provider: string; observed_at: string | null; provider_updated_at: string | null; ingested_at: string; freshness: string; data_age_seconds: number | null;
};
export type ProviderStatus = { provider: string; configured: boolean; healthy: boolean; last_success_at: string | null; last_error: string | null; latency_ms: number | null; calls_today: number; capabilities: Record<string, boolean> };
export type FixtureDetail = { fixture_id: string; provider: string; available: boolean; availability: "available" | "unsupported" | "not_covered" | "temporarily_unavailable" | "provider_failure"; data: unknown; stale: boolean; message: string | null };
export type Prediction = { available: boolean; fixture_id: string; sport?: string; generated_at?: string; data_cutoff_at?: string; model_version?: string; model?: string; expected_home_goals?: number; expected_away_goals?: number; expected_home_score?: number; expected_away_score?: number; expected_margin?: number; expected_total?: number; markets: Record<string, number | { win: number; push: number; lose: number }>; data_quality: Record<string, number>; model_confidence_score?: number; warnings: string[]; reason?: string };
export type MarketValue = { fixture_id: string; sport: string; bookmaker: string; provider: string; market_family: string; market_type?: string; participant?: "home" | "away" | "none"; selection: string; line: number | null; bookmaker_odds: number | null; model_probability: number | null; model_win_probability?: number | null; model_push_probability?: number | null; model_loss_probability?: number | null; model_resolved_win_probability?: number | null; raw_model_probability?: number | null; calibrated_model_probability?: number | null; fair_odds: number | null; raw_implied_probability: number | null; no_vig_probability: number | null; no_vig_status?: string; raw_probability_edge: number | null; novig_probability_edge: number | null; expected_value: number | null; confidence: number; data_quality: number; market_reliability?: number | null; market_reliability_components?: Record<string, unknown>; source_reliability?: number | null; source_reliability_components?: Record<string, unknown>; provider_agreement?: number | null; material_provider_conflict?: boolean; calibration_status?: string; freshness: { status: string; age_seconds: number | null; fetch_age_seconds?: number | null; price_age_seconds?: number | null; timestamp_source?: string }; status: string; compatibility?: string; reason?: string | null; ranking_score?: number; ranking_components?: Record<string, unknown> };
export type ProviderConsensus = { fixture_id: string; primary: { provider: string; status: string; home: string; away: string; observed_at?: string | null }; secondary: { provider: string; status: string; reason?: string; observed_at?: string | null }; consensus: { agreement: number; source_count: number; conflicts: Array<{ field: string; severity: string; primary_value: unknown; secondary_value: unknown }>; material_conflict?: boolean }; agreement: number; conflicts: Array<{ field: string; severity: string; primary_value: unknown; secondary_value: unknown }>; material_conflict: boolean; ranking_suppressed: boolean };
export type OddsConsensus = { provider: string; fixture_id: string; market_family: string; market_type: string; period: string; participant: string; selection: string; line: number | null; settlement_semantics: string; bookmaker_count: number; best_current_price: number; median_current_price: number; median_raw_implied_probability: number; bookmakers: string[] };
export type MarketValuesResult = { fixture_id: string; values: MarketValue[]; opportunities: MarketValue[]; consensus: ProviderConsensus; odds_consensus?: OddsConsensus[] };
export type LiveFixture = Fixture & { data_quality: { overall?: number; status?: string; state_age_seconds?: number | null; statistics_age_seconds?: number | null }; pre_match_probability: Record<string, number>; live_probability: Record<string, number>; probability_delta: Record<string, number>; confidence: number | null; calibration_status: string | null; warnings: string[] };
export type LivePrediction = { available: boolean; fixture_id: string; sport?: string; state: Record<string, unknown>; pre_match_prediction: Record<string, number>; live_prediction: Record<string, number>; probability_delta: Record<string, number>; model_version?: string | null; model?: string; confidence?: number; data_quality: Record<string, unknown>; calibration_status?: string; warnings: string[]; reason?: string };
export type LiveMarketsResult = { fixture_id: string; values: MarketValue[]; opportunities: MarketValue[]; warnings: string[]; prediction?: LivePrediction; odds_consensus?: OddsConsensus[]; reason?: string };
export type ModelVersion = { id: string; name: string; version: string; sport?: string; algorithm?: string; trained_at?: string; feature_version?: string; metrics: Record<string, number>; sample_count?: number; status: string };

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`API request failed (${response.status})`);
  return response.json() as Promise<T>;
}
export const api = {
  fixtures: (path = "/api/fixtures/today") => request<Fixture[]>(path),
  live: (sport: "football" | "basketball") => request<LiveFixture[]>(`/api/live?sport=${sport}`),
  liveDetail: (id: string) => request<{ fixture: Fixture; prediction: LivePrediction }>(`/api/live/${encodeURIComponent(id)}`),
  livePrediction: (id: string) => request<LivePrediction>(`/api/live/${encodeURIComponent(id)}/prediction`),
  liveMarkets: (id: string) => request<LiveMarketsResult>(`/api/live/${encodeURIComponent(id)}/markets`),
  liveHistory: (id: string) => request<Record<string, unknown>[]>(`/api/live/${encodeURIComponent(id)}/history`),
  fixture: (id: string) => request<Fixture>(`/api/fixtures/${encodeURIComponent(id)}`),
  detail: (id: string, kind: "stats" | "events" | "lineups" | "player-stats") => request<FixtureDetail>(`/api/fixtures/${encodeURIComponent(id)}/${kind}`),
  prediction: (id: string) => request<Prediction>(`/api/fixtures/${encodeURIComponent(id)}/prediction`),
  providers: () => request<ProviderStatus[]>("/api/providers/status"),
  models: () => request<ModelVersion[]>("/api/models"),
  backtests: () => request<Record<string, unknown>[]>("/api/backtests"),
  marketValues: (id: string) => request<MarketValuesResult>(`/api/fixtures/${encodeURIComponent(id)}/market-values`),
  consensus: (id: string) => request<ProviderConsensus>(`/api/provider-consensus/${encodeURIComponent(id)}`),
  opportunities: (profile = "balanced") => request<MarketValue[]>(`/api/opportunities?profile=${profile}`),
  movement: (id: string) => request<Record<string, unknown>[]>(`/api/odds/movement?fixture_id=${encodeURIComponent(id)}`),
  sources: () => request<Record<string, unknown>[]>("/api/data-sources"),
};
