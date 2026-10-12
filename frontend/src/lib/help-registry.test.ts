import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { helpFor } from "@/lib/help-content";

/**
 * Every literal HelpDot id in the source resolves to an entry.
 *
 * HelpDot returns null for an id it cannot find, which is right at runtime -- a
 * missing explanation should not break a page -- and means a typo or a forgotten
 * entry is invisible: the dot just is not there, and no test that renders the
 * page can tell an absent dot from one that was never meant to be. So the ids are
 * read from the source instead. Template ids (`finding:${code}`) are data-driven
 * and checked where their data is.
 */

const SRC = path.resolve(__dirname, "..");
const LITERAL_ID = /<HelpDot\b[^>]*?\bid="([^"]+)"/g;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return sourceFiles(full);
    return /\.tsx$/.test(name) && !/\.test\.tsx$/.test(name) ? [full] : [];
  });
}

const found = sourceFiles(SRC).flatMap((file) =>
  [...readFileSync(file, "utf8").matchAll(LITERAL_ID)].map((m) => ({
    id: m[1],
    file: path.relative(SRC, file),
  })),
);

describe("literal HelpDot ids", () => {
  it("finds some, so an empty scan cannot pass vacuously", () => {
    // 17 when written; a broken regex or a moved src/ would find none.
    expect(found.length).toBeGreaterThanOrEqual(15);
  });

  it.each(found.map((f) => [f.id, f.file] as const))("%s (%s)", (id) => {
    expect(helpFor(id)).toBeDefined();
  });
});
