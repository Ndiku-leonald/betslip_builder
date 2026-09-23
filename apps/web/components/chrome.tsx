"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [{ href: "/", label: "Dashboard", icon: "D" }, { href: "/builder", label: "Slip builder", icon: "B" }, { href: "/live", label: "Live", icon: "L" }, { href: "/fixtures", label: "Fixtures", icon: "F" }, { href: "/value", label: "Value Finder", icon: "V" }, { href: "/sources", label: "Data sources", icon: "S" }];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return <div className="min-h-screen bg-ink grid-noise"><aside className="fixed inset-y-0 left-0 hidden w-64 border-r border-line bg-ink/90 p-6 lg:block"><div className="mb-12 flex items-center gap-3"><span className="grid h-9 w-9 place-items-center rounded-xl bg-mint text-ink font-black">S</span><span className="text-lg font-bold tracking-tight">Slip<span className="text-mint">IQ</span></span></div><nav className="space-y-2">{links.map(link => <Link key={link.href} href={link.href} className={`flex items-center gap-3 rounded-xl px-3 py-3 text-sm ${pathname === link.href ? "bg-white/10 text-mint" : "text-slate-400 hover:bg-white/5 hover:text-white"}`}><span className="grid h-6 w-6 place-items-center rounded-md border border-line text-[10px] font-semibold">{link.icon}</span>{link.label}</Link>)}</nav><div className="absolute bottom-6 left-6 right-6 rounded-2xl border border-line bg-panel p-4"><p className="text-[10px] uppercase tracking-[.2em] text-slate-500">Stage 3</p><p className="mt-2 text-sm text-slate-300">Market intelligence is separate from probability and confidence.</p></div></aside><main className="min-h-screen lg:pl-64"><div className="mx-auto max-w-7xl px-5 py-6 sm:px-8 lg:px-12"><nav className="mb-8 flex items-center justify-between gap-2 overflow-x-auto rounded-xl border border-line bg-panel/70 p-2 lg:hidden"><span className="px-2 font-bold tracking-tight text-white">Slip<span className="text-mint">IQ</span></span>{links.map(link => <Link key={link.href} href={link.href} className={`whitespace-nowrap rounded-lg px-3 py-2 text-xs ${pathname === link.href ? "bg-mint text-ink" : "text-slate-400"}`}>{link.label}</Link>)}</nav>{children}</div></main></div>;
}

export function PageHeader({ eyebrow, title, children }: { eyebrow: string; title: string; children?: React.ReactNode }) { return <header className="mb-8 flex flex-col justify-between gap-5 md:flex-row md:items-end"><div><p className="text-xs font-semibold uppercase tracking-[.24em] text-mint">{eyebrow}</p><h1 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">{title}</h1></div>{children}</header>; }
