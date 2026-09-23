/**
 * The system states: what each says, what it offers, and what it keeps quiet.
 *
 * The rules under test are the ones the ticket is about — a failure says what
 * to do next, never the error's own words; loading is not announced for a
 * load too short to notice; losing the connection is said once, politely,
 * and so is getting it back.
 */

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RouteState } from "@/components/shell/route-state";
import { ErrorState } from "@/components/states/error-state";
import { LoadingState } from "@/components/states/loading-state";
import { OfflineBanner } from "@/components/states/offline-banner";
import { ApiError } from "@/lib/api";
import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

const fr = DICTIONARIES.fr;

function mount(children: React.ReactNode) {
  return render(<LocaleProvider>{children}</LocaleProvider>);
}

/** Flip navigator.onLine and tell the page, as the browser does. */
function goOnline(online: boolean) {
  act(() => {
    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: online });
    window.dispatchEvent(new Event(online ? "online" : "offline"));
  });
}

beforeEach(() => {
  Object.defineProperty(window.navigator, "onLine", { configurable: true, value: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("an error state", () => {
  it("says what happened and what to do, never the error's own message", async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();
    mount(
      <ErrorState
        error={new ApiError(0, "/auth/me", "Cannot reach the API at http://localhost:8000")}
        onRetry={onRetry}
      />,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(fr.states.unreachableTitle);
    expect(alert).toHaveTextContent(fr.states.unreachableBody);
    expect(alert).not.toHaveTextContent("localhost");

    await user.click(screen.getByRole("button", { name: fr.states.retry }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("quotes the reference of a server error, so it can be found in the logs", () => {
    mount(
      <ErrorState
        error={new ApiError(500, "/x", "Traceback …", undefined, undefined, "req-4f2a")}
        onRetry={() => undefined}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(fr.states.serverTitle);
    expect(screen.getByText("Référence : req-4f2a")).toBeInTheDocument();
    expect(screen.queryByText(/Traceback/)).not.toBeInTheDocument();
  });

  it("does not offer to retry what would be refused again", () => {
    mount(<ErrorState error={new ApiError(403, "/x", "no")} onRetry={() => undefined} />);

    expect(screen.getByRole("alert")).toHaveTextContent(fr.states.forbiddenTitle);
    expect(screen.queryByRole("button", { name: fr.states.retry })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: fr.states.backToOverview })).toBeInTheDocument();
  });

  it("says offline when offline, and retries on its own once the connection is back", () => {
    const onRetry = vi.fn();
    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: false });
    mount(<ErrorState error={new ApiError(0, "/x", "x")} onRetry={onRetry} />);

    expect(screen.getByRole("alert")).toHaveTextContent(fr.states.offlineTitle);
    expect(onRetry).not.toHaveBeenCalled();

    goOnline(true);

    // The body promised "the page will reload on its own".
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("gives a page that stands for itself a level-one heading", () => {
    mount(<ErrorState error={new Error("x")} headingLevel={1} />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(fr.states.errorTitle);
  });
});

describe("a loading state", () => {
  it("shows and announces nothing for a load too short to notice", () => {
    vi.useFakeTimers();
    mount(<LoadingState />);

    const region = screen.getByRole("status");
    expect(region).toBeEmptyDOMElement();

    act(() => vi.advanceTimersByTime(250));
    expect(region).toHaveTextContent(fr.states.loading);
  });
});

describe("the offline banner", () => {
  it("appears when the connection goes, and says so again when it comes back", () => {
    vi.useFakeTimers();
    mount(<OfflineBanner />);
    const region = screen.getByRole("status");
    expect(region).toBeEmptyDOMElement();

    goOnline(false);
    expect(region).toHaveTextContent(fr.states.offlineBanner);

    goOnline(true);
    expect(region).toHaveTextContent(fr.states.backOnline);

    act(() => vi.advanceTimersByTime(4_100));
    expect(region).toBeEmptyDOMElement();
  });
});

describe("a route state", () => {
  it("is the page's title when it replaces the page", () => {
    mount(<RouteState variant="not-found" />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(fr.shell.notFoundTitle);
  });

  it("sits under the page's title when there is one", () => {
    mount(<RouteState variant="unavailable" />);

    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      fr.states.unavailableTitle,
    );
  });
});
