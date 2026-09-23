"use client";

import React, { FormEvent, useState } from "react";
import { PageHeader, Shell } from "@/components/chrome";
import { api, SlipBuildResult, SlipOption } from "@/lib/api";

const initial = {
  sports: ["football", "basketball"], target_odds: 5, profile: "balanced", mode: "prematch", include_live: false,
  min_confidence: 50, min_data_quality: 50, min_probability: 0, max_individual_odds: 100,
  min_legs: 2, max_legs: 6, target_tolerance: .1, start_date: "", end_date: "", require_positive_value: false,
};

export default function BuilderPage() {
  const [form, setForm] = useState(initial);
  const [result, setResult] = useState<SlipBuildResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function build(event: FormEvent) {
    event.preventDefault(); setLoading(true); setError(null);
    try { setResult(await api.buildSlip(form)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "The builder service is unavailable."); }
    finally { setLoading(false); }
  }

  function removeLeg(optionIndex: number, legIndex: number) {
    if (!result) return;
    const slips = result.slips.map((option, index) => {
      if (index !== optionIndex) return option;
      const legs = option.legs.filter((_, current) => current !== legIndex);
      const combined = legs.reduce((value, leg) => value * leg.bookmaker_odds, 1);
      const joint = legs.reduce((value, leg) => value * leg.model_probability, 1);
      return { ...option, legs, combined_odds: combined, target_difference: combined - option.target_odds, naive_joint_probability: joint, risk_adjusted_probability: joint, target_reached: legs.length > 0 && combined >= option.target_odds * (1 - form.target_tolerance) && combined <= option.target_odds * (1 + form.target_tolerance), warnings: [...option.warnings, "A leg was removed locally; metrics were recalculated from the stored prices."] };
    });
    setResult({ ...result, slips });
  }

  return <Shell>
    <PageHeader eyebrow="Stage Five / analytical builder" title="Build around a target odd."><div className="rounded-full border border-amber/30 bg-amber/10 px-4 py-2 text-xs text-amber">Estimates only · no bet placement</div></PageHeader>
    <div className="grid gap-8 xl:grid-cols-[360px_1fr]">
      <form onSubmit={build} className="rounded-2xl border border-line bg-panel/80 p-6">
        <p className="text-xs uppercase tracking-[.2em] text-slate-500">Controls</p>
        <div className="mt-6 space-y-5">
          <label className="block text-sm text-slate-300">Sports<div className="mt-2 flex gap-2">
            {(["football", "basketball"] as const).map(sport => <button key={sport} type="button" onClick={() => setForm(current => ({ ...current, sports: current.sports.includes(sport) ? current.sports.filter(item => item !== sport) : [...current.sports, sport] }))} className={`rounded-lg border px-3 py-2 text-xs ${form.sports.includes(sport) ? "border-mint bg-mint/10 text-mint" : "border-line text-slate-500"}`}>{sport[0].toUpperCase() + sport.slice(1)}</button>)}
          </div></label>
          <label className="block text-sm text-slate-300">Target decimal odds<input aria-label="Target decimal odds" type="number" min="1.01" step=".01" value={form.target_odds} onChange={event => setForm({ ...form, target_odds: Number(event.target.value) })} className="mt-2 w-full rounded-lg border border-line bg-ink px-3 py-2 text-white" /></label>
          <label className="block text-sm text-slate-300">Risk profile<select aria-label="Risk profile" value={form.profile} onChange={event => setForm({ ...form, profile: event.target.value })} className="mt-2 w-full rounded-lg border border-line bg-ink px-3 py-2 text-white"><option value="conservative">Conservative</option><option value="balanced">Balanced</option><option value="aggressive">Aggressive</option></select></label>
          <div className="grid grid-cols-2 gap-3"><label className="text-sm text-slate-300">Min legs<input aria-label="Minimum legs" type="number" min="1" max="12" value={form.min_legs} onChange={event => setForm({ ...form, min_legs: Number(event.target.value) })} className="mt-2 w-full rounded-lg border border-line bg-ink px-3 py-2 text-white" /></label><label className="text-sm text-slate-300">Max legs<input aria-label="Maximum legs" type="number" min="1" max="12" value={form.max_legs} onChange={event => setForm({ ...form, max_legs: Number(event.target.value) })} className="mt-2 w-full rounded-lg border border-line bg-ink px-3 py-2 text-white" /></label></div>
          <label className="flex items-center gap-3 text-sm text-slate-300"><input type="checkbox" checked={form.include_live} onChange={event => setForm({ ...form, include_live: event.target.checked, mode: event.target.checked ? "both" : "prematch" })} /> Include eligible live markets</label>
          <details className="rounded-xl border border-line bg-ink/40 p-3"><summary className="cursor-pointer text-sm text-slate-300">Advanced settings</summary><div className="mt-4 grid grid-cols-2 gap-3">
            <label className="text-xs text-slate-400">Start date<input aria-label="Start date" type="date" value={form.start_date} onChange={event => setForm({ ...form, start_date: event.target.value })} className="mt-2 w-full rounded-lg border border-line bg-ink px-2 py-2 text-white" /></label>
            <label className="text-xs text-slate-400">End date<input aria-label="End date" type="date" value={form.end_date} onChange={event => setForm({ ...form, end_date: event.target.value })} className="mt-2 w-full rounded-lg border border-line bg-ink px-2 py-2 text-white" /></label>
            <label className="text-xs text-slate-400">Min confidence<input aria-label="Minimum confidence" type="number" min="0" max="100" value={form.min_confidence} onChange={event => setForm({ ...form, min_confidence: Number(event.target.value) })} className="mt-2 w-full rounded-lg border border-line bg-ink px-2 py-2 text-white" /></label>
            <label className="text-xs text-slate-400">Min data quality<input aria-label="Minimum data quality" type="number" min="0" max="100" value={form.min_data_quality} onChange={event => setForm({ ...form, min_data_quality: Number(event.target.value) })} className="mt-2 w-full rounded-lg border border-line bg-ink px-2 py-2 text-white" /></label>
            <label className="text-xs text-slate-400">Min probability<input aria-label="Minimum probability" type="number" min="0" max=".99" step=".01" value={form.min_probability} onChange={event => setForm({ ...form, min_probability: Number(event.target.value) })} className="mt-2 w-full rounded-lg border border-line bg-ink px-2 py-2 text-white" /></label>
            <label className="text-xs text-slate-400">Max leg odds<input aria-label="Maximum individual odds" type="number" min="1.01" max="100" step=".01" value={form.max_individual_odds} onChange={event => setForm({ ...form, max_individual_odds: Number(event.target.value) })} className="mt-2 w-full rounded-lg border border-line bg-ink px-2 py-2 text-white" /></label>
            <label className="text-xs text-slate-400">Target tolerance<input aria-label="Target tolerance" type="number" min="0" max=".5" step=".01" value={form.target_tolerance} onChange={event => setForm({ ...form, target_tolerance: Number(event.target.value) })} className="mt-2 w-full rounded-lg border border-line bg-ink px-2 py-2 text-white" /></label>
            <label className="col-span-2 flex items-center gap-2 text-xs text-slate-400"><input aria-label="Require positive value" type="checkbox" checked={form.require_positive_value} onChange={event => setForm({ ...form, require_positive_value: event.target.checked })} /> Require positive value</label>
          </div></details>
          <p className="text-xs leading-5 text-slate-500">Freshness, settlement, model compatibility, data quality, bookmaker consistency and correlation gates remain active.</p>
          <button disabled={loading || !form.sports.length} className="w-full rounded-lg bg-mint px-4 py-3 text-sm font-semibold text-ink disabled:opacity-40">{loading ? "Searching eligible markets…" : "Build slip candidates"}</button>
        </div>
      </form>
      <section aria-live="polite">{error && <State text={error} error />}{result && <div className={`mb-5 rounded-2xl border p-5 ${result.target_reached ? "border-mint/30 bg-mint/5" : "border-amber/30 bg-amber/5"}`}><p className="text-xs uppercase tracking-[.18em] text-slate-500">{result.status === "TARGET_REACHED" ? "Target reached within tolerance" : "No safe target found"}</p><h2 className="mt-2 text-xl font-semibold text-white">{result.target_reached ? `Eligible options near ${result.target_odds.toFixed(2)}` : "Constraints were kept intact"}</h2><p className="mt-2 text-sm leading-6 text-slate-400">{result.warnings.join(" ") || result.message}</p></div>}{result?.slips.length ? <div className="space-y-5">{result.slips.map((option, index) => <SlipCard key={option.id || index} option={option} index={index} onRemove={removeLeg} />)}</div> : result && <State text="No eligible bookmaker-consistent selections were available for these constraints." />}{!result && !error && <State text="Choose a target and profile to inspect statistically screened, single-bookmaker candidates." />}</section>
    </div>
    <p className="mt-8 text-xs leading-5 text-slate-500">Probabilities are model estimates and odds can change. A selection can lose. SlipIQ does not guarantee outcomes, profit, or execution.</p>
  </Shell>;
}

function SlipCard({ option, index, onRemove }: { option: SlipOption; index: number; onRemove: (optionIndex: number, legIndex: number) => void }) {
  return <article className="rounded-2xl border border-line bg-panel/80 p-5"><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs uppercase tracking-[.18em] text-mint">{index === 0 ? "Best fit" : index === 1 ? "Higher confidence" : "Alternative"}</p><h2 className="mt-2 text-xl font-semibold text-white">{option.combined_odds.toFixed(2)} <span className="text-sm font-normal text-slate-500">requested {option.target_odds.toFixed(2)}</span></h2><p className="mt-1 text-xs text-slate-500">{option.bookmaker || "Bookmaker unavailable"} · {option.legs.length} legs · {option.correlation_risk} correlation risk</p></div><div className="grid grid-cols-2 gap-3 text-right text-xs"><Metric label="Joint estimate" value={`${(option.risk_adjusted_probability * 100).toFixed(1)}%`} /><Metric label="Confidence" value={`${Math.min(...option.legs.map(leg => leg.confidence), 0).toFixed(0)}%`} />{(option.push_affected_probability || 0) > 0 && <Metric label="Push-aware" value={`${((option.push_affected_probability || 0) * 100).toFixed(1)}%`} />}</div></div><div className="mt-5 space-y-3">{option.legs.map((leg, legIndex) => <div key={`${leg.fixture_id}-${legIndex}`} className="rounded-xl border border-line bg-ink/50 p-4"><div className="flex items-start justify-between gap-3"><div><div className="flex flex-wrap items-center gap-2"><span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${leg.status === "LIVE" ? "bg-amber/15 text-amber" : "bg-mint/10 text-mint"}`}>{leg.status === "LIVE" ? "LIVE" : "PRE-MATCH"}</span><span className="text-xs text-slate-500">{leg.sport} · {leg.competition || "Competition unavailable"}</span></div><h3 className="mt-2 text-sm font-semibold text-white">{leg.home} vs {leg.away}</h3><p className="mt-1 text-xs text-slate-400">{leg.market_type} · {leg.selection}{leg.line !== null ? ` ${leg.line}` : ""}</p></div><div className="text-right"><p className="text-lg font-semibold text-white">{leg.bookmaker_odds.toFixed(2)}</p><button type="button" onClick={() => onRemove(index, legIndex)} className="mt-2 text-xs text-amber hover:text-white">Remove leg</button></div></div><div className="mt-3 flex flex-wrap gap-4 text-xs text-slate-400"><span>Model {(leg.model_probability * 100).toFixed(1)}%</span><span>Confidence {leg.confidence.toFixed(0)}%</span><span>Quality {leg.data_quality.toFixed(0)}%</span>{leg.expected_value !== null && leg.expected_value !== undefined && <span>EV {(leg.expected_value * 100).toFixed(1)}%</span>}</div><p className="mt-3 text-xs leading-5 text-slate-500">{leg.explanation}</p></div>)}</div>{option.warnings.length > 0 && <p className="mt-4 text-xs leading-5 text-amber">{option.warnings.join(" ")}</p>}</article>;
}

function Metric({ label, value }: { label: string; value: string }) { return <div><p className="text-[10px] uppercase tracking-[.14em] text-slate-500">{label}</p><p className="mt-1 text-sm font-semibold text-white">{value}</p></div>; }
function State({ text, error = false }: { text: string; error?: boolean }) { return <div className={`rounded-2xl border border-dashed p-8 text-sm leading-6 ${error ? "border-amber/50 text-amber" : "border-line text-slate-500"}`}>{text}</div>; }
