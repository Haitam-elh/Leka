/**
 * A connector's form, read from the JSON Schemas the catalogue sends.
 *
 * The backend owns the settings of each connector (its Pydantic models); the
 * screen owns none. A connector added on the API side gets its form here
 * without a line of frontend — the schema says which fields exist, which
 * are required, how long they may be, and which are secret.
 *
 * What the schema cannot say is in the product's language: the labels and
 * help of the fields we know are in the dictionary (`sources.fields`), and
 * a field we do not know falls back to the schema's title.
 *
 * The list fields — `repositories`, `projects` — are not typed here: they
 * are the scope, chosen from what the vendor lists, in the wizard's next
 * step. A whole number — a database's port — is typed as text, with the
 * phone's digit keyboard, and sent as text: the API reads "5432" as 5432.
 */

import { z } from "@/lib/validation";

type JsonSchema = {
  type?: string;
  format?: string;
  title?: string;
  default?: unknown;
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  writeOnly?: boolean;
  anyOf?: JsonSchema[];
  items?: JsonSchema;
};

export interface FieldSpec {
  name: string;
  title: string;
  kind: "text" | "url" | "password" | "number";
  required: boolean;
  default: string;
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
}

/** `str | None` arrives as anyOf [string, null]: the string is the field. */
function concrete(schema: JsonSchema): JsonSchema {
  return schema.anyOf?.find((option) => option.type !== "null") ?? schema;
}

function propertiesOf(schema: Record<string, unknown>): [string, JsonSchema][] {
  return Object.entries((schema.properties ?? {}) as Record<string, JsonSchema>);
}

/** The typed fields of one schema — config or credentials. */
export function fieldsOf(schema: Record<string, unknown>): FieldSpec[] {
  const required = new Set((schema.required as string[] | undefined) ?? []);
  return propertiesOf(schema)
    .filter(([, property]) => ["string", "integer"].includes(concrete(property).type ?? ""))
    .map(([name, property]) => {
      const inner = concrete(property);
      const secret = inner.format === "password" || inner.writeOnly === true;
      const whole = inner.type === "integer";
      return {
        name,
        title: property.title ?? name,
        kind: whole ? "number" : secret ? "password" : inner.format === "uri" ? "url" : "text",
        required: required.has(name),
        default: ["string", "number"].includes(typeof property.default)
          ? String(property.default)
          : "",
        minLength: inner.minLength,
        maxLength: inner.maxLength,
        minimum: inner.minimum,
        maximum: inner.maximum,
      };
    });
}

/** The config's list of what to read — `repositories`, `projects` — if any. */
export function scopeFieldOf(schema: Record<string, unknown>): string | null {
  const found = propertiesOf(schema).find(([, property]) => concrete(property).type === "array");
  return found ? found[0] : null;
}

/**
 * The validation of a set of fields. An optional field may stay empty;
 * `keepSecrets` lets a secret stay empty too, to keep the stored one.
 */
export function zodOf(fields: FieldSpec[], { keepSecrets = false } = {}) {
  const shape: Record<string, z.ZodType<string, string>> = {};
  for (const field of fields) {
    let rule = z.string().trim();
    if (field.maxLength !== undefined) rule = rule.max(field.maxLength);
    const mayBeEmpty = !field.required || (keepSecrets && field.kind === "password");
    if (field.kind === "url") {
      shape[field.name] = mayBeEmpty ? z.union([z.literal(""), z.url()]) : z.url();
      continue;
    }
    if (field.kind === "number") {
      const whole = wholeNumber(field.minimum, field.maximum);
      shape[field.name] = mayBeEmpty ? z.union([z.literal(""), whole]) : whole;
      continue;
    }
    const least = field.minLength ?? 1;
    // An empty value is allowed, or a long enough one — never a short one.
    shape[field.name] = mayBeEmpty ? z.union([z.literal(""), rule.min(least)]) : rule.min(least);
  }
  return z.object(shape);
}

/** Digits, within the schema's bounds — said as a number's bounds are. */
function wholeNumber(minimum?: number, maximum?: number) {
  return z
    .string()
    .trim()
    .regex(/^\d{1,15}$/)
    .superRefine((value, context) => {
      const number = Number(value);
      if (minimum !== undefined && number < minimum) {
        context.addIssue({
          code: "too_small",
          origin: "number",
          minimum,
          inclusive: true,
          input: value,
        });
      }
      if (maximum !== undefined && number > maximum) {
        context.addIssue({
          code: "too_big",
          origin: "number",
          maximum,
          inclusive: true,
          input: value,
        });
      }
    });
}

export function defaultsOf(fields: FieldSpec[]): Record<string, string> {
  return Object.fromEntries(fields.map((field) => [field.name, field.default]));
}

/** What the API takes: an empty field is left out, so its default applies. */
export function filled(values: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(values).filter(([, value]) => value.trim() !== ""));
}
