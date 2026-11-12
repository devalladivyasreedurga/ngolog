"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Card, ErrorText, inputClass, Page, StatusBadge } from "@/components/ui";
import { api, API_URL, getToken } from "@/lib/api";
import { money, type Campaign, type Claim, type Evidence, type ReportingRequest, type Thread } from "@/lib/contracts";

const ROUND_STATUS: Record<string, string> = {
  open: "Waiting for your reply",
  in_review: "In progress",
  awaiting_approval: "Draft ready to review",
  completed: "Published",
  overdue: "No recent update",
  escalated: "With a reviewer",
};

const PILL: Record<string, string> = {
  open: "bg-amber-100 text-amber-900",
  in_review: "bg-stone-100 text-stone-700",
  awaiting_approval: "bg-amber-100 text-amber-900",
  completed: "bg-emerald-100 text-emerald-900",
  overdue: "bg-stone-100 text-stone-700",
  escalated: "bg-amber-100 text-amber-900",
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
  const [funded, setFunded] = useState<boolean | null>(null);
  const [title, setTitle] = useState<string | null>(null);

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
    api<Campaign>(`/api/campaigns/${id}`)
      .then((c) => {
        setFunded(c.donations_received_cents > 0);
        setTitle(c.title);
      })
      .catch(() => setFunded(true));
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
      <Link href="/ngo/dashboard" className="text-sm text-emerald-800 hover:underline">← Your campaigns</Link>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">{title ?? thread?.campaign_title ?? "Spending updates"}</h1>
        {thread && funded !== false && (
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${PILL[thread.request.status] ?? "bg-stone-100 text-stone-700"}`}>
            {ROUND_STATUS[thread.request.status] ?? thread.request.status}
          </span>
        )}
        <span className="ml-auto" />
        <Link href={`/ngo/campaigns/${id}/updates`} className="text-sm text-stone-600 hover:text-emerald-800 hover:underline">Donor updates →</Link>
        <Button variant="secondary" onClick={trigger} disabled={busy || funded === false} title={funded === false ? "Updates start after the first donation" : undefined}>Start an update</Button>
      </div>
      <p className="mt-0.5 text-sm text-stone-500">
        {thread && funded !== false ? `Spending update · started ${new Date(thread.request.created_at + "Z").toLocaleDateString(undefined, { month: "short", day: "numeric" })}` : "Spending updates"}
      </p>
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
      {!thread || funded === false ? (
        <p className="mt-6 max-w-xl text-stone-600">
          {funded === false
            ? "No donations yet, so there is nothing to report. The assistant starts asking for updates after the campaign receives its first donation."
            : "No update has started. The assistant opens one on your schedule, or you can start one now."}
        </p>
      ) : (
        <>
        <Steps thread={thread} />
        <div className="mt-4 grid gap-4 lg:grid-cols-5">
          <Conversation thread={thread} busy={busy} run={run} />
          <div className="space-y-4 lg:col-span-2">
            <Claims thread={thread} busy={busy} run={run} />
            <EvidenceList thread={thread} busy={busy} run={run} />
          </div>
        </div>
        </>
      )}
    </Page>
  );
}

const STEPS = ["Report", "Receipts", "Review", "Publish"];

// Where this update is: tell what you spent, back it with receipts, review the draft, publish it.
function Steps({ thread }: { thread: Thread }) {
  const status = thread.request.status;
  const reported = thread.claims.some((c) => c.status === "reported");
  const current = status === "completed" ? 5 : status === "awaiting_approval" ? 3 : reported ? 2 : 1;
  return (
    <ol className="mt-4 flex items-center gap-2 text-xs" aria-label="Progress">
      {STEPS.map((label, i) => {
        const n = i + 1;
        const done = n < current;
        const now = n === current;
        return (
          <li key={label} className="flex flex-1 items-center gap-2 last:flex-none" aria-current={now ? "step" : undefined}>
            <span
              className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[11px] ${
                done ? "border-emerald-600 bg-emerald-50 text-emerald-800" : now ? "border-emerald-700 bg-emerald-700 text-white" : "border-stone-300 text-stone-400"
              }`}
            >
              {done ? "✓" : n}
            </span>
            <span className={done ? "text-stone-600" : now ? "font-medium text-stone-900" : "text-stone-400"}>{label}</span>
            {n < STEPS.length && <span className="h-px flex-1 bg-stone-300" />}
          </li>
        );
      })}
    </ol>
  );
}

type Run = (fn: () => Promise<Thread | void>) => Promise<void>;

function Conversation({ thread, busy, run }: { thread: Thread; busy: boolean; run: Run }) {
  const [text, setText] = useState("");
  const [sent, setSent] = useState<{ text: string; at: number } | null>(null);
  // Shown only until the server's answer arrives (the message count then moves on).
  const pending = busy && sent && sent.at === thread.messages.length ? sent.text : null;
  const setPending = (text: string) => setSent({ text, at: thread.messages.length });
  // A reply that lands instantly feels robotic: hold it for a short "typing" moment.
  const chatRun: Run = async (fn) => {
    const started = Date.now();
    await run(async () => {
      const t = await fn();
      const wait = 800 - (Date.now() - started);
      if (wait > 0) await new Promise((r) => setTimeout(r, wait));
      return t;
    });
  };
  const closed = thread.request.status === "completed";
  const listRef = useRef<HTMLOListElement>(null);
  const [seen] = useState(thread.messages.length); // messages already on screen do not animate
  const lastMsg = thread.messages[thread.messages.length - 1];
  const lastAwaiting = lastMsg?.sender_role === "agent" ? lastMsg.meta.awaiting : undefined;
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [thread.messages.length, pending]);
  return (
    <Card className="lg:col-span-3">
      <ol ref={listRef} className="max-h-[28rem] space-y-3 overflow-y-auto">
        {thread.messages.map((m, i) => (
          <li key={m.id} className={`rounded-lg px-3 py-2 text-sm whitespace-pre-line ${i >= seen ? "msg-in" : ""} ${m.sender_role === "ngo" ? "ml-8 bg-emerald-50" : "mr-8 bg-stone-100"}`}>
            <p className="mb-1 text-xs font-medium text-stone-500">{m.sender_role === "ngo" ? "You" : "Assistant"}</p>
            {m.meta.evidence_id && m.sender_role === "ngo" ? (
              <Attachment
                evidenceId={String(m.meta.evidence_id)}
                filename={String(m.meta.filename ?? "document")}
                fileType={String(m.meta.file_type ?? "")}
                onLoaded={() => listRef.current?.scrollTo({ top: listRef.current.scrollHeight })}
              />
            ) : (
              m.content
            )}
          </li>
        ))}
        {pending !== null && (
          <li className="msg-in ml-8 rounded-lg bg-emerald-50 px-3 py-2 text-sm whitespace-pre-line">
            <p className="mb-1 text-xs font-medium text-stone-500">You</p>
            {pending}
          </li>
        )}
        {pending !== null && (
          <li className="msg-in mr-8 w-16 rounded-lg bg-stone-100 px-3 py-3" aria-label="The assistant is typing">
            <span className="typing-dots"><i /><i /><i /></span>
          </li>
        )}
      </ol>
      {!closed && !busy && <QuickReplies thread={thread} busy={busy} run={chatRun} onPending={setPending} />}
      {!closed && (
        <form
          className="mt-3 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const content = text;
            setText("");
            setPending(content);
            chatRun(() => api<Thread>(`/api/reporting-requests/${thread.request.id}/messages`, { method: "POST", json: { content } }));
          }}
        >
          <input className={inputClass} placeholder="Type your reply…" value={text} onChange={(e) => setText(e.target.value)} />
          <Button type="submit" disabled={busy || !text.trim()}>Send</Button>
        </form>
      )}
      {!closed && lastAwaiting !== "confirm_claims" && (
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
    </Card>
  );
}

// The file endpoint needs the login token, so the image is fetched with it and shown from a local blob.
function Attachment({ evidenceId, filename, fileType, onLoaded }: { evidenceId: string; filename: string; fileType: string; onLoaded: () => void }) {
  const [src, setSrc] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const isImage = fileType.startsWith("image/");
  useEffect(() => {
    if (!isImage) return;
    let url: string | null = null;
    let alive = true;
    fetch(`${API_URL}/api/evidence/${evidenceId}/file`, { headers: { Authorization: `Bearer ${getToken()}` } })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error("gone"))))
      .then((b) => {
        url = URL.createObjectURL(b);
        if (alive) setSrc(url);
      })
      .catch(() => alive && setMissing(true));
    return () => {
      alive = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [evidenceId, isImage]);
  return (
    <div>
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt={filename} onLoad={onLoaded} className="max-h-56 rounded-md border border-stone-200 bg-white" />
      ) : (
        <div className="flex h-20 w-40 items-center justify-center rounded-md border border-dashed border-stone-300 text-xs text-stone-500">
          {isImage && !missing ? "Loading…" : "Document"}
        </div>
      )}
      <p className="mt-1 text-xs text-stone-500">{filename}{missing && " (file no longer stored)"}</p>
    </div>
  );
}

function QuickReplies({ thread, busy, run, onPending }: { thread: Thread; busy: boolean; run: Run; onPending: (t: string) => void }) {
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
      case "nothing_spent":
        return api<Thread>(`/api/reporting-requests/${rid}/messages`, { method: "POST", json: { content: "Nothing spent yet" } });
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
                if (file) {
                  onPending(`Sending ${file.name}…`);
                  run(() => uploadEvidence(rid, a.claim_type!, a.claim_id!, file));
                }
              }}
            />
          </label>
        ) : a.kind === "link" ? (
          <Link key={a.label} href={`/ngo/campaigns/${thread.campaign_id}/${a.href}`} className={chip}>
            {a.label}
          </Link>
        ) : (
          <button key={a.label} className={chip} disabled={busy} onClick={() => {
              onPending(a.kind === "set_amount" ? a.label : a.label.replace(/^Yes, /, ""));
              run(() => go(a));
            }}>
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
      <ul className="mt-3 space-y-2">
        {groupClaims(live).map((g) => <ClaimCard key={g[0].id} claims={g} />)}
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

// Claims that came from the same message (the purchase and the handing out) read as one thing.
function groupClaims(claims: Claim[]): Claim[][] {
  const groups = new Map<string, Claim[]>();
  for (const c of claims) {
    const key = c.report_id ?? c.id;
    groups.set(key, [...(groups.get(key) ?? []), c]);
  }
  return [...groups.values()].map((g) => [...g].sort((a, b) => Number(b.claim_type === "expense") - Number(a.claim_type === "expense")));
}

function ClaimCard({ claims }: { claims: Claim[] }) {
  const expenses = claims.filter((c) => c.claim_type === "expense");
  const impacts = claims.filter((c) => c.claim_type !== "expense");
  const title = (expenses[0] ?? impacts[0]).description;
  const waiting = claims.some((c) => c.status === "proposed");
  return (
    <li className="rounded-lg border border-stone-200 p-3 text-sm">
      <p className="font-medium">{title}</p>
      {expenses.map((c) => (
        <div key={c.id} className="mt-1 text-stone-600">
          <p>
            {expenses.length > 1 && <span className="text-stone-800">{c.description}: </span>}
            Bought for {money(c.amount_cents, c.currency ?? "USD")} · receipts match {money(c.supported_amount_cents, c.currency ?? "USD")}
          </p>
          <div className="mt-1">
            <StatusBadge status={c.evidence_status} />
          </div>
        </div>
      ))}
      {impacts.map((c) => (
        <p key={c.id} className="mt-1 text-stone-600">
          {c.quantity != null ? `Handed out: ${c.quantity} ${c.unit ?? ""}`.trim() : c.description}
        </p>
      ))}
      {waiting && <p className="mt-2 text-xs text-amber-800">Waiting for your OK in the chat</p>}
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
