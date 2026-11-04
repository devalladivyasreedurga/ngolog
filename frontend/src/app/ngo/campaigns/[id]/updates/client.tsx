"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Button, Card, ErrorText, Page } from "@/components/ui";
import { api } from "@/lib/api";
import { STATUS_LABEL, type EvidenceReviewStatus, type ReportingRequest, type TimelineEntry } from "@/lib/contracts";

export default function Updates() {
  const { id } = useParams<{ id: string }>();
  const [entries, setEntries] = useState<TimelineEntry[]>([]);
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

  return (
    <Page>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">Donor updates</h1>
        <span className="ml-auto" />
        <Link href={`/ngo/campaigns/${id}/reporting`} className="text-sm text-emerald-800 hover:underline">← Reporting</Link>
        <Button disabled={busy} onClick={() => act(() => api(`/api/campaigns/${id}/updates/draft`, { method: "POST", json: { reporting_request_id: latestRequest?.id ?? null } }))}>
          Generate draft from latest report
        </Button>
      </div>
      <p className="mt-2 text-sm text-stone-600">
        Drafts are written only from what you confirmed and what the documents show. Nothing reaches donors until you approve and publish it.
      </p>
      <ErrorText error={error} />
      <div className="mt-6 space-y-4">
        {entries.length === 0 && <p className="text-stone-500">No drafts yet.</p>}
        {entries.map(({ update, provenance }) => (
          <Card key={update.id}>
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="font-semibold">{update.title}</h2>
              <span className="rounded-full bg-stone-100 px-2.5 py-0.5 text-xs">{update.status}</span>
              <span className="ml-auto" />
              {update.status === "draft" && <Button disabled={busy} onClick={() => act(() => api(`/api/updates/${update.id}/approve`, { method: "POST" }))}>Approve</Button>}
              {update.status === "approved" && <Button disabled={busy} onClick={() => act(() => api(`/api/updates/${update.id}/publish`, { method: "POST" }))}>Publish to donors</Button>}
            </div>
            <ul className="mt-3 space-y-3 text-sm">
              {provenance.map((p, i) => (
                <li key={i} className="border-l-2 border-stone-200 pl-3">
                  <p>{String(p.text)}</p>
                  {p.evidence_status ? (
                    <p className="mt-1 text-xs text-stone-500">
                      Source: {String(p.claim_type)} claim · {STATUS_LABEL[p.evidence_status as EvidenceReviewStatus]} · {(p.evidence_ids as string[] | undefined)?.length ?? 0} document(s)
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-stone-500">{update.evidence_refs.length} shared document(s) will be linked for donors.</p>
          </Card>
        ))}
      </div>
    </Page>
  );
}
