import { describe, expect, it } from "vitest";

import { createActivityMeter, IDLE_MS, MAX_REPORT_MS } from "@/lib/activity";

/**
 * The meter must never over-count: "a case takes N minutes by hand" is the claim
 * the Outcomes screen exists to measure, and an idle tab or a hidden page adding
 * time would inflate it in the one direction that misleads. Every test here drives
 * an explicit clock, so each assertion is an exact number of milliseconds.
 */
describe("createActivityMeter", () => {
  it("counts visible time while the person is active", () => {
    const meter = createActivityMeter(true, 0);
    meter.touch(10_000);
    expect(meter.drain(25_000)).toBe(25_000);
  });

  it("stops counting IDLE_MS after the last input", () => {
    const meter = createActivityMeter(true, 0);
    // Nobody touches it: the tab sits open for ten minutes.
    expect(meter.drain(600_000)).toBe(IDLE_MS);
  });

  it("resumes from the next input, not from when counting stopped", () => {
    const meter = createActivityMeter(true, 0);
    expect(meter.drain(300_000)).toBe(IDLE_MS);
    meter.touch(400_000);
    expect(meter.drain(410_000)).toBe(10_000);
  });

  it("counts nothing while the page is hidden", () => {
    const meter = createActivityMeter(true, 0);
    meter.hide(5_000);
    expect(meter.drain(50_000)).toBe(5_000);
    meter.touch(80_000);
    expect(meter.drain(90_000)).toBe(10_000);
  });

  it("counts nothing for a page that opened hidden until it is shown", () => {
    const meter = createActivityMeter(false, 0);
    expect(meter.drain(30_000)).toBe(0);
    meter.touch(40_000);
    expect(meter.drain(45_000)).toBe(5_000);
  });

  it("resets after each drain, so a span is reported once", () => {
    const meter = createActivityMeter(true, 0);
    expect(meter.drain(20_000)).toBe(20_000);
    expect(meter.drain(20_000)).toBe(0);
  });

  it("never reports more than the API accepts in one report", () => {
    const meter = createActivityMeter(true, 0);
    // Active input every 30s for ten minutes, but drained only once.
    for (let t = 30_000; t <= 600_000; t += 30_000) meter.touch(t);
    expect(meter.drain(600_000)).toBe(MAX_REPORT_MS);
  });
});
