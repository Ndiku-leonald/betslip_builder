"use client";
import { useQuery } from "@tanstack/react-query";
import { Shell, PageHeader } from "@/components/chrome";
import { api } from "@/lib/api";

export default function ModelsPage() {
  const models = useQuery({ queryKey: ["models"], queryFn: api.models });
  const backtests = useQuery({ queryKey: ["backtests"], queryFn: api.backtests });
  return <Shell><PageHeader eyebrow="research / model registry" title="Model performance"><p className="max-w-2xl text-sm text-slate-400">Review statistical candidates and walk-forward evaluation. Metrics shown here are only meaningful when trained on genuine historical data.</p></PageHeader><section className="space-y-3">{models.isPending ? <p className="text-sm text-slate-500">Loading models…</p> : models.data?.length ? models.data.map(model => <article key={model.id} className="rounded-2xl border border-line bg-panel/80 p-5"><div className="flex flex-wrap justify-between gap-3"><div><p className="text-xs uppercase tracking-[.15em] text-mint">{model.sport || "unknown"} · {model.status}</p><h2 className="mt-2 text-lg text-white">{model.name}</h2><p className="mt-1 text-xs text-slate-500">{model.version} · {model.sample_count ?? 0} samples</p></div><div className="text-right text-xs text-slate-400">Brier {model.metrics?.calibrated_brier?.toFixed?.(4) ?? "—"}<br />Log loss {model.metrics?.calibrated_log_loss?.toFixed?.(4) ?? "—"}</div></div></article>) : <p className="rounded-2xl border border-line p-5 text-sm text-slate-500">No trained production model available.</p>}</section><section className="mt-8"><h2 className="text-lg text-white">Backtests</h2>{backtests.data?.length ? <p className="mt-3 text-sm text-slate-400">{backtests.data.length} persisted walk-forward run(s).</p> : <p className="mt-3 text-sm text-slate-500">No persisted backtests yet.</p>}</section></Shell>;
}
