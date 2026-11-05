"use client";

import { AllCommunityModule, ModuleRegistry, type ColDef } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Card, ErrorText, inputClass, Page, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { money, STATUS_LABEL, type EvidenceReviewStatus } from "@/lib/contracts";

ModuleRegistry.registerModules([AllCommunityModule]);

interface CheckRow {
  check_type: string;
  status: "pass" | "flag" | "inconclusive";
  findings: Record<string, unknown>;
  created_at: string;
}

interface ClaimRow {
  claim_id: string;
  claim_type: string;
  campaign_id: string;
  campaign_title: string;
  ngo_name: string;
  description: string;
  claim_status: string;
  evidence_status: EvidenceReviewStatus;
  reported_cents: number | null;
  supported_cents: number | null;
  gap_cents: number | null;
  currency: string | null;
  evidence_count: number;
  reporting_request_id: string;
  request_status: string;
  investigation_id: string | null;
  investigation_status: string | null;
  open_question: string | null;
  checks: CheckRow[];
  created_at: string;
}

interface RequestRow {
  reporting_request_id: string;
  campaign_id: string;
  campaign_title: string;
  ngo_name: string;
  cycle_key: string;
  status: string;
  due_at: string | null;
  past_due: boolean;
  clarification_rounds: number;
}

const moneyCell = (p: { value: number | null; data?: ClaimRow }) => (p.value == null ? "" : money(p.value, p.data?.currency ?? "USD"));

const CLAIM_COLUMNS: ColDef<ClaimRow>[] = [
  { field: "campaign_title", headerName: "Campaign", flex: 2, minWidth: 180 },
  { field: "description", headerName: "Claim", flex: 2, minWidth: 180 },
  { field: "reported_cents", headerName: "Reported", width: 115, type: "rightAligned", valueFormatter: moneyCell },
  { field: "supported_cents", headerName: "Documented", width: 125, type: "rightAligned", valueFormatter: moneyCell },
  { field: "gap_cents", headerName: "Gap", width: 100, type: "rightAligned", valueFormatter: moneyCell },
  { field: "evidence_status", headerName: "Evidence status", width: 240, valueFormatter: (p) => STATUS_LABEL[p.value as EvidenceReviewStatus] ?? p.value, filter: true },
  { field: "evidence_count", headerName: "Docs", width: 80, type: "rightAligned" },
  { field: "investigation_status", headerName: "Question", width: 120, filter: true },
];

const REQUEST_COLUMNS: ColDef<RequestRow>[] = [
  { field: "campaign_title", headerName: "Campaign", flex: 2, minWidth: 180 },
  { field: "cycle_key", headerName: "Cycle", width: 120 },
  { field: "status", headerName: "Status", width: 170, filter: true },
  { field: "due_at", headerName: "Due", width: 130, valueFormatter: (p) => (p.value ? new Date(p.value + "Z").toLocaleDateString() : "") },
  { field: "past_due", headerName: "Past due", width: 150, cellDataType: false, valueFormatter: (p) => (p.value ? "No recent update" : "") },
  { field: "clarification_rounds", headerName: "Questions asked", width: 150, type: "rightAligned" },
];

export default function Accountability() {
  const { user, ready } = useAuth();
  const [claims, setClaims] = useState<ClaimRow[]>([]);
  const [requests, setRequests] = useState<RequestRow[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [attentionOnly, setAttentionOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api<{ claims: ClaimRow[]; requests: RequestRow[] }>("/api/accountability");
      setClaims(data.claims);
      setRequests(data.requests);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    if (user?.role !== "ngo_admin" && user?.role !== "reviewer") return;
    let alive = true;
    Promise.resolve().then(() => {
      if (alive) void load();
    });
    return () => {
      alive = false;
    };
  }, [user, load]);

  const rows = useMemo(() => (attentionOnly ? claims.filter((c) => c.open_question || c.evidence_status === "needs_clarification" || c.claim_status === "proposed") : claims), [claims, attentionOnly]);
  const selected = claims.find((c) => c.claim_id === selectedId) ?? null;

  if (ready && user?.role !== "ngo_admin" && user?.role !== "reviewer") {
    return <Page><Link href="/signin" className="underline">Sign in as an NGO admin or reviewer</Link> to see this console.</Page>;
  }

  return (
    <Page>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">Accountability console</h1>
        <span className="ml-auto" />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={attentionOnly} onChange={(e) => setAttentionOnly(e.target.checked)} />
          Needs attention only
        </label>
      </div>
      <p className="mt-1 text-sm text-stone-600">
        Reported amounts are NGO statements. &quot;Documented&quot; is what reviewed documents support. Gaps are questions to follow up, not findings of wrongdoing.
      </p>
      <ErrorText error={error} />

      <h2 className="mt-6 font-semibold">Claims and evidence</h2>
      <div className="mt-2 h-80 w-full">
        <AgGridReact<ClaimRow>
          rowData={rows}
          columnDefs={CLAIM_COLUMNS}
          defaultColDef={{ sortable: true, resizable: true }}
          getRowId={(p) => p.data.claim_id}
          rowSelection={{ mode: "singleRow", checkboxes: false, enableClickSelection: true }}
          onSelectionChanged={(e) => setSelectedId(e.api.getSelectedRows()[0]?.claim_id ?? null)}
          overlayNoRowsTemplate="No claims yet"
        />
      </div>

      {selected && <ClaimDetail row={selected} canResolve={user?.role === "reviewer"} onResolved={load} />}

      <h2 className="mt-8 font-semibold">Reporting requests</h2>
      <div className="mt-2 h-56 w-full">
        <AgGridReact<RequestRow>
          rowData={requests}
          columnDefs={REQUEST_COLUMNS}
          defaultColDef={{ sortable: true, resizable: true }}
          getRowId={(p) => p.data.reporting_request_id}
          overlayNoRowsTemplate="No reporting requests yet"
        />
      </div>
    </Page>
  );
}

const CHECK_LABELS: Record<string, string> = {
  amount_match: "Amount comparison",
  exact_duplicate: "Identical file",
  reused_receipt: "Reused receipt number",
  near_duplicate: "Similar document",
  extraction: "Receipt reading",
  context_retrieval: "Earlier records searched",
};

function ClaimDetail({ row, canResolve, onResolved }: { row: ClaimRow; canResolve: boolean; onResolved: () => void }) {
  const [resolution, setResolution] = useState("");
  const [error, setError] = useState<string | null>(null);
  const canAct = canResolve && row.investigation_id && row.open_question;

  return (
    <Card className="mt-4">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="font-semibold">{row.description}</h3>
        <StatusBadge status={row.evidence_status} />
        <span className="ml-auto" />
        <Link href={`/campaigns/${row.campaign_id}`} className="text-sm text-emerald-800 hover:underline">Public page</Link>
      </div>
      {row.open_question && <p className="mt-3 rounded-lg bg-amber-50 p-3 text-sm whitespace-pre-line text-amber-900">{row.open_question}</p>}
      <h4 className="mt-4 text-sm font-medium">Evidence trail</h4>
      {row.checks.length === 0 && <p className="text-sm text-stone-500">No checks recorded yet.</p>}
      <ul className="mt-1 space-y-1 text-sm">
        {row.checks.map((c, i) => (
          <li key={i}>
            <span className={c.status === "flag" ? "font-medium text-amber-800" : "text-stone-700"}>{CHECK_LABELS[c.check_type] ?? c.check_type}: {c.status}</span>
            <span className="ml-2 text-xs text-stone-500">{new Date(c.created_at + "Z").toLocaleString()}</span>
          </li>
        ))}
      </ul>
      {canAct && (
        <div className="mt-4 flex flex-wrap gap-2">
          <input className={`${inputClass} flex-1`} placeholder="What did you check, and what did you conclude?" value={resolution} onChange={(e) => setResolution(e.target.value)} />
          <Button
            disabled={resolution.trim().length < 3}
            onClick={async () => {
              setError(null);
              try {
                await api(`/api/investigations/${row.investigation_id}/resolve`, { method: "POST", json: { resolution } });
                setResolution("");
                onResolved();
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            Record review
          </Button>
        </div>
      )}
      <ErrorText error={error} />
    </Card>
  );
}
