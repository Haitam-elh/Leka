"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { type Role, team } from "@/lib/team";

export const teamKeys = {
  all: ["team"] as const,
  members: ["team", "members"] as const,
  invitations: ["team", "invitations"] as const,
};

export function useTeamMembers() {
  return useQuery({ queryKey: teamKeys.members, queryFn: team.members });
}

export function useInvitations(enabled: boolean) {
  return useQuery({ queryKey: teamKeys.invitations, queryFn: team.invitations, enabled });
}

/** Invite, change a role, remove, revoke — the team read again. */
export function useTeamChange() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: teamKeys.all });
  return {
    invite: useMutation({
      mutationFn: ({ email, role }: { email: string; role: Role }) => team.invite(email, role),
      onSettled: refresh,
    }),
    changeRole: useMutation({
      mutationFn: ({ id, role }: { id: string; role: Role }) => team.changeRole(id, role),
      onSettled: refresh,
    }),
    remove: useMutation({ mutationFn: (id: string) => team.remove(id), onSettled: refresh }),
    revoke: useMutation({ mutationFn: (id: string) => team.revoke(id), onSettled: refresh }),
  };
}
