import React from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import BuilderPage from "./page";
import { api, SlipBuildResult } from "@/lib/api";

vi.mock("next/navigation", () => ({ usePathname: () => "/builder" }));

const result: SlipBuildResult = { status: "TARGET_REACHED", message: "estimate", target_odds: 3, profile: "balanced", mode: "prematch", target_reached: true, warnings: [], diagnostics: {}, exclusions: [], slips: [{ id: "slip-1", target_odds: 3, combined_odds: 3, target_difference: 0, profile: "balanced", mode: "prematch", bookmaker: "Book", provider: "provider", naive_joint_probability: .56, risk_adjusted_probability: .54, correlation_risk: "LOW", target_reached: true, warnings: [], legs: [{ id: "leg-1", fixture_id: "fixture-1", sport: "football", competition: "Test League", home: "Home", away: "Away", status: "PRE_MATCH", market_family: "1x2", market_type: "1x2", participant: "none", selection: "home", line: null, bookmaker_odds: 1.5, model_probability: .8, confidence: 80, data_quality: 90, explanation: "Fresh and model screened." }, { id: "leg-2", fixture_id: "fixture-2", sport: "football", competition: "Test League", home: "Home 2", away: "Away 2", status: "PRE_MATCH", market_family: "1x2", market_type: "1x2", participant: "none", selection: "home", line: null, bookmaker_odds: 2, model_probability: .7, confidence: 75, data_quality: 85, explanation: "Fresh and model screened." }] }] };

describe("BuilderPage", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it("renders controls, submits a build, shows alternatives and recalculates after leg removal", async () => {
    vi.spyOn(api, "buildSlip").mockResolvedValue(result);
    const user = userEvent.setup();
    render(<BuilderPage />);
    expect(screen.getByRole("heading", { name: "Build around a target odd." })).toBeInTheDocument();
    expect(screen.getByLabelText("Target decimal odds")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Build slip candidates" }));
    expect(await screen.findByText("Home vs Away")).toBeInTheDocument();
    expect(screen.getByText("3.00")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Remove leg" })[0]);
    await waitFor(() => expect(screen.getAllByText("2.00").length).toBeGreaterThan(0));
    expect(screen.getByText(/leg was removed locally/i)).toBeInTheDocument();
  });

  it("supports sport toggles, advanced controls and live/pre-match presentation", async () => {
    vi.spyOn(api, "buildSlip").mockResolvedValue({ ...result, slips: [{ ...result.slips[0], legs: [{ ...result.slips[0].legs[0], status: "LIVE" }] }] });
    const user = userEvent.setup();
    render(<BuilderPage />);
    await user.click(screen.getByText("Advanced settings"));
    expect(screen.getByLabelText("Minimum confidence")).toBeInTheDocument();
    expect(screen.getByLabelText("Target tolerance")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Build slip candidates" }));
    expect(await screen.findByText("LIVE")).toBeInTheDocument();
    expect(screen.getByText("Book · 1 legs · LOW correlation risk")).toBeInTheDocument();
  });

  it("shows no-safe-target and API failure states", async () => {
    vi.spyOn(api, "buildSlip").mockResolvedValue({ ...result, status: "NO_SAFE_TARGET", target_reached: false, slips: [], warnings: ["No eligible slip reached the requested target."] });
    const user = userEvent.setup();
    render(<BuilderPage />);
    await user.click(screen.getByRole("button", { name: "Build slip candidates" }));
    expect(await screen.findByText("No safe target found")).toBeInTheDocument();
    expect(screen.getByText(/No eligible bookmaker-consistent selections/)).toBeInTheDocument();
    vi.restoreAllMocks();
    vi.spyOn(api, "buildSlip").mockRejectedValue(new Error("API unavailable"));
    await user.click(screen.getByRole("button", { name: "Build slip candidates" }));
    expect(await screen.findByText("API unavailable")).toBeInTheDocument();
  });
});
