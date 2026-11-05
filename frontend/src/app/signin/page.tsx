"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Card, ErrorText, inputClass, Page } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import type { Role } from "@/lib/contracts";

const DEMO_ACCOUNTS: { label: string; email: string; role: Role }[] = [
  { label: "Demo NGO", email: "ngo@brightfutures.org", role: "ngo_admin" },
  { label: "Demo donor", email: "donor@example.com", role: "donor" },
];

export default function SignIn() {
  const { signIn } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("donor");
  const [error, setError] = useState<string | null>(null);

  async function go(e: string, r: Role) {
    setError(null);
    try {
      const user = await signIn(e, r);
      router.push(user.role === "ngo_admin" ? "/ngo/dashboard" : user.role === "donor" ? "/donor/dashboard" : "/accountability");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <Page>
      <Card className="mx-auto max-w-md">
        <h1 className="text-xl font-semibold">Sign in</h1>
        <p className="mt-1 text-sm text-stone-600">Demo sign-in: no password. Accounts are created on first use.</p>
        <div className="mt-4 flex gap-2">
          {DEMO_ACCOUNTS.map((a) => (
            <Button key={a.email} variant="secondary" onClick={() => go(a.email, a.role)}>
              {a.label}
            </Button>
          ))}
        </div>
        <form
          className="mt-6 space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            go(email, role);
          }}
        >
          <input className={inputClass} type="email" required placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
          <select className={inputClass} value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="donor">Donor</option>
            <option value="ngo_admin">NGO admin</option>
            <option value="reviewer">Platform reviewer (allowlisted)</option>
          </select>
          <Button type="submit">Continue</Button>
          <ErrorText error={error} />
        </form>
      </Card>
    </Page>
  );
}
