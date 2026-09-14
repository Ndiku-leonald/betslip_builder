"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Shell, PageHeader } from "@/components/chrome";
import { FixtureCard } from "@/components/fixture-card";
import { api } from "@/lib/api";

export default function LivePage() {
  const [sport, setSport] = useState<"football" | "basketball">("football");
  const query = useQuery({ queryKey: ["live", sport], queryFn: () => api.fixtures(`/api/fixtures/live?sport=${sport}`), refetchInterval: 60_000 });
  return <Shell><PageHeader eyebrow="Live / current state" title="The live board."><span className="text-xs text-slate-500">Refreshes according to quota mode · no live predictions</span></PageHeader><div className="mb-6 flex w-fit gap-1 rounded-xl border border-line bg-panel p-1"><button onClick={() => setSport("football")} className={`rounded-lg px-4 py-2 text-sm ${sport === "football" ? "bg-mint text-ink" : "text-slate-400"}`}>Football</button><button onClick={() => setSport("basketball")} className={`rounded-lg px-4 py-2 text-sm ${sport === "basketball" ? "bg-mint text-ink" : "text-slate-400"}`}>Basketball</button></div>{query.isPending ? <Empty text="Loading live provider data…"/> : query.isError ? <Empty text="Live data unavailable. The backend will show a provider error rather than stale certainty."/> : query.data?.length ? <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{query.data.map(f => <FixtureCard key={f.id} fixture={f}/>)}</div> : <Empty text={`No ${sport} fixtures are currently live in the normalized store.`}/>}</Shell>;
}
function Empty({ text }: { text: string }) { return <div className="rounded-2xl border border-dashed border-line p-12 text-center text-sm text-slate-500">{text}</div>; }

