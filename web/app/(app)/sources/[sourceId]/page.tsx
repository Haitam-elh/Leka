"use client";

import { useParams } from "next/navigation";

import { SourcePage } from "@/components/sources/source-page";

export default function Page() {
  const { sourceId } = useParams<{ sourceId: string }>();
  return <SourcePage sourceId={sourceId} />;
}
