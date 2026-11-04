"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, ErrorText, Page } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { money, type Donation, type NotificationItem } from "@/lib/contracts";

export default function DonorDashboard() {
  const { user, ready } = useAuth();
  const [donations, setDonations] = useState<Donation[]>([]);
  const [notes, setNotes] = useState<NotificationItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    Promise.all([api<Donation[]>("/api/donations/mine"), api<NotificationItem[]>("/api/notifications/mine")])
      .then(([d, n]) => {
        setDonations(d);
        setNotes(n);
      })
      .catch((e) => setError(e.message));
  }, [user]);

  if (ready && !user) return <Page><Link href="/signin" className="underline">Sign in</Link> to see your donations.</Page>;

  return (
    <Page>
      <h1 className="text-2xl font-semibold">My donations</h1>
      <ErrorText error={error} />
      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <Card>
          <h2 className="font-semibold">Donations</h2>
          {donations.length === 0 && <p className="mt-2 text-sm text-stone-500">No donations yet.</p>}
          <ul className="mt-3 divide-y divide-stone-100 text-sm">
            {donations.map((d) => (
              <li key={d.id} className="py-3">
                <Link href={`/campaigns/${d.campaign_id}`} className="font-medium text-emerald-800 hover:underline">{d.campaign_title}</Link>
                <p>{money(d.amount_cents, d.currency)} · {new Date(d.created_at + "Z").toLocaleDateString()}</p>
                <p className="text-xs text-stone-500">
                  PayPal capture {d.paypal_capture_id ?? "pending"} · {d.webhook_confirmed ? "confirmed by PayPal webhook" : "confirmed by PayPal capture; webhook pending"}
                </p>
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <h2 className="font-semibold">Updates from campaigns you support</h2>
          {notes.length === 0 && <p className="mt-2 text-sm text-stone-500">No updates yet.</p>}
          <ul className="mt-3 divide-y divide-stone-100 text-sm">
            {notes.map((n) => (
              <li key={n.id} className="py-3">
                <Link href={`/campaigns/${n.campaign_id}`} className="font-medium text-emerald-800 hover:underline">{n.title}</Link>
                <p className="text-xs text-stone-500">{new Date(n.created_at + "Z").toLocaleString()}</p>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </Page>
  );
}
