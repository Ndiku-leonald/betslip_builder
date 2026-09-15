import React from "react";
import Link from "next/link";
import type { Fixture } from "@/lib/api";

export function FixtureCard({ fixture }: { fixture: Fixture }) {
  const live = fixture.status === "live" || fixture.status === "halftime";
  return <Link href={`/fixtures/${fixture.id}`} className="block rounded-2xl focus:outline-none focus:ring-2 focus:ring-mint/70"><article className="rounded-2xl border border-line bg-panel/80 p-5 transition hover:border-mint/50"><div className="flex items-center justify-between text-xs text-slate-500"><span>{fixture.competition || "Competition unavailable"}</span><span className={live ? "rounded-full bg-red-400/15 px-2 py-1 font-bold uppercase tracking-wider text-red-300" : "rounded-full bg-white/5 px-2 py-1 uppercase tracking-wider"}>{live ? "Live" : fixture.status}</span></div><div className="mt-5 grid grid-cols-[1fr_auto] items-center gap-4"><div className="space-y-3 text-sm font-medium"><p>{fixture.home}</p><p>{fixture.away}</p></div><div className="text-right text-xl font-semibold tabular-nums"><p>{fixture.home_score ?? "—"}</p><p>{fixture.away_score ?? "—"}</p></div></div><div className="mt-5 flex items-center justify-between border-t border-line pt-3 text-xs text-slate-500"><span>{live ? (fixture.clock || fixture.period || "In progress") : fixture.kickoff_at ? new Date(fixture.kickoff_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "Kickoff unavailable"}</span><span>{fixture.data_age_seconds == null ? "Observation age unknown" : `Observation age ${fixture.data_age_seconds}s`}</span></div></article></Link>;
}
