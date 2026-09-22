/**
 * The console's operator list.
 *
 * There is no user table anywhere in this product -- the Firestore collections
 * are cases, events, audit_log, delegation_boundaries and prefilter_rules, and
 * adding a users collection is a larger change than putting a door on the
 * console. So operators live in one environment variable, which is honest about
 * what it is: enough for a handful of named people during pilots, and the thing
 * to replace when a customer's own staff need to log in.
 *
 * FORMAT of VF_OPERATORS -- records separated by `;`, fields by `:`
 *
 *   email:iterations:saltB64Url:hashB64Url;email:iterations:salt:hash
 *
 * An email cannot contain `:`, so the split is unambiguous. Generate records
 * with `node scripts/make-operator.mjs <email>`; never hand-write one.
 *
 * WHY PBKDF2 AND NOT A BARE SHA-256
 *
 * A bare digest of a password is a password: SHA-256 is designed to be fast, so
 * an offline guess costs nothing, and without a salt one leaked list cracks every
 * reused password at once. PBKDF2 with a per-record salt and a high iteration
 * count makes each guess expensive. 210,000 iterations of PBKDF2-SHA256 is the
 * OWASP figure. Web Crypto rather than node:crypto for consistency with
 * session.ts, which must run on the Edge runtime.
 */

const ITERATIONS_MIN = 100_000;
const KEY_BITS = 256;

export type OperatorRecord = {
  email: string;
  iterations: number;
  salt: Uint8Array;
  hash: Uint8Array;
};

function b64urlDecode(text: string): Uint8Array {
  const padded = text.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

/**
 * Parse VF_OPERATORS.
 *
 * A malformed record is skipped rather than throwing, and an under-strength
 * iteration count is treated as malformed -- a record that cannot be trusted
 * should not be able to authenticate anyone, and one bad entry should not lock
 * out the others. Note the consequence: a typo in this variable presents as
 * "that person cannot log in", so verify a new record works before relying on it.
 */
export function operators(): OperatorRecord[] {
  const raw = process.env.VF_OPERATORS;
  if (!raw) return [];

  const records: OperatorRecord[] = [];
  for (const entry of raw.split(";")) {
    const trimmed = entry.trim();
    if (!trimmed) continue;

    const parts = trimmed.split(":");
    if (parts.length !== 4) continue;

    const [email, iterationsText, saltText, hashText] = parts;
    const iterations = Number.parseInt(iterationsText, 10);
    if (!email.includes("@")) continue;
    if (!Number.isFinite(iterations) || iterations < ITERATIONS_MIN) continue;

    try {
      records.push({
        // Normalised so a capitalised login matches the stored record. Emails are
        // not case-sensitive in practice and a rejected login over letter case is
        // a support ticket, not a security gain.
        email: email.trim().toLowerCase(),
        iterations,
        salt: b64urlDecode(saltText),
        hash: b64urlDecode(hashText),
      });
    } catch {
      continue;
    }
  }
  return records;
}

async function derive(
  password: string,
  salt: Uint8Array,
  iterations: number,
): Promise<Uint8Array> {
  const material = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"],
  );
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt: salt as BufferSource, iterations, hash: "SHA-256" },
    material,
    KEY_BITS,
  );
  return new Uint8Array(bits);
}

function sameBytes(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a[i] ^ b[i];
  return diff === 0;
}

/**
 * Check a login and return the canonical email, or null.
 *
 * Derives against a decoy record when the email is unknown, so a wrong address
 * and a wrong password take the same time. Without that, response timing
 * enumerates who has an account -- which for a product sold to named freight
 * forwarders also leaks the customer list.
 */
export async function verifyOperator(
  email: string,
  password: string,
): Promise<string | null> {
  const wanted = email.trim().toLowerCase();
  const all = operators();
  const found = all.find((record) => record.email === wanted);

  const record =
    found ??
    all[0] ??
    // Nothing configured at all: still derive, still refuse. An early return here
    // would make "no operators configured" measurably faster than "wrong
    // password", and the whole point of this branch is to be indistinguishable.
    {
      email: "",
      iterations: 210_000,
      salt: new Uint8Array(16),
      hash: new Uint8Array(32),
    };

  const derived = await derive(password, record.salt, record.iterations);
  const matches = sameBytes(derived, record.hash);

  return found && matches ? found.email : null;
}
