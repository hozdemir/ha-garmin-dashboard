import { describe, expect, it } from "vitest";

import {
  barWidth,
  extent,
  hasData,
  linePath,
  linearScale,
  nearestIndex,
  niceTicks,
  segments,
  ticksForKind,
  type ChartPayload,
  type Point,
} from "../src/chart-data";

describe("niceTicks", () => {
  it("returns round steps covering the range", () => {
    expect(niceTicks(52, 64)).toEqual([50, 55, 60, 65]);
  });
  it("handles a flat series", () => {
    expect(niceTicks(50, 50).length).toBeGreaterThan(1);
  });
  it("ignores non-finite input", () => {
    expect(niceTicks(NaN, 3)).toEqual([]);
  });
});

describe("ticksForKind", () => {
  it("ticks durations on whole hours", () => {
    for (const t of ticksForKind("duration", 5.5 * 3600, 8.2 * 3600)) expect(t % 3600).toBe(0);
  });
  it("anchors percentages at 0..100", () => {
    const ticks = ticksForKind("percent", 20, 70);
    expect(ticks[0]).toBe(0);
    expect(ticks[ticks.length - 1]).toBeGreaterThanOrEqual(100);
  });
});

describe("segments", () => {
  it("splits runs at gaps and never invents zeros", () => {
    const points: Point[] = [[1, 5], [2, 6], [3, null], [4, 7]];
    expect(segments(points)).toEqual([[[1, 5], [2, 6]], [[4, 7]]]);
  });
});

describe("linePath", () => {
  const x = linearScale([0, 10], [0, 100]);
  const y = linearScale([0, 10], [100, 0]);
  it("draws straight segments", () => {
    expect(linePath([[0, 0], [10, 10]], x, y)).toBe("M0.0,100.0L100.0,0.0");
  });
  it("draws steps that hold the old value until the change", () => {
    expect(linePath([[0, 0], [10, 10]], x, y, true)).toBe("M0.0,100.0H100.0V0.0");
  });
});

describe("nearestIndex", () => {
  it("skips gaps", () => {
    const points: Point[] = [[0, 1], [10, null], [20, 3]];
    expect(nearestIndex(points, 11)).toBe(2);
  });
  it("returns -1 for an empty series", () => {
    expect(nearestIndex([], 5)).toBe(-1);
  });
});

describe("extent and data checks", () => {
  const payload: ChartPayload = {
    chart_id: "c", group: "trends", form: "line", method: "change_points", range_days: 7,
    start: "", end: "", series: [{ metric: "m", kind: "count", unit: null, points: [[0, null]] }],
  };
  it("treats an all-gap series as no data", () => {
    expect(hasData(payload)).toBe(false);
    expect(extent(payload.series)).toBeNull();
  });
  it("includes the goal in the extent", () => {
    expect(extent([{ metric: "m", kind: "count", unit: null, points: [[0, 10]] }], [100])).toEqual([10, 100]);
  });
  it("caps bar width at 24px", () => {
    expect(barWidth(1000, 7)).toBe(24);
    expect(barWidth(300, 90)).toBe(2);
  });
});
