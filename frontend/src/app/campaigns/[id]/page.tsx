import { Suspense } from "react";
import { Page } from "@/components/ui";
import CampaignPage from "./client";

export default function Route() {
  return (
    <Suspense fallback={<Page>Loading…</Page>}>
      <CampaignPage />
    </Suspense>
  );
}
