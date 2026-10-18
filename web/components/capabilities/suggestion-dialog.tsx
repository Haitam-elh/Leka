"use client";

import { Plus } from "lucide-react";
import { useState } from "react";

import { Form } from "@/components/forms/form";
import { FormAlert } from "@/components/forms/form-alert";
import { TextareaField } from "@/components/forms/textarea-field";
import { TextField } from "@/components/forms/text-field";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ApiError } from "@/lib/api";
import { useLekaForm } from "@/lib/forms/use-leka-form";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { suggestions } from "@/lib/suggestions";
import { z } from "@/lib/validation";

/**
 * « Demander une compétence » (LEKA-501): the agent or skill someone wishes
 * LEKA had, sent to LEKA's team — not a new intention, nothing run. Said
 * received once kept; the same one twice, or too many in a day, said too.
 */

const schema = z.object({
  name: z.string().trim().min(3).max(120),
  problem: z.string().trim().min(10).max(2000),
  use_case: z.string().trim().min(10).max(2000),
  systems: z.string().trim().max(300),
  context: z.string().trim().max(4000),
});

type Values = z.infer<typeof schema>;

const EMPTY: Values = { name: "", problem: "", use_case: "", systems: "", context: "" };

export function SuggestCapability() {
  const t = useDictionary().catalogue;
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button className="mt-3" onClick={() => setOpen(true)} data-testid="catalogue-ask">
        <Plus className="size-4" aria-hidden="true" />
        {t.ask}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg" data-testid="suggestion-dialog">
          <DialogHeader>
            <DialogTitle>{t.suggestion.title}</DialogTitle>
            <DialogDescription>{t.suggestion.lead}</DialogDescription>
          </DialogHeader>
          {/* Mounted with the dialog: each opening starts empty, or on its success. */}
          {open ? <SuggestionForm onClose={() => setOpen(false)} /> : null}
        </DialogContent>
      </Dialog>
    </>
  );
}

function SuggestionForm({ onClose }: { onClose: () => void }) {
  const t = useDictionary().catalogue.suggestion;
  const [sent, setSent] = useState<string | null>(null);

  const form = useLekaForm<Values>({
    schema,
    defaultValues: EMPTY,
    onSubmit: async (values) => {
      try {
        const kept = await suggestions.send({
          name: values.name,
          problem: values.problem,
          use_case: values.use_case,
          systems: values.systems || null,
          context: values.context || null,
        });
        setSent(kept.id);
      } catch (caught) {
        // Said in words: the same one still open, or enough for today.
        const said = caught instanceof ApiError ? { 409: t.duplicate, 429: t.tooMany }[caught.status] : undefined;
        if (!said) throw caught;
        form.setError("root", { type: "server", message: said });
      }
    },
  });

  if (sent) {
    return (
      <div className="space-y-4" data-testid="suggestion-sent">
        <p className="text-sm text-brand-navy">{t.sent}</p>
        <p className="font-mono text-xs text-shell-muted">{sent}</p>
        <DialogFooter>
          <Button onClick={onClose}>{t.close}</Button>
        </DialogFooter>
      </div>
    );
  }

  return (
    <Form form={form} className="space-y-4">
      <FormAlert />
      <TextField<Values, "name"> name="name" label={t.name} placeholder={t.namePlaceholder} />
      <TextareaField<Values, "problem"> name="problem" label={t.problem} max={2000} />
      <TextareaField<Values, "use_case"> name="use_case" label={t.useCase} max={2000} />
      <TextField<Values, "systems">
        name="systems"
        label={t.systems}
        description={t.optional}
        placeholder={t.systemsPlaceholder}
      />
      <TextareaField<Values, "context"> name="context" label={t.context} description={t.optional} max={4000} />
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          {t.cancel}
        </Button>
        <Button type="submit" disabled={form.formState.isSubmitting} data-testid="suggestion-send">
          {t.send}
        </Button>
      </DialogFooter>
    </Form>
  );
}
