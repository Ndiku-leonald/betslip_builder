import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LiveCard } from "./live-card";
import type { LiveFixture } from "@/lib/api";

const fixture: LiveFixture = {
  id: "live-1", sport: "football", competition: "Test League", home: "Home FC", away: "Away FC",
  kickoff_at: "2026-09-23T16:00:00Z", status: "live", status_detail: "Second Half", home_score: 1, away_score: 0,
  period: "61", clock: "61'", provider: "api-football", observed_at: "2026-09-23T16:01:00Z", provider_updated_at: "2026-09-23T16:01:00Z", ingested_at: "2026-09-23T16:01:00Z", freshness: "LIVE_CURRENT", data_age_seconds: 12,
  data_quality: { overall: .8, status: "MEDIUM", state_age_seconds: 12 }, pre_match_probability: { home_win: .47 }, live_probability: { home_win: .61 }, probability_delta: { home_win: .14 }, confidence: 58, calibration_status: "PARTIALLY_CALIBRATED", warnings: ["Live market prices unavailable — no betting-market recommendation generated."],
};

describe("LiveCard", () => {
  it("distinguishes pre-match and live probabilities and surfaces warnings", () => {
    render(<LiveCard fixture={fixture} />);
    expect(screen.getByText("61%", { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/pre 47%/)).toBeInTheDocument();
    expect(screen.getByText(/\+14 pp/)).toBeInTheDocument();
    expect(screen.getByText(/Live market prices unavailable/)).toBeInTheDocument();
  });
});
