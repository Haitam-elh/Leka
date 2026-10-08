/**
 * Équipe & accès (mockup 15): who is in the workspace — name, address,
 * role, last sign-in — who is invited, and the means to invite, change a
 * role, remove a seat, revoke an invitation; and accepting one.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type TeamMember = components["schemas"]["TeamMemberRead"];
export type PendingInvitation = components["schemas"]["PendingInvitationRead"];
export type Role = TeamMember["role"];
export const ROLES: readonly Role[] = ["owner", "admin", "member"];

export const team = {
  members: () => apiFetch<TeamMember[]>("/team/members"),
  invitations: () => apiFetch<PendingInvitation[]>("/invitations"),
  invite: (email: string, role: Role) =>
    apiFetch<components["schemas"]["InvitationCreated"]>("/members/invite", {
      method: "POST",
      body: JSON.stringify({ email, role }),
    }),
  changeRole: (membershipId: string, role: Role) =>
    apiFetch<unknown>(`/members/${membershipId}`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    }),
  remove: (membershipId: string) => apiFetch<void>(`/members/${membershipId}`, { method: "DELETE" }),
  revoke: (invitationId: string) =>
    apiFetch<void>(`/invitations/${invitationId}`, { method: "DELETE" }),
  accept: (token: string) =>
    apiFetch<unknown>(`/invitations/${encodeURIComponent(token)}/accept`, {
      method: "POST",
      redirectOn401: false,
    }),
};

export function personName(member: Pick<TeamMember, "first_name" | "last_name" | "email">): string {
  return [member.first_name, member.last_name].filter(Boolean).join(" ") || member.email;
}

export function initials(member: Pick<TeamMember, "first_name" | "last_name" | "email">): string {
  const name = personName(member);
  const parts = name.includes("@") ? [name[0]] : name.split(/\s+/).map((p) => p[0]);
  return parts.slice(0, 2).join("").toUpperCase();
}
