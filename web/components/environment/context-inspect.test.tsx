/**
 * One element of a context, inspected (LEKA-376):
 * components/environment/context-inspect.tsx.
 *
 * What these protect: how the element stood in each version — its rank,
 * absent, what changed of it, in words; what the version's quality says of
 * it; what people said of it; on asking only, the records it was read from
 * — their source, title or id, state, date, the start of their text, a way
 * to open them, gone said, a deleted source said — none said too, and a
 * role that may not read the sources told so.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { ElementEvidence, ElementInspection } from "@/lib/context";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const api = { inspect: vi.fn(), evidence: vi.fn() };

vi.mock("@/lib/context", async (original) => ({
  ...(await original<typeof import("@/lib/context")>()),
  contexts: api,
}));

const { ElementInspect } = await import("@/components/environment/context-inspect");

const CONTEXT = "5c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const PAYMENT = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const GITHUB = "2c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";

const INSPECTION = {
  context_id: CONTEXT,
  version: 3,
  element: { ref_id: PAYMENT, label: "payment-api" },
  quality: {
    gaps: [
      {
        kind: "undocumented",
        severity: "info",
        measure: "completeness",
        origin: "quality",
        said: "x",
        refs: [PAYMENT],
        detail: { entity: "payment-api" },
      },
    ],
    factors: [],
    conflicts: [
      {
        id: "attribute:p:sla",
        kind: "attribute",
        subject: PAYMENT,
        label: "payment-api",
        about: "sla",
        severity: "critical",
        why: "x",
        said: "x",
        refs: [PAYMENT],
      },
    ],
  },
  history: [
    {
      version: 3,
      trigger: "changed",
      status: "assembled",
      assembled_at: "2026-10-05T12:00:00Z",
      held: true,
      rank: 1,
      score: 1,
      changed: ["attributes.version"],
    },
    {
      version: 2,
      trigger: "compressed",
      status: "assembled",
      assembled_at: "2026-10-05T11:00:00Z",
      held: false,
      rank: null,
      score: null,
      changed: [],
    },
    {
      version: 1,
      trigger: "created",
      status: "assembled",
      assembled_at: "2026-10-05T10:00:00Z",
      held: true,
      rank: 2,
      score: 0.8,
      changed: [],
    },
  ],
  feedback: { useful: 2, not_useful: 0, wrong: 1, missing: 0 },
} as unknown as ElementInspection;

const EVIDENCE = {
  context_id: CONTEXT,
  version: 3,
  ref_id: PAYMENT,
  label: "payment-api",
  kind: "entity",
  records: [
    {
      source_id: GITHUB,
      source_name: "acme/backend",
      kind: "repositories",
      external_id: "acme/backend",
      title: "acme/backend",
      url: "https://github.com/acme/backend",
      state: "active",
      created_at: null,
      updated_at: "2026-10-04T09:00:00Z",
      excerpt: "Payments API service.",
      seen_at: "2026-10-05T09:00:00Z",
      gone: false,
    },
    {
      source_id: GITHUB,
      source_name: null,
      kind: "services",
      external_id: "PPAY01",
      title: null,
      url: null,
      state: null,
      created_at: null,
      updated_at: null,
      excerpt: null,
      seen_at: "2026-09-01T09:00:00Z",
      gone: true,
    },
  ],
  truncated: true,
} as unknown as ElementEvidence;

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ElementInspect contextId={CONTEXT} version={3} refId={PAYMENT} />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.inspect.mockResolvedValue(INSPECTION);
  api.evidence.mockResolvedValue(EVIDENCE);
});

describe("an element, inspected", () => {
  it("says how it stood in each version, what quality says, what people said", async () => {
    show();

    const history = within(await screen.findByTestId("element-history")).getAllByRole("listitem");
    expect(history.map((step) => step.textContent)).toEqual([
      "v3 · mise à jour par LEKA · n° 1 · modifié : version",
      "v2 · resserrée · absent",
      "v1 · créée · n° 2",
    ]);
    expect(api.inspect).toHaveBeenCalledWith(CONTEXT, PAYMENT, 3);
    expect(screen.getByTestId("element-quality")).toHaveTextContent(
      "Aucune page ne décrit payment-api.",
    );
    expect(screen.getByTestId("element-quality")).toHaveTextContent(
      "Désaccord sur sla (Critique)",
    );
    expect(screen.getByTestId("element-feedback-counts")).toHaveTextContent(
      "Retours : 2 utile(s) · 0 pas utile(s) · 1 faux",
    );
    // The records are read only when asked.
    expect(api.evidence).not.toHaveBeenCalled();
  });

  it("lists, asked, the records it was read from", async () => {
    const user = userEvent.setup();
    show();

    await user.click(await screen.findByRole("button", { name: "Voir les preuves" }));
    const evidence = await screen.findByTestId("element-evidence");
    expect(evidence).toHaveTextContent("Enregistrements des sources (2)");
    const [live, gone] = within(evidence).getAllByTestId("evidence-record");
    expect(live).toHaveTextContent("acme/backendacme/backend · active");
    expect(live).toHaveTextContent("Payments API service.");
    expect(within(live).getByRole("link", { name: "Ouvrir dans la source" })).toHaveAttribute(
      "href",
      "https://github.com/acme/backend",
    );
    expect(gone).toHaveAttribute("data-gone", "true");
    expect(gone).toHaveTextContent("PPAY01source supprimée depuisdisparu de la source");
    expect(evidence).toHaveTextContent("seuls les 2 plus récents sont listés");
  });

  it("says when none is kept, and when the role may not read the sources", async () => {
    const user = userEvent.setup();
    api.evidence.mockResolvedValueOnce({ ...EVIDENCE, records: [], truncated: false });
    const { unmount } = show();
    await user.click(await screen.findByRole("button", { name: "Voir les preuves" }));
    expect(
      await screen.findByText("Aucun enregistrement de source n'est gardé pour cet élément."),
    ).toBeVisible();
    unmount();

    api.evidence.mockRejectedValueOnce(new ApiError(403, "/context", "No."));
    show();
    await user.click(await screen.findByRole("button", { name: "Voir les preuves" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Votre rôle ne permet pas de lire les enregistrements des sources.",
    );
  });
});
