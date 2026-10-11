/**
 * Plurals, numbers and dates in the language the screens speak and the
 * person's region — the browser's own Intl, which knows every language of
 * the catalogue's rules: one and other in English, one for 0 and 1 in
 * French, few and many in Polish or Russian, six forms in Arabic.
 */

export type PluralForms = Partial<Record<Intl.LDMLPluralRule, string>> & { other: string };

/** The form of a word for a count, by the language's own rules: `{n}` in
 * it becomes the count, written as that language writes numbers. */
export function plural(locale: string, count: number, forms: PluralForms): string {
  const rule = new Intl.PluralRules(locale).select(count);
  const template = forms[rule] ?? forms.other;
  return template.replace("{n}", new Intl.NumberFormat(locale).format(count));
}
