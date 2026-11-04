"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Card, ErrorText, inputClass, Page } from "@/components/ui";
import { api } from "@/lib/api";
import type { Campaign, Plan } from "@/lib/contracts";

export default function NewCampaign() {
  const router = useRouter();
  const [form, setForm] = useState({ title: "", description: "", category: "school_supplies", target_amount: "1000", expected_activities: "", reporting_frequency_days: "7" });
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [plan, setPlan] = useState<{ questions: string; evidence: string; limitations: string; source: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });

  async function createAndDraft(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const c = await api<Campaign>("/api/campaigns", { method: "POST", json: { ...form, target_amount: Number(form.target_amount), reporting_frequency_days: Number(form.reporting_frequency_days) } });
      setCampaign(c);
      const p = await api<Plan>(`/api/campaigns/${c.id}/reporting-plan/draft`, { method: "POST" });
      setPlan({ questions: p.questions.join("\n"), evidence: p.evidence_suggestions.join("\n"), limitations: p.limitations.join("\n"), source: p.source });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function acceptAndPublish() {
    if (!campaign || !plan) return;
    setBusy(true);
    setError(null);
    const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);
    try {
      await api(`/api/campaigns/${campaign.id}/reporting-plan`, { method: "PUT", json: { questions: lines(plan.questions), evidence_suggestions: lines(plan.evidence), limitations: lines(plan.limitations) } });
      await api(`/api/campaigns/${campaign.id}/publish`, { method: "POST" });
      router.push(`/campaigns/${campaign.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <Page>
      <h1 className="text-2xl font-semibold">New campaign</h1>
      {!campaign ? (
        <Card className="mt-4">
          <form className="space-y-3" onSubmit={createAndDraft}>
            <input className={inputClass} required minLength={3} placeholder="Title, e.g. Supply 50 students with school kits" value={form.title} onChange={set("title")} />
            <textarea className={inputClass} required minLength={10} rows={4} placeholder="Describe the cause and who it helps" value={form.description} onChange={set("description")} />
            <textarea className={inputClass} rows={2} placeholder="Expected activities, e.g. buy kits from a local supplier, hand out at school" value={form.expected_activities} onChange={set("expected_activities")} />
            <div className="grid gap-3 sm:grid-cols-3">
              <select className={inputClass} value={form.category} onChange={set("category")}>
                <option value="school_supplies">School supplies</option>
                <option value="general">General</option>
              </select>
              <input className={inputClass} type="number" min={1} required value={form.target_amount} onChange={set("target_amount")} aria-label="Target amount (USD)" />
              <select className={inputClass} value={form.reporting_frequency_days} onChange={set("reporting_frequency_days")} aria-label="Update frequency">
                <option value="7">Weekly updates</option>
                <option value="14">Every two weeks</option>
                <option value="30">Monthly</option>
              </select>
            </div>
            <Button type="submit" disabled={busy}>{busy ? "Drafting reporting plan…" : "Create and draft reporting plan"}</Button>
            <ErrorText error={error} />
          </form>
        </Card>
      ) : (
        plan && (
          <Card className="mt-4 space-y-4">
            <div>
              <h2 className="font-semibold">Reporting plan</h2>
              <p className="text-sm text-stone-600">
                {plan.source === "ai" ? "Drafted by AI" : "Starter template"}. Edit freely, one item per line. This is what the assistant will ask about; it is not a payout schedule.
              </p>
            </div>
            <PlanField label="Questions the assistant will ask" value={plan.questions} onChange={(v) => setPlan({ ...plan, questions: v })} />
            <PlanField label="Useful supporting evidence" value={plan.evidence} onChange={(v) => setPlan({ ...plan, evidence: v })} />
            <PlanField label="Limitations donors should know" value={plan.limitations} onChange={(v) => setPlan({ ...plan, limitations: v })} />
            <Button onClick={acceptAndPublish} disabled={busy}>Accept plan and publish campaign</Button>
            <ErrorText error={error} />
          </Card>
        )
      )}
    </Page>
  );
}

function PlanField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="block text-sm font-medium">
      {label}
      <textarea className={`${inputClass} mt-1 font-normal`} rows={4} value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}
