/**
 * The browser tab (LEKA-369): a page that knows what it shows names the
 * tab, and the name goes when the page does.
 */

import { act, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { useNamePage } from "@/lib/navigation/page-name";

const ID = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const PATH = `/environment/services/${ID}`;

vi.mock("next/navigation", () => ({ usePathname: () => PATH }));

const { DocumentTitle } = await import("@/components/shell/document-title");

function Sheet({ name }: { name?: string }) {
  useNamePage(PATH, name);
  return null;
}

describe("the document title", () => {
  it("names the entity once its page knows it, and forgets it with the page", async () => {
    const { rerender } = render(
      <LocaleProvider>
        <DocumentTitle />
        <Sheet />
      </LocaleProvider>,
    );
    // Until the API answers, the identifier made presentable.
    expect(document.title).not.toContain("Payment API");

    await act(async () =>
      rerender(
        <LocaleProvider>
          <DocumentTitle />
          <Sheet name="Payment API" />
        </LocaleProvider>,
      ),
    );
    expect(document.title).toBe("Payment API · LEKA");

    await act(async () =>
      rerender(
        <LocaleProvider>
          <DocumentTitle />
        </LocaleProvider>,
      ),
    );
    expect(document.title).not.toContain("Payment API");
  });
});
