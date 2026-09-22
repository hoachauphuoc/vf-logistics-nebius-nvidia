#!/usr/bin/env node
/**
 * Generate a VF_OPERATORS record.
 *
 *   node scripts/make-operator.mjs alice@forwarder.com
 *   node scripts/make-operator.mjs alice@forwarder.com "a password I chose"
 *   node scripts/make-operator.mjs alice@forwarder.com --out ./tmp
 *
 * With no password argument one is generated, which is the recommended path: the
 * console has no rate limit on login attempts beyond Cloud Run's own, so the
 * password's own strength is the defence.
 *
 * Prints the record and the password. The password is not recoverable from the
 * record -- that is the point of it -- so save it to a password manager now.
 *
 * `--out <dir>` writes `password.txt` and `record.txt` there and prints neither.
 * Use it when the values are going straight into Secret Manager: a secret passed
 * as a command-line argument is visible in the process list, and one echoed to a
 * terminal is in the scrollback and possibly in a transcript. Delete the
 * directory afterwards.
 *
 * Uses node:crypto rather than Web Crypto because this is a one-off script and
 * pbkdf2Sync is clearer. The output is identical: src/lib/operators.ts derives
 * PBKDF2-SHA256 with the same iteration count, salt and 32-byte length, so the
 * two agree by construction.
 */
import { pbkdf2Sync, randomBytes } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

/** Matches ITERATIONS_MIN's intent in src/lib/operators.ts -- the OWASP figure. */
const ITERATIONS = 210_000;
const SALT_BYTES = 16;
const KEY_BYTES = 32;

function b64url(buffer) {
  return buffer
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

const args = process.argv.slice(2);
const outIndex = args.indexOf("--out");
const outDir = outIndex === -1 ? null : args[outIndex + 1];
const positional = args.filter(
  (_, index) => index !== outIndex && index !== outIndex + 1,
);

const email = positional[0];
if (!email || !email.includes("@")) {
  console.error(
    "usage: node scripts/make-operator.mjs <email> [password] [--out <dir>]",
  );
  process.exit(1);
}
if (outIndex !== -1 && !outDir) {
  console.error("--out needs a directory");
  process.exit(1);
}

// 24 bytes of base64url is ~192 bits. Long enough that an offline attack on the
// PBKDF2 record is not the weak point.
const password = positional[1] ?? b64url(randomBytes(24));
const salt = randomBytes(SALT_BYTES);
const hash = pbkdf2Sync(password, salt, ITERATIONS, KEY_BYTES, "sha256");

const record = `${email.trim().toLowerCase()}:${ITERATIONS}:${b64url(salt)}:${b64url(hash)}`;

if (outDir) {
  mkdirSync(outDir, { recursive: true });
  // No trailing newline: these files are uploaded verbatim with
  // `gcloud secrets versions add --data-file=`, and a newline inside the secret
  // would become part of the password and part of the stored record.
  writeFileSync(join(outDir, "password.txt"), password, { encoding: "utf8" });
  writeFileSync(join(outDir, "record.txt"), record, { encoding: "utf8" });
  console.log(`Wrote password.txt and record.txt to ${outDir}`);
  console.log("Neither value was printed. Delete the directory when done.");
  process.exit(0);
}

console.log("");
console.log("Password (save this now -- it cannot be recovered):");
console.log(`  ${password}`);
console.log("");
console.log("VF_OPERATORS record:");
console.log(`  ${record}`);
console.log("");
console.log("Append to an existing VF_OPERATORS with a ';' separator.");
console.log("");
