"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Shell, PageHeader } from "@/components/chrome";
import type { LiveFixture } from "@/lib/api";
import { api } from "@/lib/api";

export default function LivePage() {
  const [sport, setSport] = useState<"football" | "basketball">("football");
  const query = useQuery({ queryKey: ["live", sport], queryFn: () => api.live(sport), refetchInterval: 60_000 });
  return <Shell><PageHeader eyebrow="Stage Four / live intelligence" title="The live board."><span className="max-w-sm text-right text-xs text-slate-500">Posterior probabilities update the pre-match prior. No automatic bet placement.</span></PageHeader><div className="mb-6 flex w-fit gap-1 rounded-xl border border-line bg-panel p-1"><Tab active={sport === "football"} onClick={() => setSport("football")}>Football</Tab><Tab active={sport === "basketball"} onClick={() => setSport("basketball")}>Basketball</Tab></div>{query.isPending ? <Message>Loading live state…</Message> : query.isError ? <Message>Provider temporarily unavailable.</Message> : query.data?.length ? <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{query.data.map(fixture => <LiveCard key={fixture.id} fixture={fixture} />)}</div> : <Message>No {sport} fixtures are currently live in the normalized store.</Message>}</Shell>;
}

function Tab({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) { return <button onClick={onClick} className={`rounded-lg px-4 py-2 text-sm ${active ? "bg-mint text-ink" : "text-slate-400 hover:bg-white/5"}`}>{children}</button>; }
function Message({ children }: { children: React.ReactNode }) { return <div className="rounded-2xl border border-dashed border-line p-12 text-center text-sm text-slate-500">{children}</div>; }
function LiveCard({ fixture }: { fixture: LiveFixture }) {
  const homeKey = fixture.sport === "football" ? "home_win" : "home_moneyline";
  const home = fixture.live_probability?.[homeKey]; const pre = fixture.pre_match_probability?.[homeKey];
  const age = fixture.data_quality?.state_age_seconds;
  return <Link href={`/live/${fixture.id}`} className="block rounded-2xl focus:outline-none focus:ring-2 focus:ring-mint/70"><article className="rounded-2xl border border-line bg-panel/80 p-5 transition hover:border-mint/50"><div className="flex items-center justify-between text-xs text-slate-500"><span>{fixture.competition || "Competition unavailable"}</span><span className="rounded-full bg-red-400/15 px-2 py-1 font-bold uppercase tracking-wider text-red-300">{fixture.status === "halftime" ? "Halftime" : "Live"}</span></div><div className="mt-5 grid grid-cols-[1fr_auto] items-center gap-4"><div className="space-y-3 text-sm font-medium"><p>{fixture.home}</p><p>{fixture.away}</p></div><div className="text-right text-xl font-semibold tabular-nums"><p>{fixture.home_score ?? "—"}</p><p>{fixture.away_score ?? "—"}</p></div></div><div className="mt-5 flex items-center justify-between border-t border-line pt-3 text-xs text-slate-500"><span>{fixture.clock || fixture.period || "In progress"}</span><span>{age == null ? "Age unknown" : `${age}s old`}</span></div><div className="mt-4 rounded-xl border border-line bg-ink/50 p-3"><div className="flex items-center justify-between text-xs uppercase tracking-[.14em] text-slate-500"><span>Home probability</span><span className="text-mint">{fixture.data_quality?.status || "UNKNOWN"}</span></div><p className="mt-2 text-lg text-white">{home == null ? "—" : `${Math.round(home * 100)}%`} <span className="text-xs text-slate-500">pre {pre == null ? "—" : `${Math.round(pre * 100)}%`} · {fixture.probability_delta?.[homeKey] == null ? "—" : `${fixture.probability_delta[homeKey] >= 0 ? "+" : ""}${Math.round(fixture.probability_delta[homeKey] * 100)} pp`}</span></p><p className="mt-1 text-xs text-slate-500">Confidence {fixture.confidence == null ? "—" : `${Math.round(fixture.confidence)} / 100`} · {fixture.calibration_status || "INSUFFICIENT_EVIDENCE"}</p></div>{fixture.warnings?.length ? <p className="mt-3 text-xs text-amber">{fixture.warnings[0]}</p> : <p className="mt-3 text-xs text-slate-500">Open for prediction and market detail</p>}</article></Link>;
}
