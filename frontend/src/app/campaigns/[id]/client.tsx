"use client";

import { PayPalOneTimePaymentButton, PayPalProvider } from "@paypal/react-paypal-js/sdk-v6";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Card, ErrorText, inputClass, Page } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { money, STATUS_LABEL, type Donation, type EvidenceReviewStatus, type Timeline } from "@/lib/contracts";

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
          <h2 className="font-semibold">Money in and money reported</h2>
          <div className="mt-3 h-2 rounded-full bg-stone-100">
            <div className="h-2 rounded-full bg-emerald-600" style={{ width: `${pct}%` }} />
          </div>
          <dl className="mt-4 grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
            <Stat label="Donations received (PayPal)" value={money(c.donations_received_cents, c.currency)} sub={`${c.donor_count} donors · goal ${money(c.target_amount_cents, c.currency)}`} />
            <Stat label="Spending reported by NGO" value={money(c.reported_expenses_cents, c.currency)} sub="NGO statement" />
            <Stat label="Matched by reviewed documents" value={money(c.document_supported_cents, c.currency)} sub="Consistent, not audited" />
          </dl>
          <p className="mt-4 text-xs text-stone-500">{timeline.totals_note}</p>
        </Card>
        <DonateBox campaignId={c.id} onDonated={load} />
      </div>

      <h2 className="mt-10 text-xl font-semibold">Transparency timeline</h2>
      {timeline.reporting_overdue && (
        <p className="mt-2 rounded-lg bg-stone-100 p-3 text-sm text-stone-700">No recent update has been provided.</p>
      )}
      {timeline.entries.length === 0 && <p className="mt-2 text-stone-500">No updates published yet. Updates appear after the organization reviews and approves them.</p>}
      <ol className="mt-4 space-y-4">
        {timeline.entries.map(({ update, provenance }) => (
          <li key={update.id}>
            <Card>
              <p className="text-xs text-stone-500">{update.published_at && new Date(update.published_at + "Z").toLocaleString()}</p>
              <h3 className="mt-1 font-semibold">{update.title}</h3>
              <ul className="mt-3 space-y-3 text-sm">
                {provenance.map((p, i) => (
                  <li key={i}>
                    <p>{String(p.text)}</p>
                    {p.evidence_status ? (
                      <p className="mt-1 text-xs text-stone-500">
                        Status: {STATUS_LABEL[p.evidence_status as EvidenceReviewStatus] ?? String(p.evidence_status)}
                        {Number(p.evidence_count) > 0 && ` · ${p.evidence_count} document(s) reviewed`}
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
              {update.evidence_refs.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2 text-xs">
                  {update.evidence_refs.map((ref) => (
                    <a key={ref} className="text-emerald-800 underline" href={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/evidence/${ref}/file`} target="_blank" rel="noreferrer">
                      View shared document
                    </a>
                  ))}
                </div>
              )}
              <p className="mt-3 text-xs text-stone-500">&quot;Consistent&quot; means the documents match the reported amounts. It is not an independent audit.</p>
            </Card>
          </li>
        ))}
      </ol>
    </Page>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div>
      <dt className="text-stone-500">{label}</dt>
      <dd className="text-lg font-semibold">{value}</dd>
      <dd className="text-xs text-stone-500">{sub}</dd>
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
        <p className="mt-2 text-sm text-emerald-800">
          Thank you! PayPal confirmed your {money(done.amount_cents, done.currency)} donation (capture {done.paypal_capture_id}). You&apos;ll see updates on this page and in{" "}
          <Link href="/donor/dashboard" className="underline">your dashboard</Link>.
        </p>
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
          <p className="text-xs text-stone-500">Sandbox only: use a PayPal sandbox buyer account. Donations go to the campaign; NGOLog does not hold or release funds.</p>
        </div>
      )}
    </Card>
  );
}
