"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Card, ErrorText, inputClass, Page, StatusBadge } from "@/components/ui";
import { api, API_URL, getToken } from "@/lib/api";
import { money, type Claim, type Evidence, type ReportingRequest, type Thread } from "@/lib/contracts";

const ROUND_STATUS: Record<string, string> = {
  open: "Waiting for your reply",
  in_review: "In progress",
  awaiting_approval: "Draft ready to review",
  completed: "Published",
  overdue: "No recent update",
  escalated: "With a reviewer",
};

type Action = { kind: string; label: string; claim_type?: string; claim_id?: string; amount?: number; href?: string };

async function uploadEvidence(requestId: string, claimType: string, claimId: string, file: File): Promise<Thread> {
  const form = new FormData();
  form.set("reporting_request_id", requestId);
  form.set("kind", claimType === "expense" ? "receipt" : "distribution_log");
  form.set("claim_type", claimType);
  form.set("claim_id", claimId);
  form.set("file", file);
  const res = await fetch(`${API_URL}/api/evidence/upload`, { method: "POST", body: form, headers: { Authorization: `Bearer ${getToken()}` } });
  if (!res.ok) throw new Error((await res.json()).detail ?? "Upload failed");
  return (await res.json()) as Thread;
}

export default function Reporting() {
  const { id } = useParams<{ id: string }>();
  const [requests, setRequests] = useState<ReportingRequest[]>([]);
  const [thread, setThread] = useState<Thread | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = useCallback(async (fn: () => Promise<Thread | void>) => {
    setBusy(true);
    setError(null);
    try {
      const t = await fn();
      if (t) setThread(t);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    api<ReportingRequest[]>(`/api/campaigns/${id}/reporting-requests`)
      .then((rs) => {
        setRequests(rs);
        if (rs[0]) run(() => api<Thread>(`/api/reporting-requests/${rs[0].id}/thread`));
      })
      .catch((e) => setError(e.message));
  }, [id, run]);

  const trigger = () => run(() => api<Thread>(`/api/campaigns/${id}/reporting-requests/trigger`, { method: "POST", json: {} }));

  return (
    <Page>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">Reporting</h1>
        <span className="text-stone-500">{thread?.campaign_title}</span>
        <span className="ml-auto" />
        <Link href={`/ngo/campaigns/${id}/updates`} className="text-sm text-emerald-800 hover:underline">Donor updates →</Link>
        <Button variant="secondary" onClick={trigger} disabled={busy}>Run follow-up now (demo)</Button>
      </div>
      <ErrorText error={error} />
      {requests.length > 1 && (
        <select className={`${inputClass} mt-3 max-w-xs`} onChange={(e) => run(() => api<Thread>(`/api/reporting-requests/${e.target.value}/thread`))}>
          {requests.map((r, i) => (
            <option key={r.id} value={r.id}>
              Update {requests.length - i} · {new Date(r.created_at + "Z").toLocaleDateString()} · {ROUND_STATUS[r.status] ?? r.status}
            </option>
          ))}
        </select>
      )}
      {!thread ? (
        <p className="mt-6 text-stone-500">No reporting request yet. The assistant opens one on your update schedule, or run one now.</p>
      ) : (
        <div className="mt-6 grid gap-4 lg:grid-cols-5">
          <Conversation thread={thread} busy={busy} run={run} />
          <div className="space-y-4 lg:col-span-2">
            <Claims thread={thread} busy={busy} run={run} />
            <EvidenceList thread={thread} busy={busy} run={run} />
          </div>
        </div>
      )}
    </Page>
  );
}

type Run = (fn: () => Promise<Thread | void>) => Promise<void>;

function Conversation({ thread, busy, run }: { thread: Thread; busy: boolean; run: Run }) {
  const [text, setText] = useState("");
  const closed = thread.request.status === "completed";
  const listRef = useRef<HTMLOListElement>(null);
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [thread.messages.length]);
  return (
    <Card className="lg:col-span-3">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">Conversation with the accountability assistant</h2>
        <span className="text-xs text-stone-500">{ROUND_STATUS[thread.request.status] ?? thread.request.status}</span>
      </div>
      <ol ref={listRef} className="mt-4 max-h-[28rem] space-y-3 overflow-y-auto">
        {thread.messages.map((m) => (
          <li key={m.id} className={`rounded-lg px-3 py-2 text-sm whitespace-pre-line ${m.sender_role === "ngo" ? "ml-8 bg-emerald-50" : "mr-8 bg-stone-100"}`}>
            <p className="mb-1 text-xs font-medium text-stone-500">{m.sender_role === "ngo" ? "You" : "Assistant"}</p>
            {m.content}
          </li>
        ))}
      </ol>
      {!closed && <QuickReplies thread={thread} busy={busy} run={run} />}
      {!closed && (
        <form
          className="mt-3 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const content = text;
            setText("");
            run(() => api<Thread>(`/api/reporting-requests/${thread.request.id}/messages`, { method: "POST", json: { content } }));
          }}
        >
          <input className={inputClass} placeholder="Type your reply…" value={text} onChange={(e) => setText(e.target.value)} />
          <Button type="submit" disabled={busy || !text.trim()}>Send</Button>
        </form>
      )}
      {!closed && (
        <div className="mt-2 flex flex-wrap gap-2 text-xs">
          {[
            ["+ Add another expense", "We also bought "],
            ["+ Add what was handed out", "We handed out "],
          ].map(([label, starter]) => (
            <button key={label} type="button" className="rounded-full bg-stone-100 px-3 py-1 text-stone-700 hover:bg-stone-200" onClick={() => setText(starter)}>
              {label}
            </button>
          ))}
        </div>
      )}
      {thread.investigations.some((i) => i.status === "open" || i.status === "escalated") && (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <p className="font-medium">Open questions</p>
          {thread.investigations.filter((i) => i.status === "open" || i.status === "escalated").map((i) => <p key={i.id} className="mt-1">{i.question}{i.status === "escalated" && " (sent to a reviewer)"}</p>)}
        </div>
      )}
    </Card>
  );
}

function QuickReplies({ thread, busy, run }: { thread: Thread; busy: boolean; run: Run }) {
  const last = thread.messages[thread.messages.length - 1];
  const actions = ((last?.sender_role === "agent" ? last.meta.actions : undefined) as Action[] | undefined) ?? [];
  if (actions.length === 0) return null;
  const rid = thread.request.id;
  const chip = "rounded-full border border-emerald-700 px-3.5 py-1.5 text-sm font-medium text-emerald-800 hover:bg-emerald-50 disabled:opacity-50";

  function go(a: Action): Promise<Thread> {
    switch (a.kind) {
      case "confirm_all":
        return api<Thread>(`/api/reporting-requests/${rid}/claims/confirm`, { method: "POST" });
      case "reject_all":
        return api<Thread>(`/api/reporting-requests/${rid}/claims/reject`, { method: "POST" });
      case "no_evidence":
        return api<Thread>(`/api/claims/${a.claim_type}/${a.claim_id}/no-evidence`, { method: "POST", json: { explanation: "I don't have one." } });
      case "set_amount":
        return api<Thread>(`/api/claims/expense/${a.claim_id}/confirm`, { method: "POST", json: { amount: a.amount } });
      default:
        return api<Thread>(`/api/reporting-requests/${rid}/messages`, { method: "POST", json: { content: "Skip" } });
    }
  }

  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {actions.map((a) =>
        a.kind === "upload" ? (
          <label key={a.label} className={`${chip} cursor-pointer ${busy ? "pointer-events-none opacity-50" : ""}`}>
            {a.label}
            <input
              type="file"
              className="hidden"
              accept="image/jpeg,image/png,image/webp,application/pdf"
              disabled={busy}
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) run(() => uploadEvidence(rid, a.claim_type!, a.claim_id!, file));
              }}
            />
          </label>
        ) : a.kind === "link" ? (
          <Link key={a.label} href={`/ngo/campaigns/${thread.campaign_id}/${a.href}`} className={chip}>
            {a.label}
          </Link>
        ) : (
          <button key={a.label} className={chip} disabled={busy} onClick={() => run(() => go(a))}>
            {a.label}
          </button>
        ),
      )}
    </div>
  );
}

function Claims({ thread, busy, run }: { thread: Thread; busy: boolean; run: Run }) {
  const [manual, setManual] = useState({ description: "", amount: "" });
  const [activity, setActivity] = useState({ description: "", quantity: "", unit: "" });
  const live = thread.claims.filter((c) => c.status !== "withdrawn");
  return (
    <Card>
      <h2 className="font-semibold">What you reported</h2>
      <p className="mt-0.5 text-xs text-stone-500">Use the buttons in the chat to confirm or add receipts.</p>
      {live.length === 0 && <p className="mt-2 text-sm text-stone-500">Nothing yet.</p>}
      <ul className="mt-3 space-y-3">
        {live.map((c) => <ClaimRow key={c.id} claim={c} />)}
      </ul>
      <details className="mt-4 border-t border-stone-100 pt-3">
      <summary className="cursor-pointer text-sm text-emerald-800">Add manually</summary>
      <form
        className="mt-3 flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          run(() => api<Thread>(`/api/reporting-requests/${thread.request.id}/claims`, { method: "POST", json: { claim_type: "expense", description: manual.description, amount: Number(manual.amount) } }));
          setManual({ description: "", amount: "" });
        }}
      >
        <input className={`${inputClass} flex-1`} required placeholder="Expense, e.g. 25 school kits" value={manual.description} onChange={(e) => setManual({ ...manual, description: e.target.value })} />
        <input className={`${inputClass} w-24`} required type="number" min="0.01" step="0.01" placeholder="$" value={manual.amount} onChange={(e) => setManual({ ...manual, amount: e.target.value })} />
        <Button type="submit" variant="secondary" disabled={busy}>Add</Button>
      </form>
      <form
        className="mt-2 flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const quantity = activity.quantity ? Number(activity.quantity) : null;
          run(() => api<Thread>(`/api/reporting-requests/${thread.request.id}/claims`, { method: "POST", json: { claim_type: "impact", description: activity.description, quantity, unit: activity.unit || null } }));
          setActivity({ description: "", quantity: "", unit: "" });
        }}
      >
        <input className={`${inputClass} flex-1`} required placeholder="Activity, e.g. kits handed out" value={activity.description} onChange={(e) => setActivity({ ...activity, description: e.target.value })} />
        <input className={`${inputClass} w-20`} type="number" min="0" placeholder="Qty" value={activity.quantity} onChange={(e) => setActivity({ ...activity, quantity: e.target.value })} />
        <input className={`${inputClass} w-20`} placeholder="Unit" value={activity.unit} onChange={(e) => setActivity({ ...activity, unit: e.target.value })} />
        <Button type="submit" variant="secondary" disabled={busy}>Add</Button>
      </form>
      </details>
    </Card>
  );
}

function ClaimRow({ claim }: { claim: Claim }) {
  return (
    <li className="rounded-lg border border-stone-200 p-3 text-sm">
      <p className="font-medium">{claim.description}</p>
      {claim.claim_type === "expense" ? (
        <p className="text-stone-600">
          Reported {money(claim.amount_cents, claim.currency ?? "USD")} · receipts match {money(claim.supported_amount_cents, claim.currency ?? "USD")}
        </p>
      ) : (
        <p className="text-stone-600">{claim.quantity != null && `${claim.quantity} ${claim.unit ?? ""}`}</p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <StatusBadge status={claim.evidence_status} />
        {claim.status === "proposed" && <span className="text-xs text-amber-800">Waiting for your OK in the chat</span>}
      </div>
    </li>
  );
}

function EvidenceList({ thread, busy, run }: { thread: Thread; busy: boolean; run: Run }) {
  if (thread.evidence.length === 0) return null;
  return (
    <Card>
      <h2 className="font-semibold">Documents</h2>
      <ul className="mt-3 space-y-3">
        {thread.evidence.map((ev) => <EvidenceRow key={ev.id} ev={ev} busy={busy} run={run} />)}
      </ul>
      <p className="mt-3 text-xs text-stone-500">Documents are private unless you share them with donors.</p>
    </Card>
  );
}

function EvidenceRow({ ev, busy, run }: { ev: Evidence; busy: boolean; run: Run }) {
  const values = { ...(ev.extracted ?? {}), ...(ev.confirmed ?? {}) } as { total?: number; merchant?: string; receipt_number?: string };
  const [total, setTotal] = useState(values.total != null ? String(values.total) : "");
  return (
    <li className="rounded-lg border border-stone-200 p-3 text-sm">
      <p className="font-medium">{ev.original_filename}</p>
      <p className="text-stone-600">
        {values.merchant && `${values.merchant} · `}
        {values.total != null ? `total ${money(Math.round(values.total * 100))}` : "total not read"}
        {ev.confirmed ? " (you confirmed)" : ev.extracted ? " (read by AI)" : ""}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input className={`${inputClass} w-28`} type="number" step="0.01" placeholder="Total" value={total} onChange={(e) => setTotal(e.target.value)} aria-label="Receipt total" />
        <Button variant="secondary" disabled={busy || !total} onClick={() => run(() => api<Thread>(`/api/evidence/${ev.id}/confirm-values`, { method: "POST", json: { total: Number(total) } }))}>
          {ev.confirmed ? "Correct total" : "Confirm total"}
        </Button>
        <label className="flex items-center gap-1 text-xs">
          <input
            type="checkbox"
            checked={ev.visibility === "public"}
            disabled={busy}
            onChange={(e) =>
              run(async () => {
                await api(`/api/evidence/${ev.id}/visibility`, { method: "POST", json: { visibility: e.target.checked ? "public" : "private" } });
              }).then(() => window.location.reload())
            }
          />
          Share with donors
        </label>
      </div>
    </li>
  );
}
