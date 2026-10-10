// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { signSession } from "@/lib/session";

import { GET, POST, PUT } from "./route";

/**
 * The BFF's credential rule: the console's API key travels with a VERIFIED
 * session or not at all.
 *
 * Before this, the key went on every forwarded request, anonymous reads
 * included -- so every visitor was a governance admin to the API. These tests
 * are the line that stops that coming back.
 */

const SECRET = "test-session-secret-do-not-ship-0123456789abcdef";

function params(path: string) {
  return { params: Promise.resolve({ path: path.split("/") }) };
}

function sentHeaders(spy: ReturnType<typeof vi.fn>): Headers {
  const [, init] = spy.mock.calls[0] as [URL, RequestInit];
  return new Headers(init.headers);
}

describe("BFF credential attachment", () => {
  let spy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubEnv("VF_API_KEY", "console-secret-key");
    vi.stubEnv("VF_SESSION_SECRET", SECRET);
    vi.stubEnv("VF_PUBLIC_READS", "true");
    vi.stubEnv("FLASK_API_BASE", "http://127.0.0.1:9090");
    spy = vi.fn(async () => Response.json({ ok: true }));
    globalThis.fetch = spy as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("sends an anonymous read with no credential at all", async () => {
    const response = await GET(
      new Request("https://vf.example/api/proxy/review/queue"),
      params("review/queue"),
    );
    expect(response.status).toBe(200);
    const headers = sentHeaders(spy);
    expect(headers.get("x-vf-api-key")).toBeNull();
    expect(headers.get("x-vf-session")).toBeNull();
  });

  it("sends a forged cookie as anonymous, not as the key", async () => {
    await GET(
      new Request("https://vf.example/api/proxy/review/queue", {
        headers: { cookie: "vf_session=forged.token" },
      }),
      params("review/queue"),
    );
    const headers = sentHeaders(spy);
    expect(headers.get("x-vf-api-key")).toBeNull();
    expect(headers.get("x-vf-session")).toBeNull();
  });

  it("attaches the key and the session together for a signed-in person", async () => {
    const token = await signSession("reviewer@forwarder.example", "password");
    await GET(
      new Request("https://vf.example/api/proxy/review/queue", {
        headers: { cookie: `vf_session=${token}` },
      }),
      params("review/queue"),
    );
    const headers = sentHeaders(spy);
    expect(headers.get("x-vf-api-key")).toBe("console-secret-key");
    expect(headers.get("x-vf-session")).toBe(token);
  });

  it("passes the caller's address through for the rate limiter", async () => {
    await GET(
      new Request("https://vf.example/api/proxy/orchestrator/state", {
        headers: { "x-forwarded-for": "203.0.113.9" },
      }),
      params("orchestrator/state"),
    );
    expect(sentHeaders(spy).get("x-forwarded-for")).toBe("203.0.113.9");
  });

  it("refuses an anonymous write before it reaches the API", async () => {
    const response = await POST(
      new Request("https://vf.example/api/proxy/simulate", { method: "POST", body: "{}" }),
      params("simulate"),
    );
    expect(response.status).toBe(401);
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("Clear board needs a password sign-in", () => {
  let spy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubEnv("VF_API_KEY", "console-secret-key");
    vi.stubEnv("VF_SESSION_SECRET", SECRET);
    vi.stubEnv("FLASK_API_BASE", "http://127.0.0.1:9090");
    spy = vi.fn(async () => Response.json({ cleared: 3 }));
    globalThis.fetch = spy as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  async function reset(token: string | null) {
    return POST(
      new Request("https://vf.example/api/proxy/orchestrator/reset", {
        method: "POST",
        headers: token ? { cookie: `vf_session=${token}` } : {},
      }),
      params("orchestrator/reset"),
    );
  }

  it("refuses a one-click session without calling the API", async () => {
    const token = await signSession("guest-judge@vf-logistics.demo", "one_click");
    const response = await reset(token);
    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({
      required_auth: "password",
      session_method: "one_click",
    });
    expect(spy).not.toHaveBeenCalled();
  });

  it("forwards a password session with the key attached", async () => {
    const token = await signSession("judge@vf-logistics.demo", "password");
    const response = await reset(token);
    expect(response.status).toBe(200);
    expect(sentHeaders(spy).get("x-vf-api-key")).toBe("console-secret-key");
  });

  it("still turns away an anonymous caller first", async () => {
    expect((await reset(null)).status).toBe(401);
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("The two policy kill switches need a password sign-in too", () => {
  let spy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubEnv("VF_API_KEY", "console-secret-key");
    vi.stubEnv("VF_SESSION_SECRET", SECRET);
    vi.stubEnv("FLASK_API_BASE", "http://127.0.0.1:9090");
    spy = vi.fn(async () => Response.json({ ok: true }));
    globalThis.fetch = spy as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  function revoke(token: string | null) {
    return POST(
      new Request("https://vf.example/api/proxy/governance/revoke", {
        method: "POST",
        headers: { cookie: `vf_session=${token}` },
        body: "{}",
      }),
      params("governance/revoke"),
    );
  }

  function putRules(token: string | null) {
    return PUT(
      new Request("https://vf.example/api/proxy/governance/prefilter-rules", {
        method: "PUT",
        headers: { cookie: `vf_session=${token}` },
        body: "{}",
      }),
      params("governance/prefilter-rules"),
    );
  }

  it("refuses a one-click revoke and rules edit without calling the API", async () => {
    const token = await signSession("guest-judge@vf-logistics.demo", "one_click");
    for (const response of [await revoke(token), await putRules(token)]) {
      expect(response.status).toBe(403);
      expect(await response.json()).toMatchObject({ required_auth: "password" });
    }
    expect(spy).not.toHaveBeenCalled();
  });

  it("forwards both for a password session", async () => {
    const token = await signSession("judge@vf-logistics.demo", "password");
    expect((await revoke(token)).status).toBe(200);
    expect((await putRules(token)).status).toBe(200);
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("leaves publish open to a one-click session", async () => {
    const token = await signSession("guest-judge@vf-logistics.demo", "one_click");
    const response = await POST(
      new Request("https://vf.example/api/proxy/governance/publish", {
        method: "POST",
        headers: { cookie: `vf_session=${token}` },
        body: "{}",
      }),
      params("governance/publish"),
    );
    expect(response.status).toBe(200);
  });
});
