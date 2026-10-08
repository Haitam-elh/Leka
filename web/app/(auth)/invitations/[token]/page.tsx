"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { buttonVariants } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { auth } from "@/lib/auth";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { team } from "@/lib/team";
import { workspace as workspaces } from "@/lib/workspace";

type State = "joining" | "signed-out" | "joined" | "failed";

/**
 * Accepting an invitation (Équipe & accès): signed in, the seat is taken and
 * the workspace becomes the active one; signed out, the way to sign in or
 * register — and back here after. One request per token, whoever asks (the
 * effect runs twice in development).
 */
const requests = new Map<string, Promise<unknown>>();

function acceptOnce(token: string): Promise<unknown> {
  let request = requests.get(token);
  if (!request) {
    request = team.accept(token).then(async (seat) => {
      const workspace = (seat as { workspace_id?: string }).workspace_id;
      if (workspace) await workspaces.enter(workspace);
      return seat;
    });
    requests.set(token, request);
  }
  return request;
}

export default function InvitationPage() {
  const t = useDictionary();
  const w = t.invitation;
  const params = useParams<{ token: string }>();
  const token = params.token ?? "";
  const back = `/invitations/${encodeURIComponent(token)}`;
  const [state, setState] = useState<State>("joining");

  useEffect(() => {
    let cancelled = false;
    auth.me({ redirectOn401: false }).then(
      () =>
        acceptOnce(token).then(
          () => !cancelled && setState("joined"),
          () => !cancelled && setState("failed"),
        ),
      (error: unknown) => {
        if (cancelled) return;
        setState(error instanceof ApiError && error.status === 401 ? "signed-out" : "failed");
      },
    );
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (state === "joining") {
    return <AuthCard title={w.title} description={w.joining}>{null}</AuthCard>;
  }
  if (state === "joined") {
    return (
      <AuthCard title={w.title} description={w.joined}>
        <Link href="/overview" className={buttonVariants({ className: "w-full" })} data-testid="invitation-open">
          {w.open}
        </Link>
      </AuthCard>
    );
  }
  if (state === "signed-out") {
    return (
      <AuthCard title={w.title} description={w.signIn}>
        <div className="flex flex-col gap-2">
          <Link
            href={`/login?next=${encodeURIComponent(back)}`}
            className={buttonVariants({ className: "w-full" })}
            data-testid="invitation-login"
          >
            {w.login}
          </Link>
          <Link
            href={`/register?next=${encodeURIComponent(back)}`}
            className={buttonVariants({ variant: "outline", className: "w-full" })}
          >
            {w.register}
          </Link>
        </div>
      </AuthCard>
    );
  }
  return (
    <AuthCard title={w.title} description={w.failed}>
      <Link href="/overview" className={buttonVariants({ variant: "outline", className: "w-full" })}>
        {w.open}
      </Link>
    </AuthCard>
  );
}
