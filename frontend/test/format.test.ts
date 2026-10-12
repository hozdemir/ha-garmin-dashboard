import { describe, expect, it } from "vitest";

import { formatCategory, formatDistance, formatNumber, goalProgress } from "../src/format";

const tr = { locale: "tr", lengthUnit: "km" };
const enMi = { locale: "en", lengthUnit: "mi" };

describe("format", () => {
  it("shows seconds instead of 0 minutes", () => {
    expect(formatNumber(tr, "duration", 24)).toBe("24 sn.");
  });
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

describe("categoryMessage", async () => {
  const { categoryMessage, translator } = await import("../src/i18n");
  it("translates known source enums in any casing", () => {
    expect(translator("tr")(categoryMessage("BALANCED")!)).toBe("Dengeli");
    expect(translator("tr")(categoryMessage("Detraining")!)).toBe("Form kaybı");
    expect(categoryMessage("NO_STATUS")).toBe("cat_no_status");
  });
  it("returns null for unknown values so the raw text is humanized instead", () => {
    expect(categoryMessage("Something new")).toBeNull();
  });
});

describe("formatSpeedOrPace", async () => {
  const { formatSpeedOrPace } = await import("../src/format");
  it("shows speed for rides and pace for runs", () => {
    expect(formatSpeedOrPace({ locale: "en", lengthUnit: "km" }, "road_biking", 6.6667)).toBe("24 km/h");
    expect(formatSpeedOrPace({ locale: "en", lengthUnit: "km" }, "running", 1000 / 330)).toBe("5:30 /km");
    expect(formatSpeedOrPace({ locale: "en", lengthUnit: "mi" }, "trail_running", 1609.344 / 600)).toBe("10:00 /mi");
  });
  it("never divides by zero", () => {
    expect(formatSpeedOrPace({ locale: "en", lengthUnit: "km" }, "running", 0)).toBe("—");
  });
});

describe("mass", async () => {
  const { formatNumber } = await import("../src/format");
  it("follows HA's mass unit", () => {
    expect(formatNumber({ locale: "en", lengthUnit: "km", massUnit: "kg" }, "mass", 74.3)).toBe("74.3 kg");
    expect(formatNumber({ locale: "en", lengthUnit: "mi", massUnit: "lb" }, "mass", 74.3)).toBe("163.8 lb");
  });
});
