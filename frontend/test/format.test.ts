import { describe, expect, it } from "vitest";

import { formatCategory, formatDistance, formatNumber, goalProgress } from "../src/format";

const tr = { locale: "tr", lengthUnit: "km" };
const enMi = { locale: "en", lengthUnit: "mi" };

describe("format", () => {
  it("uses unambiguous Turkish duration units", () => {
    expect(formatNumber(tr, "duration", 4 * 3600 + 16 * 60)).toBe("4 sa. 16 dk.");
  });
  it("converts meters to the HA length unit", () => {
    expect(formatDistance(tr, 6200)).toBe("6,2 km");
    expect(formatDistance(enMi, 1609.344)).toBe("1 mi");
  });
  it("formats durations in hours and minutes", () => {
    expect(formatNumber({ locale: "en", lengthUnit: "km" }, "duration", 7 * 3600 + 32 * 60)).toBe("7 hr 32 min");
  });
  it("humanizes source enum text", () => {
    expect(formatCategory("BALANCED")).toBe("Balanced");
    expect(formatCategory("NO_STATUS")).toBe("No status");
  });
  it("lets progress exceed 100% while the bar stops at 100", () => {
    expect(goalProgress(15000, 10000)).toEqual({ percent: 150, bar: 100 });
    expect(goalProgress(500, 0)).toBeNull();
  });
});
