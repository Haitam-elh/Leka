"use client";

import { useRouter } from "next/navigation";

import { Form } from "@/components/forms/form";
import { IntentionComposer } from "@/components/intentions/intention-composer";
import { routes } from "@/config/routes";
import { useLekaForm } from "@/lib/forms/use-leka-form";
import { type IntentionDraft, intentionDraftSchema } from "@/lib/validation/intentions";

/**
 * "Que voulez-vous accomplir aujourd'hui ?" — the box on the overview.
 *
 * It does not submit an intention. It carries the sentence to the screen
 * that does, through the same `?q=` the command palette uses, so there is
 * one way into the composer and not two. Everything the full step then
 * needs — sources, scope, attachments — is decided there, where there is
 * room to decide it.
 */
export function CompactIntentionComposer() {
  const router = useRouter();

  const form = useLekaForm<IntentionDraft>({
    schema: intentionDraftSchema,
    defaultValues: { text: "" },
    onSubmit: (values) => {
      router.push(`${routes.intentionNew()}?q=${encodeURIComponent(values.text)}`);
    },
  });

  return (
    <Form form={form}>
      <IntentionComposer
        variant="compact"
        onSubmit={() => void form.submit()}
        // Files are attached on the full step, where there is room to list
        // them; the paperclip carries the sentence there as it is.
        onAttachRequest={() => {
          const text = form.getValues("text");
          router.push(
            text ? `${routes.intentionNew()}?q=${encodeURIComponent(text)}` : routes.intentionNew(),
          );
        }}
      />
    </Form>
  );
}
