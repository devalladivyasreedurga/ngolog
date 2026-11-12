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

function Tile({ label, value, info }: { label: string; value: string; info?: string }) {
  return (
    <div className="rounded-lg bg-stone-50 p-3">
      <p className="text-xs text-stone-500">{label}{info && <Info text={info} />}</p>
      <p className="mt-0.5 text-lg font-semibold">{value}</p>
    </div>
  );
}

/** One published (or about-to-be-published) update, as donors see it: a short summary first, the full list on request. */
export function UpdateCard({
  update,
  items,
  photos = [],
  apiUrl,
  showWording = true,
}: {
  update: DonorUpdate;
  items: Provenance[];
  photos?: string[];
  apiUrl: string;
  showWording?: boolean;
}) {
  const when = update.published_at ?? update.created_at;
  const spent = items.filter((i) => i.claim_type === "expense" && i.amount_cents != null);
  const acts = items.filter((i) => i.claim_type === "impact" && i.description);
  const cur = spent[0]?.currency ?? "USD";
  const reported = spent.reduce((n, i) => n + (i.amount_cents ?? 0), 0);
  const matched = spent.reduce((n, i) => n + (i.supported_cents ?? 0), 0);
  const names = spent.map((i) => i.description).filter(Boolean) as string[];
  const receipts = update.evidence_refs.filter((r) => !photos.includes(r));
  const verdict =
    spent.length === 0 ? null : matched === 0 ? "No receipts yet. This is the organization's own report." : matched >= reported ? "Receipts match the reported amount." : "Receipts match part of the reported amount.";

  return (
    <div>
      <p className="text-xs text-stone-500">{new Date(when + "Z").toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}</p>
      <h3 className="mt-0.5 text-lg font-semibold">{update.title}</h3>

      {spent.length > 0 && (
        <>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
            <Tile label="Reported spending" value={money(reported, cur)} info="What the organization says it spent. Not an audited figure." />
            <Tile label="Matched by receipts" value={money(matched, cur)} info="The part of the reported spending that reviewed receipts support." />
            <Tile label="Activities reported" value={String(acts.length)} info="Things the organization says it did, such as handing out items. Its own statement." />
          </div>
          <p className="mt-3 text-sm text-stone-700">
            {names.length > 0 && <>Spent on {names.slice(0, 4).join(", ")}{names.length > 4 ? ` and ${names.length - 4} more` : ""}. </>}
            {verdict}
          </p>
        </>
      )}
      {spent.length === 0 && items[0] && <p className="mt-3 text-sm text-stone-700">{items[0].text}</p>}

      {photos.length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-medium uppercase tracking-wide text-stone-500">Photos from the organization</p>
          <ul className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {photos.map((id) => (
              <li key={id}>
                <a href={`${apiUrl}/api/evidence/${id}/file`} target="_blank" rel="noreferrer">
                  {/* eslint-disable-next-line @next/next/no-img-element -- served by the API, not a static asset */}
                  <img src={`${apiUrl}/api/evidence/${id}/file`} alt="Shared by the organization" loading="lazy" className="aspect-[4/3] w-full rounded-lg border border-stone-200 object-cover" />
                </a>
              </li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-stone-500">Photos show that something happened. They are not receipts.</p>
        </div>
      )}

      {(items.length > 0 || receipts.length > 0) && (
        <details className="group mt-4 border-t border-stone-200 pt-3">
          <summary className="cursor-pointer text-sm font-medium text-emerald-800">
            <span className="group-open:hidden">See the details</span>
            <span className="hidden group-open:inline">Hide the details</span>
          </summary>
          <ul className="mt-3 space-y-2">
            {items.map((item, i) => <Row key={i} item={item} />)}
          </ul>
          {receipts.length > 0 && (
            <div className="mt-3 text-sm">
              <p className="text-xs font-medium uppercase tracking-wide text-stone-500">Receipts shared by the organization</p>
              <p className="mt-1">
                {receipts.map((ref, i) => (
                  <a key={ref} className="mr-3 text-emerald-800 underline" href={`${apiUrl}/api/evidence/${ref}/file`} target="_blank" rel="noreferrer">
                    Receipt {i + 1}
                  </a>
                ))}
              </p>
            </div>
          )}
          {showWording && (
            <div className="mt-3 space-y-2 text-xs text-stone-600">
              <p className="font-medium text-stone-700">Full wording</p>
              {items.map((item, i) => <p key={i}>{item.text}</p>)}
            </div>
          )}
        </details>
      )}
      <p className="mt-3 text-xs text-stone-500">
        &quot;Documents match&quot; means the receipts agree with what was reported. It isn&apos;t an audit.
      </p>
    </div>
  );
}
