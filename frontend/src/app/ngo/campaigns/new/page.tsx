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
  const [plan, setPlan] = useState<{ questions: string[]; evidence: string[]; limitations: string; source: string } | null>(null);
  const [newChip, setNewChip] = useState("");
  const [showLimits, setShowLimits] = useState(false);
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
      setPlan({ questions: p.questions, evidence: p.evidence_suggestions, limitations: p.limitations.join("\n"), source: p.source });
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
      await api(`/api/campaigns/${campaign.id}/reporting-plan`, { method: "PUT", json: { questions: plan.questions, evidence_suggestions: plan.evidence, limitations: lines(plan.limitations) } });
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
          <Card className="mt-4 space-y-5">
            <div>
              <h2 className="font-semibold">How you&apos;ll report</h2>
              <p className="mt-1 text-sm text-stone-600">
                The assistant will check in {form.reporting_frequency_days === "7" ? "every week" : form.reporting_frequency_days === "14" ? "every two weeks" : "every month"} and ask what you spent and handed out. It never moves money.
              </p>
            </div>
            <div>
              <p className="text-sm font-medium">Evidence you can share</p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {plan.evidence.map((e, i) => (
                  <span key={`${e}-${i}`} className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-3 py-1 text-sm text-emerald-900">
                    {e}
                    <button type="button" aria-label={`Remove ${e}`} className="text-emerald-700 hover:text-emerald-950" onClick={() => setPlan({ ...plan, evidence: plan.evidence.filter((_, j) => j !== i) })}>×</button>
                  </span>
                ))}
                <form
                  onSubmit={(ev) => {
                    ev.preventDefault();
                    const v = newChip.trim();
                    if (v) setPlan({ ...plan, evidence: [...plan.evidence, v] });
                    setNewChip("");
                  }}
                >
                  <input className="w-40 rounded-full border border-dashed border-stone-300 px-3 py-1 text-sm" placeholder="+ Add another" value={newChip} onChange={(ev) => setNewChip(ev.target.value)} />
                </form>
              </div>
            </div>
            <p className="text-xs text-stone-500">
              Donors will see a short note on the campaign page about what these documents can and can&apos;t show.{" "}
              <button type="button" className="underline" onClick={() => setShowLimits(!showLimits)}>
                {showLimits ? "Hide limitations" : "Limitations"}
              </button>
            </p>
            {showLimits && (
              <textarea className={`${inputClass} text-sm`} rows={3} aria-label="Limitations shown to donors" value={plan.limitations} onChange={(ev) => setPlan({ ...plan, limitations: ev.target.value })} />
            )}
            <Button onClick={acceptAndPublish} disabled={busy}>Publish campaign</Button>
            <ErrorText error={error} />
          </Card>
        )
      )}
    </Page>
  );
}
