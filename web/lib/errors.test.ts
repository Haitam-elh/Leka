import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";
import { classifyError } from "@/lib/errors";

/**
 * Which situation a failure puts someone in — the input to every error
 * message the interface shows, so every branch is pinned here.
 */
describe("classifying a failure", () => {
  it.each([
    ["the API could not be reached", new ApiError(0, "/x", "Cannot reach the API"), "unreachable"],
    ["a refusal", new ApiError(403, "/x", "no"), "forbidden"],
    ["a wrong address", new ApiError(404, "/x", "no"), "not-found"],
    ["our bug", new ApiError(500, "/x", "boom"), "server"],
    ["a gateway timing out", new ApiError(504, "/x", "timeout"), "server"],
    ["a request the API refused as invalid", new ApiError(422, "/x", "bad"), "unknown"],
    ["a crash in the page", new TypeError("x is undefined"), "unknown"],
    ["something that is not even an Error", "a string", "unknown"],
  ])("%s", (_label, error, kind) => {
    expect(classifyError(error, true).kind).toBe(kind);
  });

  it("puts being offline before anything the error says", () => {
    // A fetch that failed while offline looks exactly like our service
    // being down. Saying "our service is down" would send them to wait for
    // us instead of checking their connection.
    expect(classifyError(new ApiError(0, "/x", "Cannot reach"), false).kind).toBe("offline");
    expect(classifyError(new ApiError(500, "/x", "boom"), false).kind).toBe("offline");
  });

  it("keeps the request id, to quote to whoever investigates", () => {
    const error = new ApiError(500, "/x", "boom", undefined, undefined, "req-123");

    expect(classifyError(error, true)).toEqual({ kind: "server", reference: "req-123" });
  });
});
