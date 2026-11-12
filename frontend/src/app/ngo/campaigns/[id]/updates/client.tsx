"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { UpdateCard } from "@/components/update-card";
import { Button, Card, ErrorText, Page } from "@/components/ui";
import { api, API_URL } from "@/lib/api";
import { DONOR_STATUS, type ReportingRequest, type TimelineEntry } from "@/lib/contracts";

export default function Updates() {
  const { id } = useParams<{ id: string }>();
  const [entries, setEntries] = useState<TimelineEntry[] | null>(null);
  const [latestRequest, setLatestRequest] = useState<ReportingRequest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [ups, reqs] = await Promise.all([
        api<TimelineEntry[]>(`/api/campaigns/${id}/updates`),
        api<ReportingRequest[]>(`/api/campaigns/${id}/reporting-requests`),
      ]);
      setEntries(ups);
      setLatestRequest(reqs[0] ?? null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);
  useEffect(() => {
    let alive = true;
    Promise.resolve().then(() => {
      if (alive) void load();
    });
    return () => {
      alive = false;
    };
  }, [load]);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // Publishing is one click for the NGO; the server still records an approval and then a publication.
  const publish = (entry: TimelineEntry) =>
    act(async () => {
      if (entry.update.status === "draft") await api(`/api/updates/${entry.update.id}/approve`, { method: "POST" });
      await api(`/api/updates/${entry.update.id}/publish`, { method: "POST" });
    });

  const live = (entries ?? []).filter((e) => e.update.status !== "withdrawn");
  const pending = live.find((e) => e.update.status === "draft" || e.update.status === "approved");
  const published = live.filter((e) => e.update.status === "published");

  return (
    <Page>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">Donor update</h1>
        <span className="ml-auto" />
        <Link href={`/ngo/campaigns/${id}/reporting`} className="text-sm text-emerald-800 hover:underline">← Back to reporting</Link>
      </div>
      <ErrorText error={error} />
      {entries === null && !error && <p className="mt-4 text-stone-500">Loading…</p>}

      {entries !== null && !pending && (
        <Card className="mt-6">
          <p className="font-medium">No draft waiting</p>
          <p className="mt-1 text-sm text-stone-600">
            A draft appears here by itself once you have reported spending and the receipts are reviewed.
          </p>
          <Button
            className="mt-3"
            variant="secondary"
            disabled={busy}
            onClick={() => act(() => api(`/api/campaigns/${id}/updates/draft`, { method: "POST", json: { reporting_request_id: latestRequest?.id ?? null } }))}
          >
            Create a draft from my latest report
          </Button>
        </Card>
      )}

      {pending && (
        <div className="mt-6">
          <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
            Preview: this is exactly what donors will see. Nothing is shared until you publish.
          </p>
          <Card className="mt-3">
            <UpdateCard update={pending.update} items={pending.provenance} apiUrl={API_URL} showWording={false} />
          </Card>
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer text-emerald-800">How was this written?</summary>
            <ul className="mt-2 space-y-2 text-stone-700">
              {pending.provenance.map((p, i) => (
                <li key={i} className="border-l-2 border-stone-200 pl-3">
                  <p>{p.text}</p>
                  {p.evidence_status && (
                    <p className="mt-0.5 text-xs text-stone-500">
                      Built from your {p.claim_type} report · {DONOR_STATUS[p.evidence_status].label} · {p.evidence_ids?.length ?? 0} document(s)
                    </p>
                  )}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-stone-500">Only facts you confirmed and documents you uploaded are used. Nothing is added by the AI.</p>
          </details>
          <Button className="mt-4" disabled={busy} onClick={() => publish(pending)}>
            {busy ? "Publishing…" : "Publish to donors"}
          </Button>
        </div>
      )}

      {published.length > 0 && (
        <>
          <h2 className="mt-10 font-semibold">Already published</h2>
          <ol className="mt-3 space-y-3">
            {published.map((e) => (
              <li key={e.update.id}>
                <Card>
                  <UpdateCard update={e.update} items={e.provenance} apiUrl={API_URL} showWording={false} />
                </Card>
              </li>
            ))}
          </ol>
        </>
      )}
    </Page>
  );
}
