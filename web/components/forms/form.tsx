"use client";

import { type FieldValues, FormProvider } from "react-hook-form";

import { cn } from "cn";
import type { LekaForm } from "@/lib/forms/use-leka-form";

/**
 * The element every field in LEKA reads its form from.
 *
 * It exists so that a field can be written `<TextField name="name" … />`
 * with nothing else wired: the form travels down through context instead of
 * through a prop every level has to forward, which is what makes a field
 * moveable between screens.
 *
 * `noValidate` is not a detail. Without it the browser runs its own
 * validation first, in its own words, in the language of the operating
 * system rather than the one the person chose — and it stops the submit
 * before zod ever sees the values.
 */
export function Form<TValues extends FieldValues>({
  form,
  className,
  children,
  ...props
}: {
  form: LekaForm<TValues>;
  className?: string;
  children: React.ReactNode;
} & Omit<React.ComponentProps<"form">, "onSubmit" | "children">) {
  return (
    <FormProvider {...form}>
      <form
        noValidate
        onSubmit={(event) => void form.submit(event)}
        className={cn("space-y-6", className)}
        {...props}
      >
        {children}
      </form>
    </FormProvider>
  );
}
