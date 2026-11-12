"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Button, Card, ErrorText, inputClass, Page } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { money, type Campaign, type ReportingRequest } from "@/lib/contracts";

export default function NgoDashboard() {
  const { user, ready } = useAuth();
  const [hasNgo, setHasNgo] = useState<boolean | null>(null);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [waiting, setWaiting] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    try {
      await api("/api/ngos/me");
      setHasNgo(true);
      const list = await api<Campaign[]>("/api/campaigns?mine=true");
      setCampaigns(list);
      const latest = await Promise.all(list.map((c) => api<ReportingRequest[]>(`/api/campaigns/${c.id}/reporting-requests`).then((rs) => [c.id, rs[0]] as const).catch(() => [c.id, undefined] as const)));
      const funded = new Set(list.filter((c) => c.donations_received_cents > 0).map((c) => c.id));
      setWaiting(Object.fromEntries(latest.map(([id, r]) => [id, funded.has(id) && (r?.status === "open" || r?.status === "overdue")])));
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) setHasNgo(false);
      else setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    if (user?.role !== "ngo_admin") return;
    let alive = true;
    Promise.resolve().then(() => {
      if (alive) void load();
    });
    return () => {
      alive = false;
    };
  }, [user, load]);

  if (ready && user?.role !== "ngo_admin") return <Page><Link href="/signin" className="underline">Sign in as an NGO admin</Link>.</Page>;
  if (hasNgo === false) return <Page><CreateNgo onCreated={load} /></Page>;
  if (hasNgo === null) return <Page>{error ? <ErrorText error={error} /> : <p className="text-stone-500">Loading…</p>}</Page>;

  return (
    <Page>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Your campaigns</h1>
        <Link href="/ngo/campaigns/new"><Button>New campaign</Button></Link>
      </div>
      <ErrorText error={error} />
      <div className="mt-6 space-y-3">
        {campaigns.length === 0 && <p className="text-stone-500">No campaigns yet.</p>}
        {campaigns.map((c) => (
          <Card key={c.id} className="flex flex-wrap items-center gap-4">
            <div className="flex-1">
              <p className="font-semibold">
                {c.title}
                {waiting[c.id] && <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 align-middle text-xs font-medium text-amber-900">Waiting for your reply</span>}
              </p>
              <p className="text-sm text-stone-600">
                {c.status} · {money(c.donations_received_cents, c.currency)} received · {money(c.reported_expenses_cents, c.currency)} reported spent
                {c.next_followup_at && ` · next update due ${new Date(c.next_followup_at + "Z").toLocaleDateString()}`}
              </p>
            </div>
            <Link href={`/campaigns/${c.id}`} className="text-sm text-emerald-800 hover:underline">Public page</Link>
            <Link href={`/ngo/campaigns/${c.id}/reporting`} className="text-sm text-emerald-800 hover:underline">{waiting[c.id] ? "Reply now" : "Reporting"}</Link>
            <Link href={`/ngo/campaigns/${c.id}/updates`} className="text-sm text-emerald-800 hover:underline">Donor updates</Link>
          </Card>
        ))}
      </div>
    </Page>
  );
}

function CreateNgo({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [agree, setAgree] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Card className="mx-auto max-w-lg">
      <h1 className="text-xl font-semibold">Set up your organization</h1>
      <form
        className="mt-4 space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api("/api/ngos", { method: "POST", json: { name, description, accept_reporting_agreement: agree } });
            onCreated();
          } catch (err) {
            setError((err as Error).message);
          }
        }}
      >
        <input className={inputClass} required placeholder="Organization name" value={name} onChange={(e) => setName(e.target.value)} />
        <textarea className={inputClass} placeholder="What you do" value={description} onChange={(e) => setDescription(e.target.value)} />
        <label className="flex gap-2 text-sm">
          <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
          <span>I agree to periodic AI follow-ups about campaign spending, evidence requests where appropriate, and a public &quot;overdue&quot; status if updates are not provided.</span>
        </label>
        <Button type="submit" disabled={!agree}>Create organization</Button>
        <ErrorText error={error} />
      </form>
    </Card>
  );
}
