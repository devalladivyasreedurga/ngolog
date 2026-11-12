"use client";

import { useState } from "react";
import { DONOR_STATUS, money, type DonorUpdate, type Provenance } from "@/lib/contracts";

/** A small "i" that reveals a one-line explanation. Works on touch screens, unlike a hover tooltip. */
export function Info({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-block align-middle">
      <button
        type="button"
        aria-label="More info"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onBlur={() => setOpen(false)}
        className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full border border-stone-300 text-[10px] leading-none text-stone-500 hover:bg-stone-100"
      >
        i
      </button>
      {open && (
        <span role="tooltip" className="absolute left-0 top-6 z-10 w-56 rounded-lg border border-stone-200 bg-white p-2 text-xs font-normal text-stone-600 shadow">
          {text}
        </span>
      )}
    </span>
  );
}

const TONE = {
  good: "bg-emerald-50 text-emerald-800",
  wait: "bg-amber-50 text-amber-800",
  plain: "bg-stone-100 text-stone-700",
} as const;

function Pill({ tone, children }: { tone: keyof typeof TONE; children: React.ReactNode }) {
  return <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${TONE[tone]}`}>{children}</span>;
}

function Row({ item }: { item: Provenance }) {
  const status = item.evidence_status ? DONOR_STATUS[item.evidence_status] : null;
  if (item.claim_type === "expense" && item.amount_cents != null) {
    const cur = item.currency ?? "USD";
    return (
      <li className="rounded-lg border border-stone-200 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-medium">{item.description}</p>
          {status && <Pill tone={status.tone}>{status.label}</Pill>}
        </div>
        <dl className="mt-2 grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt className="text-xs text-stone-500">Reported spending</dt>
            <dd className="font-semibold">{money(item.amount_cents, cur)}</dd>
          </div>
          <div>
            <dt className="text-xs text-stone-500">Matched by receipts</dt>
            <dd className="font-semibold">{money(item.supported_cents ?? 0, cur)}</dd>
          </div>
        </dl>
      </li>
    );
  }
  if (item.claim_type === "impact" && item.description) {
    return (
      <li className="rounded-lg border border-stone-200 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-medium">{item.description}</p>
          <Pill tone="plain">The organization&apos;s statement</Pill>
        </div>
        {item.quantity != null && (
          <p className="mt-1 text-sm text-stone-600">Quantity: {item.quantity} {item.unit ?? ""}</p>
        )}
      </li>
    );
  }
  // Updates written before item details existed, or with no spending: fall back to the stored sentence.
  return (
    <li className="rounded-lg border border-stone-200 p-3 text-sm">
      <p>{item.text}</p>
      {status && <div className="mt-2"><Pill tone={status.tone}>{status.label}</Pill></div>}
    </li>
  );
}

/** One published (or about-to-be-published) update, as donors see it. */
export function UpdateCard({
  update,
  items,
  apiUrl,
  showWording = true,
}: {
  update: DonorUpdate;
  items: Provenance[];
  apiUrl: string;
  showWording?: boolean;
}) {
  const when = update.published_at ?? update.created_at;
  return (
    <div>
      <p className="text-xs text-stone-500">{new Date(when + "Z").toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}</p>
      <h3 className="mt-0.5 font-semibold">{update.title}</h3>
      <ul className="mt-3 space-y-2">
        {items.map((item, i) => <Row key={i} item={item} />)}
      </ul>
      {update.evidence_refs.length > 0 && (
        <p className="mt-3 text-sm">
          {update.evidence_refs.map((ref, i) => (
            <a key={ref} className="mr-3 text-emerald-800 underline" href={`${apiUrl}/api/evidence/${ref}/file`} target="_blank" rel="noreferrer">
              Shared document {i + 1}
            </a>
          ))}
        </p>
      )}
      <p className="mt-3 text-xs text-stone-500">
        &quot;Documents match&quot; means the receipts agree with what was reported. It isn&apos;t an audit.
      </p>
      {showWording && items.length > 0 && (
        <details className="mt-2 text-xs text-stone-600">
          <summary className="cursor-pointer text-emerald-800">Full wording</summary>
          <div className="mt-2 space-y-2">
            {items.map((item, i) => <p key={i}>{item.text}</p>)}
          </div>
        </details>
      )}
    </div>
  );
}
