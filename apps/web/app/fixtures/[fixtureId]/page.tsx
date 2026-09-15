"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Shell, PageHeader } from "@/components/chrome";
import { api, FixtureDetail, Prediction } from "@/lib/api";

const tabs = [{ key: "stats", label: "Statistics" }, { key: "events", label: "Events" }, { key: "lineups", label: "Lineups" }, { key: "prediction", label: "Prediction" }] as const;

export default function FixtureDetailPage() {
  const { fixtureId } = useParams<{ fixtureId: string }>();
  const [tab, setTab] = useState<(typeof tabs)[number]["key"]>("stats");
  const fixture = useQuery({ queryKey: ["fixture", fixtureId], queryFn: () => api.fixture(fixtureId), enabled: Boolean(fixtureId) });
  const detail = useQuery<FixtureDetail | Prediction>({ queryKey: ["fixture-detail", fixtureId, tab], queryFn: () => tab === "prediction" ? api.prediction(fixtureId) : api.detail(fixtureId, tab), enabled: Boolean(fixtureId) });
  if (fixture.isPending) return <Shell><p className="text-sm text-slate-500">Loading fixture…</p></Shell>;
  if (fixture.isError || !fixture.data) return <Shell><p className="rounded-xl border border-amber/40 p-5 text-sm text-amber">Fixture unavailable.</p></Shell>;
  const item = fixture.data;
  return <Shell><Link href="/fixtures" className="text-sm text-mint">← Back to fixtures</Link><PageHeader eyebrow={`${item.sport} / fixture detail`} title={`${item.home} vs ${item.away}`}><span className="rounded-full border border-line bg-panel px-4 py-2 text-xs text-slate-400">{item.provider} · {item.freshness}</span></PageHeader>
    <section className="grid gap-4 md:grid-cols-4"><Info label="Competition" value={item.competition || "Unavailable"} /><Info label="Status" value={item.status_detail || item.status} /><Info label="Score" value={`${item.home_score ?? "—"} – ${item.away_score ?? "—"}`} /><Info label="Observation age" value={item.data_age_seconds == null ? "Unknown" : `${item.data_age_seconds}s`} /></section>
    <section className="mt-8 rounded-2xl border border-line bg-panel/80 p-5"><div className="flex flex-wrap gap-2 border-b border-line pb-4">{tabs.map(({ key, label }) => <button key={key} onClick={() => setTab(key)} className={`rounded-lg px-4 py-2 text-sm ${tab === key ? "bg-mint text-ink" : "text-slate-400 hover:bg-white/5"}`}>{label}</button>)}</div>{detail.isPending ? <p className="pt-5 text-sm text-slate-500">Loading detail…</p> : detail.isError ? <p className="pt-5 text-sm text-amber">Detail unavailable.</p> : tab === "prediction" ? <PredictionState prediction={detail.data as Prediction} /> : <DetailState detail={detail.data as FixtureDetail} />}</section></Shell>;
}

function Info({ label, value }: { label: string; value: string }) { return <div className="rounded-xl border border-line bg-panel/70 p-4"><p className="text-xs uppercase tracking-[.15em] text-slate-500">{label}</p><p className="mt-3 text-sm font-medium text-white">{value}</p></div>; }
function DetailState({ detail }: { detail: { available: boolean; data: unknown; message: string | null } }) { if (!detail.available) return <p className="pt-5 text-sm text-slate-500">{detail.message || "This detail is not available from the current provider."}</p>; return <pre className="mt-5 max-h-[32rem] overflow-auto rounded-xl bg-ink p-4 text-xs leading-5 text-slate-300">{JSON.stringify(detail.data, null, 2)}</pre>; }
function PredictionState({ prediction }: { prediction: Prediction }) {
  if (!prediction.available) return <div className="pt-5"><p className="text-sm text-slate-300">No trained production model available.</p><p className="mt-2 text-sm text-slate-500">{prediction.reason || "Prediction unavailable."}</p></div>;
  const markets = Object.entries(prediction.markets || {}).filter((entry): entry is [string, number] => typeof entry[1] === "number").slice(0, 12);
  const summary: [string, number | undefined][] = [["Expected home", prediction.expected_home_goals ?? prediction.expected_home_score], ["Expected away", prediction.expected_away_goals ?? prediction.expected_away_score], ["Data quality", prediction.data_quality?.overall], ["Model confidence score", prediction.model_confidence_score]];
  return <div className="pt-5"><div className="rounded-xl border border-mint/30 bg-mint/5 p-4"><p className="text-xs font-semibold tracking-[.16em] text-mint">MODEL ESTIMATE</p><p className="mt-2 text-xs text-slate-400">Not bookmaker odds or betting certainty · {prediction.model_version}</p></div><div className="mt-4 grid gap-3 sm:grid-cols-2">{summary.map(([label, value]) => <Info key={label} label={label} value={value == null ? "Unavailable" : `${value.toFixed(2)}${label.includes("quality") || label.includes("confidence") ? "/100" : ""}`} />)}</div><div className="mt-5 space-y-3">{markets.map(([key, value]) => <div key={key}><div className="flex justify-between text-xs text-slate-400"><span>{key.replaceAll("_", " ")}</span><span>{(value * 100).toFixed(1)}%</span></div><div className="mt-1 h-2 rounded-full bg-ink"><div className="h-2 rounded-full bg-mint" style={{ width: `${value * 100}%` }} /></div></div>)}</div></div>;
}
