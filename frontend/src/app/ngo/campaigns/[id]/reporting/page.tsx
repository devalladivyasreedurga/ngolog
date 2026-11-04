import { Suspense } from "react";
import { Page } from "@/components/ui";
import Reporting from "./client";

export default function Route() {
  return (
    <Suspense fallback={<Page>Loading…</Page>}>
      <Reporting />
    </Suspense>
  );
}
