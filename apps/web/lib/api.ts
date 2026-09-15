export type Fixture = {
  id: string; sport: string; competition: string | null; home: string; away: string;
  kickoff_at: string | null; status: string; status_detail: string | null;
  home_score: number | null; away_score: number | null; period: string | null; clock: string | null;
  provider: string; observed_at: string | null; provider_updated_at: string | null; ingested_at: string; freshness: string; data_age_seconds: number | null;
};
export type ProviderStatus = { provider: string; configured: boolean; healthy: boolean; last_success_at: string | null; last_error: string | null; latency_ms: number | null; calls_today: number; capabilities: Record<string, boolean> };
export type FixtureDetail = { fixture_id: string; provider: string; available: boolean; availability: "available" | "unsupported" | "not_covered" | "temporarily_unavailable" | "provider_failure"; data: unknown; stale: boolean; message: string | null };

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`API request failed (${response.status})`);
  return response.json() as Promise<T>;
}
export const api = {
  fixtures: (path = "/api/fixtures/today") => request<Fixture[]>(path),
  fixture: (id: string) => request<Fixture>(`/api/fixtures/${encodeURIComponent(id)}`),
  detail: (id: string, kind: "stats" | "events" | "lineups") => request<FixtureDetail>(`/api/fixtures/${encodeURIComponent(id)}/${kind}`),
  providers: () => request<ProviderStatus[]>("/api/providers/status"),
};
