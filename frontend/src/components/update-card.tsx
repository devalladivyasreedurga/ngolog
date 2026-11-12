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
        <span role="tooltip" className="absolute left-0 top-6 z-10 w-56 rounded-lg border border-stone-200 bg-surface p-2 text-xs font-normal text-[#58574d] shadow">
          {text}
        </span>
      )}
    </span>
  );
}

const TONE = {
  good: "bg-emerald-50 text-[#43563a]",
  wait: "bg-amber-50 text-[#9c2616]",
  plain: "bg-surface text-[#3f3e37]",
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

function Stat({ label, value, info, first, hover, compact }: { label: string; value: string; info?: string; first?: boolean; hover?: boolean; compact?: boolean }) {
  return (
    <div className={`flex-1 py-3 ${first ? "" : "border-l border-stone-200 pl-4"}`}>
      <p className="text-xs text-stone-500">{label}{info && <Info text={info} />}</p>
      <p className={`mt-0.5 ${compact ? "text-xl" : "text-2xl"} font-semibold ${hover ? "origin-left cursor-default transition duration-150 hover:scale-110 hover:text-coral-500" : ""}`}>{value}</p>
    </div>
  );
}

const fileUrl = (apiUrl: string, id: string) => `${apiUrl}/api/evidence/${id}/file`;

function Photo({ apiUrl, id, className }: { apiUrl: string; id: string; className: string }) {
  return (
    <a href={fileUrl(apiUrl, id)} target="_blank" rel="noreferrer">
      {/* eslint-disable-next-line @next/next/no-img-element -- served by the API, not a static asset */}
      <img src={fileUrl(apiUrl, id)} alt="Shared by the organization" loading="lazy" className={`w-full rounded-lg border border-stone-200 object-cover ${className}`} />
    </a>
  );
}

/** One published (or about-to-be-published) update, as donors see it: a short summary first, the full list on request. */
export function UpdateCard({
  update,
  items,
  photos = [],
  apiUrl,
  showWording = true,
  action,
  compact = false,
}: {
  update: DonorUpdate;
  items: Provenance[];
  photos?: string[];
  apiUrl: string;
  showWording?: boolean;
  action?: React.ReactNode;
  compact?: boolean;
}) {
  const [allPhotos, setAllPhotos] = useState(false);
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
    <div className={`rounded-xl border border-stone-200 bg-surface ${compact ? "p-4" : "p-5"}`}>
      <div className="flex flex-wrap items-start gap-3">
        <div>
          <p className="text-xs text-stone-500">{new Date(when + "Z").toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}</p>
        </div>
        {action && <div className="ml-auto">{action}</div>}
      </div>

      {spent.length > 0 ? (
        <>
          <p className={`mt-2 ${compact ? "text-sm" : "text-base"} font-semibold text-stone-900`}>
            {names.length > 0 && <>Spent on {names.slice(0, 4).join(", ")}{names.length > 4 ? ` and ${names.length - 4} more` : ""}. </>}
            {verdict}
          </p>
          <div className={`${compact ? "mt-2" : "mt-3"} flex border-y border-stone-200`}>
            <Stat compact={compact} first hover label="Reported spending" value={money(reported, cur)} info="What the organization says it spent. Not an audited figure." />
            <Stat compact={compact} label="Matched by receipts" value={money(matched, cur)} info="The part of the reported spending that reviewed receipts support." />
            <Stat compact={compact} label="Activities" value={String(acts.length)} info="Things the organization says it did, such as handing out items. Its own statement." />
          </div>
        </>
      ) : (
        items[0] && <p className="mt-3 text-base font-semibold text-stone-900">{items[0].text}</p>
      )}

      {photos.length > 0 && (
        <div className="mt-4">
          <div className={`group relative ${compact ? "max-w-[14rem]" : "max-w-sm"}`} title="Photos show that something happened. They are not receipts.">
            <Photo apiUrl={apiUrl} id={photos[0]} className={compact ? "h-28" : "h-44"} />
            <p className="pointer-events-none absolute inset-x-0 bottom-0 rounded-b-lg bg-stone-900/75 px-3 py-2 text-xs text-white opacity-0 transition-opacity duration-150 group-focus-within:opacity-100 group-hover:opacity-100">
              Photos show that something happened. They are not receipts.
            </p>
          </div>
          {photos.length > 1 && (
            <button
              type="button"
              onClick={() => setAllPhotos((v) => !v)}
              aria-expanded={allPhotos}
              className="mt-2 rounded-lg border border-stone-300 px-3 py-1.5 text-sm text-emerald-800 hover:bg-stone-50"
            >
              {allPhotos ? "Hide photos" : `See all ${photos.length} photos`}
            </button>
          )}
          {allPhotos && photos.length > 1 && (
            <ul className="mt-3 grid grid-cols-2 gap-1.5 sm:grid-cols-4">
              {photos.map((id) => (
                <li key={id}>
                  <Photo apiUrl={apiUrl} id={id} className="h-24" />
                </li>
              ))}
            </ul>
          )}
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
