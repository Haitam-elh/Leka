"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useRef } from "react";

import { Form } from "@/components/forms/form";
import { FormAlert } from "@/components/forms/form-alert";
import { useAttachments } from "@/components/intentions/attachments";
import { IntentionComposer } from "@/components/intentions/intention-composer";
import { routes } from "@/config/routes";
import { ApiError } from "@/lib/api";
import { useLekaForm } from "@/lib/forms/use-leka-form";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { intentAsk, submitIntention } from "@/lib/intentions/api";
import { intentionKeys } from "@/lib/intentions/queries";
import { type IntentionDraft, intentionDraftSchema } from "@/lib/validation/intentions";

/**
 * "Que voulez-vous accomplir aujourd'hui ?" — the box on the overview.
 *
 * What is typed here is asked here (2026-10-14: carried to another screen
 * to be asked again, it read as « ça ne marche pas »): the intention is
 * made — every source, every environment, as the full step does by
 * default — and its page opens on its analysis. A request LEKA cannot take
 * — about anything but technology, or naming nothing it knows — is said
 * above the box. Its files are attached here: sent as they are chosen, and
 * only those kept go with it — refused, the words and the files stay.
 */
export function CompactIntentionComposer() {
  const router = useRouter();
  const t = useDictionary();
  const client = useQueryClient();
  // One key per request — its words and its files (LEKA-443): pressed
  // twice, it is one intention.
  const requestKey = useRef<{ said: string; key: string } | null>(null);
  const files = useAttachments();

  const form = useLekaForm<IntentionDraft>({
    schema: intentionDraftSchema,
    defaultValues: { text: "" },
    onSubmit: async (values) => {
      const ask = intentAsk(
        {
          text: values.text,
          sources: [],
          environment: "all",
          period: { preset: "7d", range: { from: "", to: "" } },
          services: [],
          attachments: [],
        },
        { everySource: true, periodChosen: false },
      );
      const attachments = files.ids;
      const said = JSON.stringify([ask.text, attachments]);
      if (requestKey.current?.said !== said) {
        requestKey.current = { said, key: crypto.randomUUID() };
      }
      try {
        const made = await submitIntention(
          attachments.length ? { ...ask, attachments } : ask,
          requestKey.current.key,
        );
        files.clear();
        client.setQueryData(intentionKeys.one(made.intention.id), made.intention);
        void client.invalidateQueries({ queryKey: intentionKeys.all });
        router.push(`${routes.intentions()}/${made.intention.id}`);
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 422) {
          form.setError("root", {
            type: "server",
            message:
              caught.fieldErrors?.attachments === "attachment_unknown"
                ? t.composer.files.unknown
                : caught.code === "off_topic"
                  ? t.intentions.brief.offTopic
                  : t.intent.nothing,
          });
          return;
        }
        throw caught;
      }
    },
  });

  return (
    <Form form={form} className="space-y-3">
      <FormAlert />
      <IntentionComposer
        variant="compact"
        onSubmit={() => void form.submit()}
        // Creating the intention takes seconds: the button says it is working.
        submitting={form.formState.isSubmitting}
        files={files}
      />
    </Form>
  );
}
