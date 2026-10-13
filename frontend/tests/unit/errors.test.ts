import { describe, expect, it } from "vitest";
import { errorMessage } from "../../src/errors";

describe("errorMessage", () => {
  it("uses an Error message and a consistent fallback for unknown values", () => {
    expect(errorMessage(new Error("保存 failed"))).toBe("保存 failed");
    expect(errorMessage({ message: "not an Error" })).toBe("未知错误");
  });
});
