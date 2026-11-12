"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, ErrorText, Page } from "@/components/ui";
import { api } from "@/lib/api";
import { money, type Campaign } from "@/lib/contracts";

export default function Home() {
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Campaign[]>("/api/campaigns").then(setCampaigns).catch((e) => setError(e.message));
  }, []);

  return (
    <Page>
      <h1 className="text-3xl font-semibold">Your donation shouldn&apos;t be the end of the story.</h1>
      <p className="mt-2 max-w-2xl text-stone-600">
        Give through PayPal, then follow what the organization reports doing with campaign funds, which documents
        were reviewed, and what is still being clarified.
      </p>
      <ErrorText error={error} />
      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        {campaigns?.length === 0 && <p className="text-stone-500">No published campaigns yet.</p>}
        {campaigns?.map((c) => {
          const pct = Math.min(100, Math.round((c.donations_received_cents / c.target_amount_cents) * 100));
          return (
            <Link key={c.id} href={`/campaigns/${c.id}`}>
              <Card className="h-full hover:border-emerald-700">
                <p className="text-xs uppercase tracking-wide text-stone-500">{c.ngo_name}</p>
                <h2 className="mt-1 text-lg font-semibold">{c.title}</h2>
                <p className="mt-2 line-clamp-2 text-sm text-stone-600">{c.description}</p>
                <div className="mt-4 h-2 rounded-full bg-stone-100">
                  <div className="h-2 rounded-full bg-coral-500" style={{ width: `${pct}%` }} />
                </div>
                <p className="mt-2 text-sm text-stone-700">
                  {money(c.donations_received_cents, c.currency)} of {money(c.target_amount_cents, c.currency)} raised
                </p>
              </Card>
            </Link>
          );
        })}
      </div>
    </Page>
  );
}
