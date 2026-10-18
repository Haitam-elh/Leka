"use client";

import { Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";

import { useConfirm } from "@/components/interactions/confirm";
import { useRights } from "@/components/intentions/journey";
import { Button } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { ApiError } from "@/lib/api";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { IntentionDetail } from "@/lib/intentions/api";
import { useIntentionDelete } from "@/lib/intentions/queries";
import { notify } from "@/lib/notify";

/** « Supprimer l'analyse » (LEKA-487): whatever its status, to its asker or
 * who may approve; confirmed, saying what goes — then back to the history. */
export function DeleteIntention({ intention }: { intention: IntentionDetail }) {
  const w = useDictionary().intentions.actions;
  const confirm = useConfirm();
  const router = useRouter();
  const remove = useIntentionDelete(intention.id);
  const { yours, steward } = useRights(intention);
  if (!yours && !steward) return null;
  return (
    <Button
      type="button"
      variant="outline"
      className="text-state-danger"
      disabled={remove.isPending}
      data-testid="intention-delete"
      onClick={async () => {
        const ok = await confirm({
          title: w.deleteTitle,
          description: w.deleteBody,
          confirmLabel: w.deleteConfirm,
          destructive: true,
        });
        if (ok === null || ok === false) return;
        try {
          const said = await remove.mutateAsync();
          if (said.status === "pending") notify.info({ title: w.deletePending });
          else notify.success({ title: w.deleted });
          router.push(routes.intentions());
        } catch (error) {
          notify.error({ title: error instanceof ApiError ? error.message : w.deleteFailed });
        }
      }}
    >
      <Trash2 className="size-4" aria-hidden="true" />
      {w.delete}
    </Button>
  );
}

