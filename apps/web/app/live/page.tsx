"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Shell, PageHeader } from "@/components/chrome";
import { api } from "@/lib/api";
import { LiveCard } from "./live-card";

export default function LivePage() {
  const [sport, setSport] = useState<"football" | "basketball">("football");
  const query = useQuery({ queryKey: ["live", sport], queryFn: () => api.live(sport), refetchInterval: 60_000 });
  return <Shell><PageHeader eyebrow="Stage Four / live intelligence" title="The live board."><span className="max-w-sm text-right text-xs text-slate-500">Posterior probabilities update the pre-match prior. No automatic bet placement.</span></PageHeader><div className="mb-6 flex w-fit gap-1 rounded-xl border border-line bg-panel p-1"><Tab active={sport === "football"} onClick={() => setSport("football")}>Football</Tab><Tab active={sport === "basketball"} onClick={() => setSport("basketball")}>Basketball</Tab></div>{query.isPending ? <Message>Loading live state…</Message> : query.isError ? <Message>Provider temporarily unavailable.</Message> : query.data?.length ? <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{query.data.map(fixture => <LiveCard key={fixture.id} fixture={fixture} />)}</div> : <Message>No {sport} fixtures are currently live in the normalized store.</Message>}</Shell>;
}

function Tab({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) { return <button onClick={onClick} className={`rounded-lg px-4 py-2 text-sm ${active ? "bg-mint text-ink" : "text-slate-400 hover:bg-white/5"}`}>{children}</button>; }
function Message({ children }: { children: React.ReactNode }) { return <div className="rounded-2xl border border-dashed border-line p-12 text-center text-sm text-slate-500">{children}</div>; }
