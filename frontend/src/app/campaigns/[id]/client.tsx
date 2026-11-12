"use client";

import { PayPalOneTimePaymentButton, PayPalProvider } from "@paypal/react-paypal-js/sdk-v6";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Info, UpdateCard } from "@/components/update-card";
import { Button, Card, ErrorText, inputClass, Page } from "@/components/ui";
import { api, API_URL } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { money, type Donation, type Timeline } from "@/lib/contracts";

const PAYPAL_CLIENT_ID = process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID ?? "";

export default function CampaignPage() {
  const { id } = useParams<{ id: string }>();
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Timeline>(`/api/campaigns/${id}/timeline`).then(setTimeline).catch((e) => setError(e.message));
  }, [id]);
  useEffect(load, [load]);

  if (!timeline) return <Page>{error ? <ErrorText error={error} /> : <p>Loading…</p>}</Page>;
  const c = timeline.campaign;
  const pct = Math.min(100, Math.round((c.donations_received_cents / c.target_amount_cents) * 100));

  return (
    <Page>
      <p className="text-sm uppercase tracking-wide text-stone-500">{c.ngo_name}</p>
      <h1 className="mt-1 text-3xl font-semibold">{c.title}</h1>
      <p className="mt-3 max-w-3xl whitespace-pre-line text-stone-700">{c.description}</p>

      <div className="mt-6 grid gap-4 md:grid-cols-3">
        <Card className="md:col-span-2">
          <div className="flex items-baseline justify-between">
            <p className="text-2xl font-semibold">{money(c.donations_received_cents, c.currency)}</p>
            <p className="text-sm text-stone-500">of {money(c.target_amount_cents, c.currency)} goal · {c.donor_count} {c.donor_count === 1 ? "donor" : "donors"}</p>
          </div>
          <div className="mt-2 h-2 rounded-full bg-stone-100">
            <div className="h-2 rounded-full bg-emerald-600" style={{ width: `${pct}%` }} />
          </div>
          <dl className="mt-5 grid grid-cols-1 gap-4 text-sm sm:grid-cols-3">
            <Tile
              label="Donations received"
              value={money(c.donations_received_cents, c.currency)}
              caption="Confirmed by PayPal"
              info="Counted only after PayPal confirms the payment."
            />
            <Tile
              label="Reported spending"
              value={money(c.reported_expenses_cents, c.currency)}
              caption="Reported by the organization"
              info="What the organization says it has spent, from any funds. It is their statement, not an audited account balance."
            />
            <Tile
              label="Matched by receipts"
              value={money(c.document_supported_cents, c.currency)}
              caption="Receipts agree with the report"
              info="The part of reported spending that reviewed receipts support. A matching receipt shows a purchase, not that items reached people."
            />
          </dl>
          {c.reported_expenses_cents > c.donations_received_cents && (
            <p className="mt-4 rounded-lg bg-stone-50 p-3 text-xs text-stone-600">
              Reported spending can include the organization&apos;s other funds. Donations received is only what came through NGOLog.
            </p>
          )}
        </Card>
        <DonateBox campaignId={c.id} onDonated={load} />
      </div>

      <h2 className="mt-10 text-xl font-semibold">Updates from the organization</h2>
      {timeline.reporting_overdue && (
        <p className="mt-2 rounded-lg bg-stone-100 p-3 text-sm text-stone-700">No recent update has been provided.</p>
      )}
      {timeline.entries.length === 0 && !timeline.reporting_overdue && (
        <p className="mt-2 text-stone-500">No updates yet. Each update appears here after the organization reviews and approves it.</p>
      )}
      <ol className="mt-4 space-y-4">
        {timeline.entries.map(({ update, provenance, photos }) => (
          <li key={update.id}>
            <Card>
              <UpdateCard update={update} items={provenance} photos={photos} apiUrl={API_URL} />
            </Card>
          </li>
        ))}
      </ol>
      <Limitations items={timeline.limitations} />
    </Page>
  );
}

// Like the small print at the bottom of a site: always there, opened on request.
function Limitations({ items }: { items: string[] }) {
  const [open, setOpen] = useState(false);
  if (items.length === 0) return null;
  return (
    <footer className="mt-12 border-t border-stone-200 pt-4 text-xs text-stone-500">
      <p>
        Updates are the organization&apos;s own reports, checked against the documents it shared.{" "}
        <button type="button" className="underline" aria-expanded={open} onClick={() => setOpen(!open)}>
          Limitations
        </button>
      </p>
      {open && (
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {items.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      )}
    </footer>
  );
}

function Tile({ label, value, caption, info }: { label: string; value: string; caption: string; info: string }) {
  return (
    <div>
      <dt className="text-stone-500">
        {label}
        <Info text={info} />
      </dt>
      <dd className="text-lg font-semibold">{value}</dd>
      <dd className="text-xs text-stone-500">{caption}</dd>
    </div>
  );
}

function DonateBox({ campaignId, onDonated }: { campaignId: string; onDonated: () => void }) {
  const { user } = useAuth();
  const [amount, setAmount] = useState("25");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Donation | null>(null);

  return (
    <Card>
      <h2 className="font-semibold">Donate</h2>
      {!PAYPAL_CLIENT_ID ? (
        <p className="mt-2 text-sm text-amber-800">PayPal sandbox is not configured (set NEXT_PUBLIC_PAYPAL_CLIENT_ID).</p>
      ) : user?.role !== "donor" ? (
        <p className="mt-2 text-sm text-stone-600">
          <Link href="/signin" className="text-emerald-800 underline">Sign in as a donor</Link> to give through PayPal sandbox.
        </p>
      ) : done ? (
        <div className="mt-2 space-y-3 text-sm">
          <p className="text-emerald-800">
            Thank you! PayPal confirmed your {money(done.amount_cents, done.currency)} donation.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              onClick={() => {
                setDone(null);
                setError(null);
              }}
            >
              Donate again
            </Button>
            <Link href="/donor/dashboard" className="self-center text-emerald-800 underline">My donations</Link>
          </div>
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          <label className="block text-sm">
            Amount (USD)
            <input className={inputClass} type="number" min={1} max={10000} step="1" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
          <PayPalProvider clientId={PAYPAL_CLIENT_ID} environment="sandbox" components={["paypal-payments"]} pageType="checkout">
            <PayPalOneTimePaymentButton
              type="donate"
              createOrder={async () => {
                setError(null);
                const res = await api<{ paypal_order_id: string }>(`/api/campaigns/${campaignId}/paypal/orders`, { method: "POST", json: { amount: Number(amount) } });
                return { orderId: res.paypal_order_id };
              }}
              onApprove={async ({ orderId }) => {
                // Only the server's capture result counts as a donation.
                const donation = await api<Donation>(`/api/paypal/orders/${orderId}/capture`, { method: "POST" });
                setDone(donation);
                onDonated();
              }}
              onCancel={() => setError("Payment cancelled. No money was taken.")}
              onError={(e) => setError(`PayPal error: ${String((e as Error)?.message ?? e)}`)}
            />
          </PayPalProvider>
          <ErrorText error={error} />
          <p className="text-xs text-stone-500">Sandbox payment. Your gift goes to the campaign; NGOLog never holds the money.</p>
        </div>
      )}
    </Card>
  );
}
