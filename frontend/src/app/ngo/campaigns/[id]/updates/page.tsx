import { Suspense } from "react";
import { Page } from "@/components/ui";
import Updates from "./client";

export default function Route() {
  return (
    <Suspense fallback={<Page>Loading…</Page>}>
      <Updates />
    </Suspense>
  );
}
