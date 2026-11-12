"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { STATUS_LABEL, type EvidenceReviewStatus } from "@/lib/contracts";

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <section className={`rounded-xl border border-stone-200 bg-surface p-5 ${className}`}>{children}</section>;
}

export function Button({
  children,
  variant = "primary",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "accent" }) {
  const styles = {
    primary: "bg-emerald-700 text-white hover:bg-emerald-800",
    secondary: "border border-stone-300 bg-surface text-stone-800 hover:bg-stone-50",
    ghost: "text-emerald-800 hover:underline",
    accent: "bg-coral-500 text-white hover:bg-coral-600",
  }[variant];
  return (
    <button
      {...props}
      className={`rounded-lg px-3.5 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${props.className ?? ""}`}
    >
      {children}
    </button>
  );
}

export const inputClass =
  "w-full rounded-lg border border-stone-300 bg-surface px-3 py-2 text-sm focus:border-emerald-700 focus:outline-none";

const STATUS_COLORS: Record<EvidenceReviewStatus, string> = {
  reported: "bg-stone-100 text-stone-700",
  submitted: "bg-sky-50 text-sky-800",
  consistent: "bg-emerald-50 text-emerald-800",
  needs_clarification: "bg-amber-50 text-amber-800",
  reviewed_by_human: "bg-violet-50 text-violet-800",
  not_documented: "bg-stone-100 text-stone-700",
};

export function StatusBadge({ status }: { status: EvidenceReviewStatus }) {
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_COLORS[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  );
}

export function ErrorText({ error }: { error: string | null }) {
  return error ? <p className="text-sm text-red-700">{error}</p> : null;
}

export function Nav() {
  const { user, signOut } = useAuth();
  const router = useRouter();
  return (
    <header className="bg-emerald-400 text-emerald-950">
      <nav className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-6 py-3 text-sm">
        <Link href="/" className="text-base font-semibold text-emerald-950">
          NGOLog<span className="text-coral-500">.</span>
        </Link>
        <Link href="/campaigns" className="text-emerald-950 hover:underline">
          Campaigns
        </Link>
        {user?.role === "ngo_admin" && (
          <Link href="/ngo/dashboard" className="text-emerald-950 hover:underline">
            NGO dashboard
          </Link>
        )}
        {(user?.role === "ngo_admin" || user?.role === "reviewer") && (
          <Link href="/accountability" className="text-emerald-950 hover:underline">
            Accountability
          </Link>
        )}
        {user?.role === "donor" && (
          <Link href="/donor/dashboard" className="text-emerald-950 hover:underline">
            My campaigns
          </Link>
        )}
        <span className="ml-auto" />
        {user ? (
          <>
            <span className="text-emerald-950/80">{user.email}</span>
            <Button
              variant="ghost"
              className="!text-emerald-950"
              onClick={() => {
                signOut();
                router.push("/");
              }}
            >
              Sign out
            </Button>
          </>
        ) : (
          <Link href="/signin" className="font-medium text-emerald-950 hover:underline">
            Sign in
          </Link>
        )}
      </nav>
    </header>
  );
}

export function Page({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">{children}</main>;
}
