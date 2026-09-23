"use client";

import { useCallback, useEffect, useRef } from "react";
import { type FieldValues, type Path, useWatch } from "react-hook-form";

import { FormField, type FormFieldProps } from "@/components/forms/form-field";
import { Textarea } from "@/components/ui/textarea";

/**
 * Several lines of text, in a box that grows with them.
 *
 * It grows because the alternative is a fixed box with a scrollbar inside,
 * and someone writing an intention cannot see the sentence they just wrote.
 * It stops growing at `maxRows` because a box that swallows the page hides
 * the button that submits it.
 */
export function TextareaField<TFieldValues extends FieldValues, TName extends Path<TFieldValues>>({
  name,
  minRows = 3,
  maxRows = 12,
  max,
  placeholder,
  ...props
}: Omit<FormFieldProps<TFieldValues, TName>, "children" | "counter" | "name"> & {
  name: TName;
  minRows?: number;
  maxRows?: number;
  /** Shows `n / max` under the box, and warns near the limit. */
  max?: number;
  placeholder?: string;
}) {
  const value = useWatch({ name }) as unknown;
  const length = typeof value === "string" ? value.length : 0;

  return (
    <FormField
      {...props}
      name={name}
      counter={max === undefined ? undefined : { value: length, max }}
    >
      {({ field, invalid }) => (
        <AutoTextarea
          {...field}
          value={typeof field.value === "string" ? field.value : ""}
          minRows={minRows}
          maxRows={maxRows}
          placeholder={placeholder}
          aria-invalid={invalid || undefined}
        />
      )}
    </FormField>
  );
}

function AutoTextarea({
  minRows,
  maxRows,
  onChange,
  ...props
}: React.ComponentProps<typeof Textarea> & { minRows: number; maxRows: number }) {
  const ref = useRef<HTMLTextAreaElement | null>(null);

  const resize = useCallback(() => {
    const node = ref.current;
    if (node === null) return;
    const styles = window.getComputedStyle(node);
    // A line height of "normal" has no number to compute with; 1.5em of the
    // font size is what the cascade would have produced anyway.
    const line = Number.parseFloat(styles.lineHeight) || Number.parseFloat(styles.fontSize) * 1.5;
    const padding = Number.parseFloat(styles.paddingTop) + Number.parseFloat(styles.paddingBottom);

    // Measured from zero: scrollHeight never shrinks on its own, so a box
    // that once grew would never come back down as text is deleted.
    node.style.height = "auto";
    const wanted = node.scrollHeight;
    const min = line * minRows + padding;
    const max = line * maxRows + padding;
    node.style.height = `${Math.min(Math.max(wanted, min), max)}px`;
    node.style.overflowY = wanted > max ? "auto" : "hidden";
  }, [minRows, maxRows]);

  // Also on mount and on any value change from outside — a draft restored
  // from storage arrives without anyone typing.
  useEffect(resize, [resize, props.value]);

  return (
    <Textarea
      {...props}
      ref={ref}
      rows={minRows}
      onChange={(event) => {
        onChange?.(event);
        resize();
      }}
      className="resize-none"
    />
  );
}
