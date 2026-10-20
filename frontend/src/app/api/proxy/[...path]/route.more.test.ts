// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { signSession } from "@/lib/session";

import { GET, POST, PUT } from "./route";

/**
 * The BFF's routing and response rules: which paths are forwarded, how the
 * upstream reply is passed back, and what an unreachable API looks like.
 *
 * The credential rules have their own file (route.test.ts); these tests cover
 * the rest of the route.
 */

const SECRET = "test-session-secret-do-not-ship-0123456789abcdef";

function params(path: string) {
  return { params: Promise.resolve({ path: path.split("/") }) };
}

function sentUrl(spy: ReturnType<typeof vi.fn>): string {
  const [url] = spy.mock.calls[0] as [URL, RequestInit];
  return String(url);
}

function sentInit(spy: ReturnType<typeof vi.fn>): RequestInit {
  const [, init] = spy.mock.calls[0] as [URL, RequestInit];
  return init;
}

async function cookieFor(email: string, amr: "password" | "one_click"): Promise<string> {
  return `vf_session=${await signSession(email, amr)}`;
}

describe("Paths the proxy does not forward", () => {
  let spy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubEnv("VF_API_KEY", "console-secret-key");
    vi.stubEnv("VF_SESSION_SECRET", "");
    vi.stubEnv("VF_PUBLIC_READS", "");
    vi.stubEnv("FLASK_API_BASE", "http://127.0.0.1:9090");
    spy = vi.fn(async () => Response.json({ ok: true }));
    vi.stubGlobal("fetch", spy);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("answers 404 for an unlisted GET and names the path", async () => {
    const response = await GET(
      new Request("https://vf.example/api/proxy/admin/secret"),
      params("admin/secret"),
    );
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({
      error: "Path not proxied for GET: admin/secret",
    });
    expect(spy).not.toHaveBeenCalled();
  });

  it("answers 404 for a read-only path sent as a POST", async () => {
    const response = await POST(
      new Request("https://vf.example/api/proxy/orchestrator/state", { method: "POST", body: "{}" }),
      params("orchestrator/state"),
    );
    expect(response.status).toBe(404);
    expect((await response.json()).error).toBe(
      "Path not proxied for POST: orchestrator/state",
    );
    expect(spy).not.toHaveBeenCalled();
  });

  it("answers 404 for a PUT to any path other than the prefilter rules", async () => {
    const response = await PUT(
      new Request("https://vf.example/api/proxy/orchestrator/reset", { method: "PUT", body: "{}" }),
      params("orchestrator/reset"),
    );
    expect(response.status).toBe(404);
    expect((await response.json()).error).toBe(
      "Path not proxied for PUT: orchestrator/reset",
    );
    expect(spy).not.toHaveBeenCalled();
  });

  it("refuses a by-id read whose id is not a well-formed case id", async () => {
    const response = await GET(
      new Request("https://vf.example/api/proxy/orchestrator/case/bad.id"),
      params("orchestrator/case/bad.id"),
    );
    expect(response.status).toBe(404);
    expect(spy).not.toHaveBeenCalled();
  });

  it("refuses a traversal hidden inside a review write path", async () => {
    const response = await POST(
      new Request("https://vf.example/api/proxy/review/../orchestrator/reset", {
        method: "POST",
        body: "{}",
      }),
      params("review/../orchestrator/reset"),
    );
    expect(response.status).toBe(404);
    expect(spy).not.toHaveBeenCalled();
  });

  it("answers 404 with an empty path name when no segments are given", async () => {
    const response = await GET(
      new Request("https://vf.example/api/proxy/"),
      { params: Promise.resolve({ path: undefined as never }) },
    );
    expect(response.status).toBe(404);
    expect((await response.json()).error).toBe("Path not proxied for GET: ");
  });
});

describe("Reads", () => {
  let spy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubEnv("VF_API_KEY", "console-secret-key");
    vi.stubEnv("VF_SESSION_SECRET", "");
    vi.stubEnv("VF_PUBLIC_READS", "");
    vi.stubEnv("FLASK_API_BASE", "http://127.0.0.1:9090");
    vi.stubEnv("FLASK_API_TOKEN", "");
    spy = vi.fn(async () => Response.json({ ok: true }));
    vi.stubGlobal("fetch", spy);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("forwards an allowed read to the API root, keeping only the allowed query parameters", async () => {
    vi.stubEnv("FLASK_API_BASE", "http://flask.internal:9090/");
    await GET(
      new Request("https://vf.example/api/proxy/cases?state=OPEN&secret=x&limit=5"),
      params("cases"),
    );
    expect(sentUrl(spy)).toBe("http://flask.internal:9090/api/v1/cases?limit=5&state=OPEN");
  });

  it("forwards a by-id read for a well-formed case id", async () => {
    const response = await GET(
      new Request("https://vf.example/api/proxy/orchestrator/case/CASE-1"),
      params("orchestrator/case/CASE-1"),
    );
    expect(response.status).toBe(200);
    expect(sentUrl(spy)).toBe("http://127.0.0.1:9090/api/v1/orchestrator/case/CASE-1");
  });

  it("forwards the scanned document for a review case", async () => {
    await GET(
      new Request("https://vf.example/api/proxy/review/CASE-1/document"),
      params("review/CASE-1/document"),
    );
    expect(sentUrl(spy)).toBe("http://127.0.0.1:9090/api/v1/review/CASE-1/document");
  });

  it("answers 401 to an anonymous read when sign-in is required and public reads are off", async () => {
    vi.stubEnv("VF_SESSION_SECRET", SECRET);
    const response = await GET(
      new Request("https://vf.example/api/proxy/audit"),
      params("audit"),
    );
    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({
      error: "not_authenticated",
      detail: "Sign in to continue.",
    });
    expect(spy).not.toHaveBeenCalled();
  });

  it("answers 401 to an anonymous read in production with no session secret", async () => {
    // Fail closed: a production console without a secret is offline, not open.
    vi.stubEnv("NODE_ENV", "production");
    const response = await GET(
      new Request("https://vf.example/api/proxy/audit"),
      params("audit"),
    );
    expect(response.status).toBe(401);
    expect(spy).not.toHaveBeenCalled();
  });

  it("lets an anonymous read through in development with no session secret", async () => {
    vi.stubEnv("NODE_ENV", "development");
    const response = await GET(
      new Request("https://vf.example/api/proxy/audit"),
      params("audit"),
    );
    expect(response.status).toBe(200);
    expect(new Headers(sentInit(spy).headers).get("x-vf-api-key")).toBeNull();
  });

  it("sends the service bearer token when the console runs behind IAP", async () => {
    vi.stubEnv("FLASK_API_TOKEN", "service-token");
    await GET(new Request("https://vf.example/api/proxy/audit"), params("audit"));
    expect(new Headers(sentInit(spy).headers).get("authorization")).toBe("Bearer service-token");
  });

  it("does not forward a content type on a read", async () => {
    await GET(
      new Request("https://vf.example/api/proxy/audit", {
        headers: { "content-type": "application/json" },
      }),
      params("audit"),
    );
    expect(new Headers(sentInit(spy).headers).get("content-type")).toBeNull();
  });

  it("forwards the last X-Forwarded-Proto hop so Flask sees the public scheme", async () => {
    await GET(
      new Request("https://vf.example/api/proxy/audit", {
        headers: { "x-forwarded-proto": "http, https" },
      }),
      params("audit"),
    );
    expect(new Headers(sentInit(spy).headers).get("x-forwarded-proto")).toBe("https");
  });
});

describe("Passing the upstream reply back", () => {
  let spy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubEnv("VF_API_KEY", "console-secret-key");
    vi.stubEnv("VF_SESSION_SECRET", "");
    vi.stubEnv("VF_PUBLIC_READS", "");
    vi.stubEnv("FLASK_API_BASE", "http://127.0.0.1:9090");
    spy = vi.fn(async () => Response.json({ ok: true }));
    vi.stubGlobal("fetch", spy);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("keeps the upstream status and JSON body", async () => {
    spy.mockImplementation(async () => Response.json({ id: "CASE-1" }, { status: 201 }));
    const response = await GET(new Request("https://vf.example/api/proxy/cases"), params("cases"));
    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({ id: "CASE-1" });
    expect(response.headers.get("content-type")).toContain("application/json");
  });

  it("treats an upstream reply with no content type as JSON", async () => {
    spy.mockImplementation(async () => new Response(null, { status: 200 }));
    const response = await GET(new Request("https://vf.example/api/proxy/cases"), params("cases"));
    expect(response.headers.get("content-type")).toBe("application/json");
  });

  it("passes a PDF through as bytes, with its disposition and nosniff", async () => {
    const pdf = Uint8Array.from([37, 80, 68, 70]);
    spy.mockImplementation(
      async () =>
        new Response(pdf, {
          headers: {
            "content-type": "application/pdf",
            "content-disposition": "inline; filename=bol.pdf",
          },
        }),
    );
    const response = await GET(
      new Request("https://vf.example/api/proxy/review/CASE-1/document"),
      params("review/CASE-1/document"),
    );
    expect(response.headers.get("content-type")).toBe("application/pdf");
    expect(response.headers.get("content-disposition")).toBe("inline; filename=bol.pdf");
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(pdf);
  });

  it.each([
    "text/html; charset=utf-8",
    "application/javascript",
    "image/svg+xml",
  ])("downgrades a %s reply to a generic binary type", async (contentType) => {
    const body = "<script>alert(1)</script>";
    spy.mockImplementation(
      async () => new Response(body, { headers: { "content-type": contentType } }),
    );
    const response = await GET(new Request("https://vf.example/api/proxy/audit"), params("audit"));
    expect(response.headers.get("content-type")).toBe("application/octet-stream");
    expect(response.headers.get("content-disposition")).toBeNull();
    expect(new TextDecoder().decode(await response.arrayBuffer())).toBe(body);
  });

  it("keeps a supported image type that carries a parameter", async () => {
    spy.mockImplementation(
      async () => new Response(Uint8Array.from([137, 80]), { headers: { "content-type": "image/png; x=1" } }),
    );
    const response = await GET(
      new Request("https://vf.example/api/proxy/review/CASE-1/document"),
      params("review/CASE-1/document"),
    );
    expect(response.headers.get("content-type")).toBe("image/png; x=1");
  });

  it("answers 502 with the reason when the API cannot be reached", async () => {
    spy.mockRejectedValue(new Error("connect ECONNREFUSED 127.0.0.1:9090"));
    const response = await GET(new Request("https://vf.example/api/proxy/cases"), params("cases"));
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({
      error: "upstream_unreachable",
      detail: "connect ECONNREFUSED 127.0.0.1:9090",
    });
  });

  it("reports a non-Error failure as text in the 502 detail", async () => {
    spy.mockRejectedValue("socket hang up");
    const response = await GET(new Request("https://vf.example/api/proxy/cases"), params("cases"));
    expect(response.status).toBe(502);
    expect((await response.json()).detail).toBe("socket hang up");
  });
});

describe("Writes", () => {
  let spy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubEnv("VF_API_KEY", "console-secret-key");
    vi.stubEnv("VF_SESSION_SECRET", SECRET);
    vi.stubEnv("VF_PUBLIC_READS", "");
    vi.stubEnv("FLASK_API_BASE", "http://127.0.0.1:9090");
    spy = vi.fn(async () => Response.json({ ok: true }));
    vi.stubGlobal("fetch", spy);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("streams the request body and its content type to the API", async () => {
    vi.stubEnv("VF_SESSION_SECRET", "");
    const response = await POST(
      new Request("https://vf.example/api/proxy/simulate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: '{"shipment":"S1"}',
      }),
      params("simulate"),
    );
    expect(response.status).toBe(200);
    const init = sentInit(spy);
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("content-type")).toBe("application/json");
    expect((init as RequestInit & { duplex?: string }).duplex).toBe("half");
    expect(await new Response(init.body).text()).toBe('{"shipment":"S1"}');
  });

  it("forwards an evidence link and refuses an unknown sub-action on a case", async () => {
    vi.stubEnv("VF_SESSION_SECRET", "");
    const linked = await POST(
      new Request("https://vf.example/api/proxy/review/CASE-1/evidence/EV-2/link", {
        method: "POST",
        body: "{}",
      }),
      params("review/CASE-1/evidence/EV-2/link"),
    );
    expect(linked.status).toBe(200);
    expect(sentUrl(spy)).toBe(
      "http://127.0.0.1:9090/api/v1/review/CASE-1/evidence/EV-2/link",
    );

    const unknown = await POST(
      new Request("https://vf.example/api/proxy/review/CASE-1/delete", { method: "POST", body: "{}" }),
      params("review/CASE-1/delete"),
    );
    expect(unknown.status).toBe(404);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("refuses an anonymous prefilter-rules PUT with 401 when sign-in is required", async () => {
    const response = await PUT(
      new Request("https://vf.example/api/proxy/governance/prefilter-rules", {
        method: "PUT",
        body: "{}",
      }),
      params("governance/prefilter-rules"),
    );
    expect(response.status).toBe(401);
    expect((await response.json()).error).toBe("not_authenticated");
    expect(spy).not.toHaveBeenCalled();
  });

  it("forwards a password-signed prefilter-rules PUT with the key attached", async () => {
    const cookie = await cookieFor("judge@vf-logistics.demo", "password");
    const response = await PUT(
      new Request("https://vf.example/api/proxy/governance/prefilter-rules", {
        method: "PUT",
        headers: { cookie },
        body: "{}",
      }),
      params("governance/prefilter-rules"),
    );
    expect(response.status).toBe(200);
    expect(sentInit(spy).method).toBe("PUT");
    expect(new Headers(sentInit(spy).headers).get("x-vf-api-key")).toBe("console-secret-key");
  });
});
