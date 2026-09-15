"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Shell, PageHeader } from "@/components/chrome";
import { api } from "@/lib/api";

const detailKinds = [
  { key: "stats" as const, label: "Statistics" },
  { key: "events" as const, label: "Events" },
  { key: "lineups" as const, label: "Lineups" },
];

export default function FixtureDetailPage() {
  const params = useParams<{ fixtureId: string }>();
  const fixtureId = params.fixtureId;
  const fixture = useQuery({ queryKey: ["fixture", fixtureId], queryFn: () => api.fixture(fixtureId), enabled: Boolean(fixtureId) });
  const [activeKind, setActiveKind] = useStateKind();
  const detail = useQuery({ queryKey: ["fixture-detail", fixtureId, activeKind], queryFn: () => api.detail(fixtureId, activeKind), enabled: Boolean(fixtureId) });

  if (fixture.isPending) return <Shell><p className="text-sm text-slate-500">Loading fixture…</p></Shell>;
  if (fixture.isError || !fixture.data) return <Shell><p className="rounded-xl border border-amber/40 p-5 text-sm text-amber">Fixture unavailable.</p></Shell>;
  const item = fixture.data;
  return <Shell>
    <Link href="/fixtures" className="text-sm text-mint">← Back to fixtures</Link>
    <PageHeader eyebrow={`${item.sport} / fixture detail`} title={`${item.home} vs ${item.away}`}>
      <span className="rounded-full border border-line bg-panel px-4 py-2 text-xs text-slate-400">{item.provider} · {item.freshness}</span>
    </PageHeader>
    <section className="grid gap-4 md:grid-cols-4">
      <Info label="Competition" value={item.competition || "Unavailable"} />
      <Info label="Status" value={item.status_detail || item.status} />
      <Info label="Score" value={`${item.home_score ?? "—"} – ${item.away_score ?? "—"}`} />
      <Info label="Observation age" value={item.data_age_seconds == null ? "Unknown" : `${item.data_age_seconds}s`} />
    </section>
    <section className="mt-8 rounded-2xl border border-line bg-panel/80 p-5">
      <div className="flex flex-wrap gap-2 border-b border-line pb-4">{detailKinds.map(kind => <button key={kind.key} onClick={() => setActiveKind(kind.key)} className={`rounded-lg px-4 py-2 text-sm ${activeKind === kind.key ? "bg-mint text-ink" : "text-slate-400 hover:bg-white/5"}`}>{kind.label}</button>)}</div>
      {detail.isPending ? <p className="pt-5 text-sm text-slate-500">Loading provider detail…</p> : detail.isError ? <p className="pt-5 text-sm text-amber">Provider detail unavailable.</p> : <DetailState detail={detail.data} />}
    </section>
  </Shell>;
}

function useStateKind() {
  const [kind, setKind] = useState<(typeof detailKinds)[number]["key"]>("stats");
  return [kind, setKind] as const;
}

function Info({ label, value }: { label: string; value: string }) { return <div className="rounded-xl border border-line bg-panel/70 p-4"><p className="text-xs uppercase tracking-[.15em] text-slate-500">{label}</p><p className="mt-3 text-sm font-medium text-white">{value}</p></div>; }

function DetailState({ detail }: { detail: { available: boolean; availability: string; data: unknown; stale: boolean; message: string | null } }) {
  if (!detail.available) return <p className="pt-5 text-sm text-slate-500">{detail.message || "This detail is not available from the current provider."}</p>;
  return <pre className="mt-5 max-h-[32rem] overflow-auto rounded-xl bg-ink p-4 text-xs leading-5 text-slate-300">{JSON.stringify(detail.data, null, 2)}</pre>;
}
