"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, ErrorText, Page } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { money, type Donation, type Timeline } from "@/lib/contracts";

interface Supported {
  timeline: Timeline;
  donations: Donation[];
}

export default function DonorDashboard() {
  const { user, ready } = useAuth();
  const [board, setBoard] = useState<Supported[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user?.role !== "donor") return;
    let alive = true;
    (async () => {
      try {
        const donations = await api<Donation[]>("/api/donations/mine");
        const byCampaign = new Map<string, Donation[]>();
        for (const d of donations) byCampaign.set(d.campaign_id, [...(byCampaign.get(d.campaign_id) ?? []), d]);
        const cards = await Promise.all(
          [...byCampaign.entries()].map(async ([id, ds]) => ({ timeline: await api<Timeline>(`/api/campaigns/${id}/timeline`), donations: ds })),
        );
        if (alive) setBoard(cards);
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    })();
    return () => {
      alive = false;
    };
  }, [user]);

  if (ready && user?.role !== "donor") return <Page><Link href="/signin" className="underline">Sign in as a donor</Link> to see the campaigns you support.</Page>;

  return (
    <Page>
      <h1 className="text-2xl font-semibold">Campaigns you support</h1>
      <ErrorText error={error} />
      {board === null && !error && <p className="mt-4 text-stone-500">Loading…</p>}
      {board?.length === 0 && (
        <p className="mt-4 text-stone-600">
          You haven&apos;t donated yet. <Link href="/" className="text-emerald-800 underline">Browse campaigns</Link>.
        </p>
      )}
      <div className="mt-6 grid gap-4 md:grid-cols-2">
        {board?.map(({ timeline, donations }) => <CampaignCard key={timeline.campaign.id} timeline={timeline} donations={donations} />)}
      </div>
    </Page>
  );
}

function CampaignCard({ timeline, donations }: Supported) {
  const c = timeline.campaign;
  const pct = Math.min(100, Math.round((c.donations_received_cents / c.target_amount_cents) * 100));
  const given = donations.reduce((sum, d) => sum + d.amount_cents, 0);
  const latest = timeline.entries[0];
  const spent = latest?.provenance.filter((p) => p.claim_type === "expense" && p.amount_cents != null) ?? [];
  const reported = spent.reduce((s, p) => s + (p.amount_cents ?? 0), 0);
  const matched = spent.reduce((s, p) => s + (p.supported_cents ?? 0), 0);

  return (
    <Card className="flex flex-col">
      <p className="text-xs uppercase tracking-wide text-stone-500">{c.ngo_name}</p>
      <h2 className="mt-1 text-lg font-semibold">{c.title}</h2>
      <div className="mt-3 h-2 rounded-full bg-stone-100">
        <div className="h-2 rounded-full bg-emerald-600" style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-1 text-xs text-stone-500">{money(c.donations_received_cents, c.currency)} of {money(c.target_amount_cents, c.currency)} raised</p>

      <div className="mt-4 rounded-lg bg-emerald-50 p-3 text-sm">
        <p className="font-medium text-emerald-900">You gave {money(given, c.currency)}</p>
        <ul className="mt-1 text-xs text-emerald-900/80">
          {donations.map((d) => (
            <li key={d.id}>
              {money(d.amount_cents, d.currency)} · {new Date(d.created_at + "Z").toLocaleDateString()} · {d.webhook_confirmed ? "confirmed by PayPal" : "payment recorded"}
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-4 text-sm">
        <p className="text-xs font-medium uppercase tracking-wide text-stone-500">Latest update</p>
        {timeline.reporting_overdue && <p className="mt-1 text-stone-600">No recent update has been provided.</p>}
        {latest ? (
          <p className="mt-1">
            <span className="text-stone-500">{new Date((latest.update.published_at ?? latest.update.created_at) + "Z").toLocaleDateString()}</span>
            {spent.length > 0 ? (
              <>
                {" · "}Reported {money(reported, c.currency)}, receipts match {money(matched, c.currency)}
              </>
            ) : (
              <> · {latest.update.title}</>
            )}
          </p>
        ) : (
          !timeline.reporting_overdue && <p className="mt-1 text-stone-500">Nothing published yet.</p>
        )}
      </div>

      <Link href={`/campaigns/${c.id}`} className="mt-4 self-start text-sm font-medium text-emerald-800 hover:underline">
        View campaign and all updates →
      </Link>
    </Card>
  );
}
