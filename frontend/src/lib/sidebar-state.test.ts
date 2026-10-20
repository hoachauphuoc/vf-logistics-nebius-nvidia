import { act, renderHook } from "@testing-library/react";
import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type * as SidebarState from "@/lib/sidebar-state";

const STORAGE_KEY = "vf.console.sidebar.collapsed";

// The store keeps its value in a module-level cache, so every test loads a fresh copy
// of the module. Without this, the first test that reads localStorage decides the value
// for every test after it in this file.
let sidebar: typeof SidebarState;

beforeEach(async () => {
  window.localStorage.clear();
  vi.resetModules();
  sidebar = await import("@/lib/sidebar-state");
});

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("useSidebarCollapsed reads the persisted value", () => {
  it("starts expanded when nothing is persisted", () => {
    const { result } = renderHook(() => sidebar.useSidebarCollapsed());

    expect(result.current[0]).toBe(false);
  });

  it("starts collapsed when the stored value is 1", () => {
    window.localStorage.setItem(STORAGE_KEY, "1");

    const { result } = renderHook(() => sidebar.useSidebarCollapsed());

    expect(result.current[0]).toBe(true);
  });

  it.each(["0", "true", "yes", ""])(
    "treats the stored value %j as expanded, because only 1 means collapsed",
    (stored) => {
      window.localStorage.setItem(STORAGE_KEY, stored);

      const { result } = renderHook(() => sidebar.useSidebarCollapsed());

      expect(result.current[0]).toBe(false);
    },
  );

  it("renders expanded on the server even when the stored value is 1", () => {
    window.localStorage.setItem(STORAGE_KEY, "1");
    const Probe = () => {
      const [collapsed] = sidebar.useSidebarCollapsed();
      return createElement("span", null, String(collapsed));
    };

    const html = renderToString(createElement(Probe));

    expect(html).toContain(">false<");
    expect(html).not.toContain(">true<");
  });

  it("reads localStorage once per page load and does not pick up later writes", () => {
    const { result } = renderHook(() => sidebar.useSidebarCollapsed());
    expect(result.current[0]).toBe(false);

    window.localStorage.setItem(STORAGE_KEY, "1");

    expect(result.current[0]).toBe(false);
  });
});

describe("setCollapsed", () => {
  it("updates a mounted consumer to collapsed", () => {
    const { result } = renderHook(() => sidebar.useSidebarCollapsed());

    act(() => sidebar.setCollapsed(true));

    expect(result.current[0]).toBe(true);
  });

  it("writes 1 when collapsing and 0 when expanding", () => {
    sidebar.setCollapsed(true);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("1");

    sidebar.setCollapsed(false);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("0");
  });

  it("persists the value so a freshly loaded module starts in the same state", async () => {
    sidebar.setCollapsed(true);
    vi.resetModules();
    const fresh = await import("@/lib/sidebar-state");

    const { result } = renderHook(() => fresh.useSidebarCollapsed());

    expect(result.current[0]).toBe(true);
  });

  it("does not write storage when the value is unchanged", () => {
    renderHook(() => sidebar.useSidebarCollapsed());
    const setItem = vi.spyOn(Storage.prototype, "setItem");

    sidebar.setCollapsed(false);

    expect(setItem).not.toHaveBeenCalled();
  });

  it("notifies every mounted consumer", () => {
    const first = renderHook(() => sidebar.useSidebarCollapsed());
    const second = renderHook(() => sidebar.useSidebarCollapsed());

    act(() => sidebar.setCollapsed(true));

    expect(first.result.current[0]).toBe(true);
    expect(second.result.current[0]).toBe(true);
  });

  it("stops updating a consumer that has unmounted", () => {
    const mounted = renderHook(() => sidebar.useSidebarCollapsed());
    const unmounted = renderHook(() => sidebar.useSidebarCollapsed());
    unmounted.unmount();

    act(() => sidebar.setCollapsed(true));

    expect(mounted.result.current[0]).toBe(true);
    expect(unmounted.result.current[0]).toBe(false);
  });
});

describe("useSidebarCollapsed setter", () => {
  it("is the same function as setCollapsed", () => {
    const { result } = renderHook(() => sidebar.useSidebarCollapsed());

    expect(result.current[1]).toBe(sidebar.setCollapsed);
  });

  it("collapses the sidebar and persists it when called from the hook", () => {
    const { result } = renderHook(() => sidebar.useSidebarCollapsed());

    act(() => result.current[1](true));

    expect(result.current[0]).toBe(true);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("1");
  });
});
