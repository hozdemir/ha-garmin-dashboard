import { describe, expect, it } from "vitest";

import { projectRoute } from "../src/route-geometry";

describe("projectRoute", () => {
  it("keeps true proportions using cos(latitude)", () => {
    // ~1 km east and ~1 km north at 60°N: lon span is twice the lat span.
    const p = projectRoute([[60, 10], [60.009, 10.018]], 400, 1000, 0)!;
    const dx = p.end[0] - p.start[0];
    const dy = p.start[1] - p.end[1];
    expect(Math.abs(dx / dy - 1)).toBeLessThan(0.01);
  });
  it("puts north up and fits inside the box", () => {
    const p = projectRoute([[41, 29], [41.1, 29.1]], 300, 200)!;
    expect(p.end[1]).toBeLessThan(p.start[1]);
    for (const [x, y] of [p.start, p.end]) {
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(300);
      expect(y).toBeLessThanOrEqual(p.height);
    }
    expect(p.height).toBeLessThanOrEqual(200);
  });
  it("handles a straight north-south or single-spot track", () => {
    expect(projectRoute([[41, 29], [41.1, 29]], 300, 200)).not.toBeNull();
    expect(projectRoute([[41, 29], [41, 29]], 300, 200)).not.toBeNull();
  });
  it("needs two points", () => {
    expect(projectRoute([[41, 29]], 300, 200)).toBeNull();
  });
});
