"use client";

import { useQuery } from "@tanstack/react-query";

import { billing } from "@/lib/billing";

export function useWorkspaceUsage() {
  return useQuery({ queryKey: ["billing", "usage"], queryFn: billing.usage });
}

export function useCredits() {
  return useQuery({ queryKey: ["billing", "credits"], queryFn: billing.credits });
}
