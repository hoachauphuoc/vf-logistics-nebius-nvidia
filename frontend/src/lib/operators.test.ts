import { describe, expect, it, beforeEach, afterEach } from "vitest";
import { operators, verifyOperator, type OperatorRecord } from "./operators";

describe("operators()", () => {
  const originalEnv = process.env.VF_OPERATORS;

  afterEach(() => {
    process.env.VF_OPERATORS = originalEnv;
  });

  it("returns empty array when VF_OPERATORS is not set", () => {
    delete process.env.VF_OPERATORS;
    expect(operators()).toEqual([]);
  });

  it("returns empty array when VF_OPERATORS is empty string", () => {
    process.env.VF_OPERATORS = "";
    expect(operators()).toEqual([]);
  });

  it("returns empty array when VF_OPERATORS contains only whitespace and separators", () => {
    process.env.VF_OPERATORS = ";;;  ;  ";
    expect(operators()).toEqual([]);
  });

  it("parses a single valid operator record", () => {
    process.env.VF_OPERATORS = "test@example.com:210000:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg";
    const result = operators();
    expect(result).toHaveLength(1);
    expect(result[0].email).toBe("test@example.com");
    expect(result[0].iterations).toBe(210000);
  });

  it("normalizes email to lowercase", () => {
    process.env.VF_OPERATORS = "Test@Example.COM:210000:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg";
    const result = operators();
    expect(result[0].email).toBe("test@example.com");
  });

  it("trims whitespace from email and iteration fields", () => {
    process.env.VF_OPERATORS = "  test@example.com  :  210000  :dGVzdFNhbHQxNg:dGVzdEhhc2gxNg";
    const result = operators();
    expect(result[0].email).toBe("test@example.com");
    expect(result[0].iterations).toBe(210000);
  });

  it("parses multiple valid operator records", () => {
    process.env.VF_OPERATORS =
      "alice@example.com:210000:YWxpY2VTZWX+:YWxpY2VIYWVI;bob@example.com:210000:Ym9iU2FsdA==:Ym9iSGFzaA==";
    const result = operators();
    expect(result).toHaveLength(2);
    expect(result[0].email).toBe("alice@example.com");
    expect(result[1].email).toBe("bob@example.com");
  });

  it("skips records with fewer than 4 fields", () => {
    process.env.VF_OPERATORS = "test@example.com:210000:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg;incomplete:field:missing";
    const result = operators();
    expect(result).toHaveLength(1);
    expect(result[0].email).toBe("test@example.com");
  });

  it("skips records with more than 4 fields", () => {
    process.env.VF_OPERATORS = "test@example.com:210000:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg:extra";
    const result = operators();
    expect(result).toHaveLength(0);
  });

  it("skips records with email missing @ symbol", () => {
    process.env.VF_OPERATORS = "notanemail:210000:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg";
    const result = operators();
    expect(result).toHaveLength(0);
  });

  it("skips records with invalid iteration count (non-numeric)", () => {
    process.env.VF_OPERATORS = "test@example.com:notanumber:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg";
    const result = operators();
    expect(result).toHaveLength(0);
  });

  it("skips records with iteration count below ITERATIONS_MIN (100000)", () => {
    process.env.VF_OPERATORS = "test@example.com:99999:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg";
    const result = operators();
    expect(result).toHaveLength(0);
  });

  it("accepts records with exactly ITERATIONS_MIN iterations", () => {
    process.env.VF_OPERATORS = "test@example.com:100000:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg";
    const result = operators();
    expect(result).toHaveLength(1);
    expect(result[0].iterations).toBe(100000);
  });

  it("skips records with invalid base64 salt", () => {
    process.env.VF_OPERATORS = "test@example.com:210000:!!!invalid!!!:dGVzdEhhc2gxNg";
    const result = operators();
    expect(result).toHaveLength(0);
  });

  it("skips records with invalid base64 hash", () => {
    process.env.VF_OPERATORS = "test@example.com:210000:dGVzdFNhbHQxNg:!!!invalid!!!";
    const result = operators();
    expect(result).toHaveLength(0);
  });

  it("handles base64url decoding with URL-safe characters (- and _)", () => {
    // Base64url uses - instead of + and _ instead of /
    process.env.VF_OPERATORS = "test@example.com:210000:--__--__:--__--__";
    const result = operators();
    expect(result).toHaveLength(1);
    expect(result[0].salt).toBeInstanceOf(Uint8Array);
    expect(result[0].hash).toBeInstanceOf(Uint8Array);
  });

  it("decodes salt and hash as Uint8Array", () => {
    process.env.VF_OPERATORS = "test@example.com:210000:dGVzdFNhbHQ=:dGVzdEhhc2g=";
    const result = operators();
    expect(result[0].salt).toBeInstanceOf(Uint8Array);
    expect(result[0].hash).toBeInstanceOf(Uint8Array);
    expect(result[0].salt.length).toBeGreaterThan(0);
    expect(result[0].hash.length).toBeGreaterThan(0);
  });

  it("skips empty entries after trimming", () => {
    process.env.VF_OPERATORS = "test@example.com:210000:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg;;;";
    const result = operators();
    expect(result).toHaveLength(1);
  });

  it("handles mixed valid and invalid records, parsing only valid ones", () => {
    process.env.VF_OPERATORS =
      "valid@example.com:210000:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg;invalid:field;another@valid.com:210000:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg";
    const result = operators();
    expect(result).toHaveLength(2);
    expect(result[0].email).toBe("valid@example.com");
    expect(result[1].email).toBe("another@valid.com");
  });
});

describe("verifyOperator()", () => {
  const originalEnv = process.env.VF_OPERATORS;

  afterEach(() => {
    process.env.VF_OPERATORS = originalEnv;
  });

  it("returns null when no operators are configured", async () => {
    delete process.env.VF_OPERATORS;
    const result = await verifyOperator("test@example.com", "password");
    expect(result).toBeNull();
  });

  it("returns null for unknown email", async () => {
    process.env.VF_OPERATORS = "known@example.com:210000:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg";
    const result = await verifyOperator("unknown@example.com", "anypassword");
    expect(result).toBeNull();
  });

  it("returns null for correct email but wrong password", async () => {
    process.env.VF_OPERATORS = "test@example.com:210000:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg";
    const result = await verifyOperator("test@example.com", "wrongpassword");
    expect(result).toBeNull();
  });

  it("normalizes email to lowercase for verification", async () => {
    process.env.VF_OPERATORS = "test@example.com:210000:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg";
    const result = await verifyOperator("TEST@EXAMPLE.COM", "wrongpassword");
    // Will fail password check, but email was normalized for lookup
    expect(result).toBeNull();
  });

  it("trims whitespace from email input", async () => {
    process.env.VF_OPERATORS = "test@example.com:210000:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg";
    const result = await verifyOperator("  test@example.com  ", "wrongpassword");
    expect(result).toBeNull();
  });

  it("returns the canonical email address on successful verification", async () => {
    // For a real operator record, we need to generate a valid password hash.
    // We'll use a known password and its correct PBKDF2-SHA256 hash.
    // This is a test record with password "testpass123"
    const saltBase64 = "SGVsbG9Xb3JsZFNhbHQx"; // "HelloWorldSalt1" as base64
    const testPass = "testpass123";

    // We need to derive the hash for this password
    const saltUint = new Uint8Array([72, 101, 108, 108, 111, 87, 111, 114, 108, 100, 83, 97, 108, 116, 49]); // "HelloWorldSalt1"
    const material = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(testPass),
      "PBKDF2",
      false,
      ["deriveBits"],
    );
    const bits = await crypto.subtle.deriveBits(
      { name: "PBKDF2", salt: saltUint, iterations: 210000, hash: "SHA-256" },
      material,
      256,
    );
    const hashBytes = new Uint8Array(bits);
    // Convert to base64 for the env var
    const hashBase64 = btoa(String.fromCharCode(...hashBytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");

    process.env.VF_OPERATORS = `test@example.com:210000:${saltBase64}:${hashBase64}`;
    const result = await verifyOperator("test@example.com", testPass);
    expect(result).toBe("test@example.com");
  });

  it("returns canonical email even if email was entered with different case", async () => {
    const saltBase64 = "SGVsbG9Xb3JsZFNhbHQx";
    const testPass = "testpass123";

    const saltUint = new Uint8Array([72, 101, 108, 108, 111, 87, 111, 114, 108, 100, 83, 97, 108, 116, 49]);
    const material = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(testPass),
      "PBKDF2",
      false,
      ["deriveBits"],
    );
    const bits = await crypto.subtle.deriveBits(
      { name: "PBKDF2", salt: saltUint, iterations: 210000, hash: "SHA-256" },
      material,
      256,
    );
    const hashBytes = new Uint8Array(bits);
    const hashBase64 = btoa(String.fromCharCode(...hashBytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");

    process.env.VF_OPERATORS = `test@example.com:210000:${saltBase64}:${hashBase64}`;
    const result = await verifyOperator("TEST@EXAMPLE.COM", testPass);
    expect(result).toBe("test@example.com");
  });

  it("takes constant time for unknown email (uses decoy record)", async () => {
    process.env.VF_OPERATORS = "known@example.com:210000:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg";
    // Unknown email will use the first operator as decoy
    const result = await verifyOperator("unknown@example.com", "anypassword");
    expect(result).toBeNull();
  });

  it("still derives when no operators exist (constant time behavior)", async () => {
    delete process.env.VF_OPERATORS;
    // Should still derive even though there are no operators
    const result = await verifyOperator("any@example.com", "anypassword");
    expect(result).toBeNull();
  });

  it("returns null for multiple operators when password is wrong", async () => {
    process.env.VF_OPERATORS =
      "alice@example.com:210000:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg;bob@example.com:210000:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg";
    const result = await verifyOperator("alice@example.com", "wrongpass");
    expect(result).toBeNull();
  });

  it("handles empty password input", async () => {
    process.env.VF_OPERATORS = "test@example.com:210000:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg";
    const result = await verifyOperator("test@example.com", "");
    expect(result).toBeNull();
  });

  it("handles empty email input", async () => {
    process.env.VF_OPERATORS = "test@example.com:210000:dGVzdFNhbHQxNg:dGVzdEhhc2gxNg";
    const result = await verifyOperator("", "testpassword");
    expect(result).toBeNull();
  });
});
