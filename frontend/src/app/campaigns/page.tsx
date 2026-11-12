"use client";

import { CampaignList } from "@/components/campaign-list";
import { Page } from "@/components/ui";

export default function Campaigns() {
  return (
    <Page>
      <h1 className="text-3xl font-semibold">Campaigns</h1>
      <CampaignList />
    </Page>
  );
}
