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

  it("forwards the chosen organisation only beside a verified session", async () => {
    // Findings T02/T03: the choice selects among the person's own memberships.
    // Without a session there is nobody whose memberships it could select from.
    const token = await signSession("reviewer@forwarder.example", "password");
    await GET(
      new Request("https://vf.example/api/proxy/review/queue", {
        headers: { cookie: `vf_session=${token}; vf_tenant=acme` },
      }),
      params("review/queue"),
    );
    expect(sentHeaders(spy).get("x-vf-tenant")).toBe("acme");

    spy.mockClear();
    await GET(
      new Request("https://vf.example/api/proxy/review/queue", {
        headers: { cookie: "vf_tenant=acme" },
      }),
      params("review/queue"),
    );
    expect(sentHeaders(spy).get("x-vf-tenant")).toBeNull();
  });

  it("never forwards a malformed organisation id", async () => {
    const token = await signSession("reviewer@forwarder.example", "password");
    await GET(
      new Request("https://vf.example/api/proxy/review/queue", {
        headers: { cookie: `vf_session=${token}; vf_tenant=..%2Fother` },
      }),
      params("review/queue"),
    );
    expect(sentHeaders(spy).get("x-vf-tenant")).toBeNull();
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
    // A guest token is honoured only while the guest door is open (finding S01).
    vi.stubEnv("VF_ONE_CLICK_JUDGE", "true");
    vi.stubEnv("VF_ONE_CLICK_EMAIL", "guest-judge@vf-logistics.demo");
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

describe("The policy writes need a password sign-in too", () => {
  let spy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubEnv("VF_API_KEY", "console-secret-key");
    vi.stubEnv("VF_SESSION_SECRET", SECRET);
    vi.stubEnv("VF_ONE_CLICK_JUDGE", "true");
    vi.stubEnv("VF_ONE_CLICK_EMAIL", "guest-judge@vf-logistics.demo");
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

  function publish(token: string | null) {
    return POST(
      new Request("https://vf.example/api/proxy/governance/publish", {
        method: "POST",
        headers: { cookie: `vf_session=${token}` },
        body: JSON.stringify({ permissions: { allowed_actions: [] } }),
      }),
      params("governance/publish"),
    );
  }

  it("refuses a one-click publish, revoke and rules edit without calling the API", async () => {
    const token = await signSession("guest-judge@vf-logistics.demo", "one_click");
    for (const response of [await publish(token), await revoke(token), await putRules(token)]) {
      expect(response.status).toBe(403);
      expect(await response.json()).toMatchObject({ required_auth: "password" });
    }
    expect(spy).not.toHaveBeenCalled();
  });

  it("forwards all three for a password session", async () => {
    const token = await signSession("judge@vf-logistics.demo", "password");
    expect((await publish(token)).status).toBe(200);
    expect((await revoke(token)).status).toBe(200);
    expect((await putRules(token)).status).toBe(200);
    expect(spy).toHaveBeenCalledTimes(3);
  });

  it("leaves simulate open to a one-click session", async () => {
    const token = await signSession("guest-judge@vf-logistics.demo", "one_click");
    const response = await POST(
      new Request("https://vf.example/api/proxy/governance/simulate", {
        method: "POST",
        headers: { cookie: `vf_session=${token}` },
        body: "{}",
      }),
      params("governance/simulate"),
    );
    expect(response.status).toBe(200);
  });

  it("treats a guest cookie as signed out once the guest door is closed", async () => {
    // Finding S01: the cookie was minted while the door was open, and closing
    // the door must end it rather than only stopping the next guest.
    const token = await signSession("guest-judge@vf-logistics.demo", "one_click");
    vi.stubEnv("VF_ONE_CLICK_JUDGE", "false");
    const response = await publish(token);
    expect(response.status).toBe(401);
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("Evidence upload is authenticated by its token, not a session", () => {
  let spy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubEnv("VF_API_KEY", "console-secret-key");
    vi.stubEnv("VF_SESSION_SECRET", SECRET);
    vi.stubEnv("FLASK_API_BASE", "http://127.0.0.1:9090");
    spy = vi.fn(async () => Response.json({ received: true }, { status: 201 }));
    globalThis.fetch = spy as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  const upload = () =>
    new Request("https://vf.example/api/proxy/evidence/respond", {
      method: "POST",
      headers: { "X-VF-Evidence-Token": "signed.token" },
      body: "file",
    });

  it("lets a shipper with no console session reach the API (Rev2 N08: it was a 401)", async () => {
    const response = await POST(upload(), params("evidence/respond"));
    expect(response.status).toBe(201);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("forwards the shipper's token but never the console's API key", async () => {
    await POST(upload(), params("evidence/respond"));
    const headers = sentHeaders(spy);
    expect(headers.get("x-vf-evidence-token")).toBe("signed.token");
    expect(headers.get("x-vf-api-key")).toBeNull();
  });

  it("does not open any other write to an anonymous caller", async () => {
    for (const path of ["review/CASE-1/approve", "review/CASE-1/execute", "review/CASE-1/reevaluate"]) {
      const response = await POST(
        new Request(`https://vf.example/api/proxy/${path}`, { method: "POST", body: "{}" }),
        params(path),
      );
      expect(response.status).toBe(401);
    }
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("Approving and executing a decision need a password sign-in at the BFF too (N07)", () => {
  let spy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubEnv("VF_API_KEY", "console-secret-key");
    vi.stubEnv("VF_SESSION_SECRET", SECRET);
    vi.stubEnv("FLASK_API_BASE", "http://127.0.0.1:9090");
    vi.stubEnv("VF_ONE_CLICK_JUDGE", "true");
    vi.stubEnv("VF_ONE_CLICK_EMAIL", "guest-judge@vf-logistics.demo");
    spy = vi.fn(async () => Response.json({ state: "APPROVED" }));
    globalThis.fetch = spy as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  const post = (path: string, token: string | null) =>
    POST(
      new Request(`https://vf.example/api/proxy/${path}`, {
        method: "POST",
        headers: token ? { cookie: `vf_session=${token}` } : {},
        body: "{}",
      }),
      params(path),
    );

  // The gate used to be keyed by the TEMPLATE ("review/approve") and looked up with
  // the raw path ("review/CASE-1/approve"), so it never matched and only Flask's own
  // check was left standing.
  it.each(["review/CASE-1/approve", "review/CASE-1/execute"])(
    "turns a one-click session away from %s without calling the API",
    async (path) => {
      const token = await signSession("guest-judge@vf-logistics.demo", "one_click");
      const response = await post(path, token);
      expect(response.status).toBe(403);
      expect(await response.json()).toMatchObject({
        error: "password_session_required",
        required_auth: "password",
      });
      expect(spy).not.toHaveBeenCalled();
    },
  );

  it.each(["review/CASE-1/approve", "review/CASE-1/execute"])(
    "forwards %s for a password session, key attached",
    async (path) => {
      const token = await signSession("reviewer@forwarder.example", "password");
      expect((await post(path, token)).status).toBe(200);
      expect(sentHeaders(spy).get("x-vf-api-key")).toBe("console-secret-key");
    },
  );

  it("leaves the other review writes to a one-click session (a block is not a release)", async () => {
    const token = await signSession("guest-judge@vf-logistics.demo", "one_click");
    for (const path of ["review/CASE-1/decide", "review/CASE-1/request-evidence", "review/CASE-1/reevaluate"]) {
      expect((await post(path, token)).status).toBe(200);
    }
    expect(spy).toHaveBeenCalledTimes(3);
  });
});
