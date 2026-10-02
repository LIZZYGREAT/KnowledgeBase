import { describe, expect, it } from "vitest";
import { errorMessage } from "../../src/errors";

describe("errorMessage", () => {
  it("uses an Error message and a consistent fallback for unknown values", () => {
    expect(errorMessage(new Error("Save failed"))).toBe("Save failed");
    expect(errorMessage({ message: "not an Error" })).toBe("未知错误");
  });
});
