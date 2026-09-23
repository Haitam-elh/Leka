/**
 * The variant this file is really guarding is `success`: before it existed,
 * the one caller that needed a positive-tone alert (the auth FormMessage)
 * built one by hand with raw `--state-success` classes instead of a variant
 * — which is the kind of thing that drifts the next time someone touches
 * the token. This pins the variant's own output, not that caller.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Alert, AlertDescription } from "@/components/ui/alert";

describe("Alert", () => {
  it("is announced as a role=alert region regardless of variant", () => {
    render(
      <Alert variant="success">
        <AlertDescription>Enregistré</AlertDescription>
      </Alert>
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Enregistré");
  });

  it("tints success with the state-success tokens, not the destructive ones", () => {
    render(<Alert variant="success" data-testid="alert" />);
    const alert = screen.getByTestId("alert");
    expect(alert).toHaveClass("bg-state-success-soft", "text-state-success");
    expect(alert).not.toHaveClass("text-destructive");
  });

  it("keeps destructive on its existing, quieter bg-card treatment", () => {
    render(<Alert variant="destructive" data-testid="alert" />);
    const alert = screen.getByTestId("alert");
    expect(alert).toHaveClass("bg-card", "text-destructive");
  });
});
