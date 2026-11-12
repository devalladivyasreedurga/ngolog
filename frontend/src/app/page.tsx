"use client";

import Link from "next/link";
import { CampaignList } from "@/components/campaign-list";
import { Page } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function Home() {
  const { user, ready } = useAuth();
  const showLanding = ready && !user;

  return (
    <Page>
      <section className={showLanding ? "py-10 sm:py-16" : ""}>
        <h1 className={showLanding ? "max-w-3xl text-4xl font-semibold leading-tight sm:text-5xl" : "text-3xl font-semibold"}>
          Your donation shouldn&apos;t be the end of the story.
        </h1>
        <p className={`max-w-2xl text-stone-600 ${showLanding ? "mt-4 text-lg" : "mt-2"}`}>
          Give through PayPal, then follow what the organization reports doing with campaign funds, which documents
          were reviewed, and what is still being clarified.
        </p>
        {showLanding && (
          <div className="mt-6 flex flex-wrap gap-3">
            <Link
              href="/signin"
              className="rounded-lg bg-coral-500 px-4 py-2.5 text-sm font-medium text-white hover:bg-coral-600"
            >
              Sign in to donate
            </Link>
            <Link
              href="/campaigns"
              className="rounded-lg border border-stone-300 bg-surface px-4 py-2.5 text-sm font-medium text-stone-800 hover:bg-stone-50"
            >
              Browse campaigns
            </Link>
          </div>
        )}
      </section>
      {user && <CampaignList />}
    </Page>
  );
}
