"""What the files a change touches may use (2026-10-29), pure.

What these protect: the modules the files read import, found where their
imports say — relative, `@/` the importer's top folder — the most imported
first; a module said in a line, its exports and the variants its
components take; an import of no file, a variant no module declares, and a
key written twice into one object, each told to the writer; never a
function's parameters or a regular expression taken for an object.
"""

from __future__ import annotations

from leka.capabilities.code_names import (
    held_said,
    imported_by,
    invented_variants,
    resolved,
    unknown_imports,
    variants_of,
    written_twice,
)

BUTTON = """import { cva } from "class-variance-authority";

const buttonVariants = cva("inline-flex", {
  variants: {
    variant: {
      default: "bg-primary",
      outline: "border",
      "ghost-soft": "bg-transparent",
    },
    size: { sm: "h-8", lg: "h-10" },
  },
  defaultVariants: { variant: "default", size: "sm" },
});

export function Button({ variant, size, ...props }: Props) {
  return <button className={buttonVariants({ variant, size })} {...props} />;
}
export { buttonVariants };
"""
TREE = frozenset(
    {
        "web/components/ui/button.tsx",
        "web/components/overview/overview.tsx",
        "web/components/overview/cards.tsx",
        "web/lib/format/index.ts",
    }
)


def test_imports_are_found_where_they_say_the_most_imported_first() -> None:
    home = "web/components/overview/overview.tsx"
    assert resolved("@/components/ui/button", home, TREE) == "web/components/ui/button.tsx"
    assert resolved("./cards", home, TREE) == "web/components/overview/cards.tsx"
    assert resolved("@/lib/format", home, TREE) == "web/lib/format/index.ts"
    assert resolved("react", home, TREE) is None
    read = {
        home: 'import { Button } from "@/components/ui/button";\nimport { A } from "./cards";\n',
        "web/components/overview/cards.tsx": 'import { Button } from "@/components/ui/button";\n',
    }
    assert imported_by(read, TREE) == ["web/components/ui/button.tsx"]


def test_a_module_is_said_by_its_exports_and_its_variants() -> None:
    assert variants_of(BUTTON) == {
        "variant": ["default", "outline", "ghost-soft"],
        "size": ["sm", "lg"],
    }
    assert held_said(BUTTON) == (
        "exports Button, buttonVariants · variant: default | outline | ghost-soft · size: sm | lg"
    )


def test_an_import_of_no_file_and_a_variant_none_declares_are_told() -> None:
    home = "web/components/overview/overview.tsx"
    after = {
        home: (
            'import { Button } from "@/components/ui/button";\n'
            'import { Fancy } from "@/components/ui/fancy-card";\n'
            'import { New } from "./new-block";\n'
            'export const A = () => <Button variant="primary" size="lg">x</Button>;\n'
        )
    }
    [unknown] = unknown_imports(after, TREE, new=["web/components/overview/new-block.tsx"])
    assert unknown.startswith(f"{home} imports « @/components/ui/fancy-card », which is no file")
    variants = {"web/components/ui/button.tsx": variants_of(BUTTON)}
    [said] = invented_variants(after, TREE, variants)
    assert '<Button variant="primary">' in said and "default, outline, ghost-soft" in said
    kept = {home: after[home].replace('"primary"', '"outline"')}
    assert invented_variants(kept, TREE, variants) == []


def test_a_key_written_twice_into_one_object_is_told_never_parameters_or_a_pattern() -> None:
    # 2026-10-29, #450: three labels the dictionary held, added again (TS1117).
    before = 'const fr = {\n  home: {\n    allAgents: "Voir",\n    latest: "Dernières",\n  },\n};\n'
    after = before.replace("    latest:", '    latest: "x",\n    allAgents: "Voir tous",\n    old:')
    [said] = written_twice(before, after, "web/lib/i18n/dictionaries.ts")
    assert said.startswith("web/lib/i18n/dictionaries.ts: « allAgents » is written twice")
    assert "(line 5)" in said
    # The same name in two objects, a function's parameters, a pattern.
    fine = (
        "const a = { x: 1, inner: { x: 2 } };\n"
        "const api = { update: (id: string, body: B) => f(id, body),\n"
        "  remove: (id: string) => g(id) };\n"
        "text.replace(/\\{(\\w+)\\}/g, (whole, key: string) => key);\n"
    )
    assert written_twice("", fine, "web/lib/x.ts") == []
    assert written_twice(before, after, "api/x.py") == []
