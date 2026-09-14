"use client";
import { useQuery } from "@tanstack/react-query";
import { Shell, PageHeader } from "@/components/chrome";
import { FixtureCard } from "@/components/fixture-card";
import { api } from "@/lib/api";

export default function FixturesPage() { const query = useQuery({ queryKey: ["fixtures"], queryFn: () => api.fixtures("/api/fixtures?limit=100") }); return <Shell><PageHeader eyebrow="Fixtures / normalized feed" title="All available fixtures."><span className="text-xs text-slate-500">Canonical IDs · provider timestamps · freshness</span></PageHeader>{query.isPending ? <p className="text-sm text-slate-500">Loading…</p> : query.isError ? <p className="rounded-xl border border-amber/40 p-5 text-sm text-amber">Fixture feed unavailable.</p> : query.data?.length ? <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{query.data.map(f => <FixtureCard key={f.id} fixture={f}/>)}</div> : <p className="rounded-2xl border border-dashed border-line p-10 text-sm text-slate-500">No normalized fixtures are stored yet. Run an explicit ingestion job with a configured provider.</p>}</Shell>; }

