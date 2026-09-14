import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FixtureCard } from "./fixture-card";

describe("FixtureCard", () => {
  it("renders real fixture fields and freshness age", () => {
    render(<FixtureCard fixture={{ id: "1", sport: "football", competition: "Premier League", home: "Arsenal", away: "Chelsea", kickoff_at: "2026-09-14T16:00:00Z", status: "live", status_detail: "Second Half", home_score: 1, away_score: 0, period: "61", clock: "61'", provider: "api-football", provider_timestamp: "2026-09-14T16:00:00Z", ingested_at: "2026-09-14T16:00:00Z", freshness: "LIVE_CURRENT", data_age_seconds: 18 }} />);
    expect(screen.getByText("Arsenal")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(screen.getByText("18s old")).toBeInTheDocument();
  });
});
