/**
 * An Enterprise contract (2026-10-25): « La page Facturation devient
 * Contrat » — its type, the organisation, since when, its members, its
 * dedicated contact — and nothing commercial anywhere: no price, no
 * credits, no bundle, no « Passer à… », no checkout. The server refuses
 * them too (`enterprise_contract`); the screens never offer them.
 *
 * Its logo, given by its admin: text — its name — by default.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiAddress, apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { useCredits } from "@/lib/billing-queries";
import { workspace, type WorkspaceRead } from "@/lib/workspace";

export type Contract = components["schemas"]["ContractRead"];

export const ENTERPRISE = "enterprise";
/** What its admin may give: what the server keeps. */
export const LOGO_TYPES = ["image/png", "image/jpeg", "image/webp"] as const;
export const LOGO_MAX_BYTES = 512 * 1024;

export const contracts = {
  read: () => apiFetch<Contract>("/billing/contract"),
  giveLogo: (file: File) =>
    apiFetch<WorkspaceRead>("/workspaces/current/logo", {
      method: "PUT",
      body: file,
      headers: { "Content-Type": file.type },
    }),
  removeLogo: () => apiFetch<undefined>("/workspaces/current/logo", { method: "DELETE" }),
};

/** Under an Enterprise contract — false until known: never assumed. */
export function useEnterprise(): boolean {
  return useCredits().data?.plan === ENTERPRISE;
}

export function useContract(enabled = true) {
  return useQuery({ queryKey: ["billing", "contract"], queryFn: contracts.read, enabled });
}

/** The workspace as the API keeps it — its settings with it. */
const CURRENT = ["workspace", "current"] as const;

export function useWorkspaceDetails(enabled = true) {
  return useQuery({ queryKey: CURRENT, queryFn: workspace.current, enabled });
}

export type Logo = { key: string; type: string; updated_at: string };

export function logoOf(saved: WorkspaceRead | undefined): Logo | null {
  const said = (saved?.settings as { logo?: Partial<Logo> } | undefined)?.logo;
  return said?.key && said.type && said.updated_at
    ? { key: said.key, type: said.type, updated_at: said.updated_at }
    : null;
}

/** Where its image is read — its moment in the address, so a new one is
 * never an old one cached. */
export function logoAddress(logo: Logo): string {
  return apiAddress(`/workspaces/current/logo?v=${encodeURIComponent(logo.updated_at)}`);
}

export function useLogo(enabled = true): Logo | null {
  return logoOf(useWorkspaceDetails(enabled).data?.workspace);
}

export function useGiveLogo() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: contracts.giveLogo,
    onSuccess: () => queries.invalidateQueries({ queryKey: CURRENT }),
  });
}

export function useRemoveLogo() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: contracts.removeLogo,
    onSuccess: () => queries.invalidateQueries({ queryKey: CURRENT }),
  });
}
