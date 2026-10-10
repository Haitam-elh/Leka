"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { access, type PolicyUpdate, type RoleUpdate } from "@/lib/access";

export const accessKeys = {
  all: ["access"] as const,
  model: ["access", "model"] as const,
  restrictions: ["access", "restrictions"] as const,
  decisions: (decision: string | null) => ["access", "decisions", decision] as const,
  search: (q: string) => ["access", "search", q] as const,
  roles: ["access", "roles"] as const,
  assignments: ["access", "assignments"] as const,
  policies: ["access", "policies"] as const,
  history: ["access", "history"] as const,
};

export function useAccessModel() {
  return useQuery({ queryKey: accessKeys.model, queryFn: access.model });
}

export function useRestrictions() {
  return useQuery({ queryKey: accessKeys.restrictions, queryFn: access.restrictions });
}

export function useDecisions(decision: "allow" | "deny" | null) {
  return useQuery({
    queryKey: accessKeys.decisions(decision),
    queryFn: () => access.decisions(decision),
  });
}

export function useEntitySearch(q: string) {
  return useQuery({
    queryKey: accessKeys.search(q),
    queryFn: () => access.search(q),
    enabled: q.trim().length >= 2,
  });
}

/** Restricted, lifted — the restrictions and the trail read again. */
export function useRestrictionChange() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: accessKeys.all });
  return {
    restrict: useMutation({
      mutationFn: ({ entityId, reason }: { entityId: string; reason: string }) =>
        access.restrict(entityId, reason),
      onSettled: refresh,
    }),
    lift: useMutation({ mutationFn: (entityId: string) => access.lift(entityId), onSettled: refresh }),
  };
}

export function useCustomRoles() {
  return useQuery({ queryKey: accessKeys.roles, queryFn: access.roles });
}

export function useAssignments() {
  return useQuery({ queryKey: accessKeys.assignments, queryFn: access.assignments });
}

export function usePolicies() {
  return useQuery({ queryKey: accessKeys.policies, queryFn: access.policies });
}

export function useGovernanceHistory() {
  return useQuery({ queryKey: accessKeys.history, queryFn: access.history });
}

/** Roles, assignments, policies changed — all of it read again. */
export function usePolicyChange() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: accessKeys.all });
  return {
    saveRole: useMutation({
      mutationFn: ({ key, body }: { key: string; body: RoleUpdate }) => access.saveRole(key, body),
      onSettled: refresh,
    }),
    deleteRole: useMutation({ mutationFn: (key: string) => access.deleteRole(key), onSettled: refresh }),
    assign: useMutation({
      mutationFn: ({ userId, role }: { userId: string; role: string | null }) =>
        access.assign(userId, role),
      onSettled: refresh,
    }),
    createPolicy: useMutation({
      mutationFn: (body: PolicyUpdate) => access.createPolicy(body),
      onSettled: refresh,
    }),
    updatePolicy: useMutation({
      mutationFn: ({ id, body }: { id: string; body: PolicyUpdate }) => access.updatePolicy(id, body),
      onSettled: refresh,
    }),
    deletePolicy: useMutation({
      mutationFn: (id: string) => access.deletePolicy(id),
      onSettled: refresh,
    }),
  };
}
