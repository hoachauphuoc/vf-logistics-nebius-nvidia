import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { setHelpMode, useHelpMode } from "./help-mode";

describe("help-mode store", () => {
  let localStorageMock: Record<string, string>;
  let setItemSpy: ReturnType<typeof vi.fn>;
  let getItemSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    localStorageMock = {};
    getItemSpy = vi.fn((key: string) => localStorageMock[key] ?? null);
    setItemSpy = vi.fn((key: string, value: string) => {
      localStorageMock[key] = value;
    });
    vi.stubGlobal(
      "localStorage",
      {
        getItem: getItemSpy,
        setItem: setItemSpy,
      } as never,
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe("setHelpMode", () => {
    beforeEach(() => {
      vi.resetModules();
    });

    it("writes true as '1' to localStorage", async () => {
      const { setHelpMode: setter } = await import("./help-mode");
      setter(true);
      expect(setItemSpy).toHaveBeenCalledWith("vf.console.help", "1");
    });

    it("writes false as '0' to localStorage", async () => {
      const { setHelpMode: setter } = await import("./help-mode");
      setter(false);
      expect(setItemSpy).toHaveBeenCalledWith("vf.console.help", "0");
    });

    it("skips write when value unchanged", async () => {
      const { setHelpMode: setter } = await import("./help-mode");
      setter(false);
      vi.clearAllMocks();
      setter(false);
      expect(setItemSpy).not.toHaveBeenCalled();
    });

    it("toggles between true and false", async () => {
      const { setHelpMode: setter } = await import("./help-mode");
      setter(true);
      expect(setItemSpy).toHaveBeenNthCalledWith(1, "vf.console.help", "1");
      setter(false);
      expect(setItemSpy).toHaveBeenNthCalledWith(2, "vf.console.help", "0");
    });
  });

  describe("useHelpMode hook", () => {
    beforeEach(() => {
      vi.resetModules();
    });

    it("returns a tuple with boolean and function", async () => {
      localStorageMock = {};
      getItemSpy = vi.fn((key: string) => localStorageMock[key] ?? null);
      setItemSpy = vi.fn((key: string, value: string) => {
        localStorageMock[key] = value;
      });
      vi.stubGlobal(
        "localStorage",
        {
          getItem: getItemSpy,
          setItem: setItemSpy,
        } as never,
      );
      const { useHelpMode: hook } = await import("./help-mode");
      const { result } = renderHook(() => hook());
      expect(Array.isArray(result.current)).toBe(true);
      expect(result.current.length).toBe(2);
      expect(typeof result.current[0]).toBe("boolean");
      expect(typeof result.current[1]).toBe("function");
    });

    it("returns setHelpMode as the setter", async () => {
      localStorageMock = {};
      getItemSpy = vi.fn((key: string) => localStorageMock[key] ?? null);
      setItemSpy = vi.fn((key: string, value: string) => {
        localStorageMock[key] = value;
      });
      vi.stubGlobal(
        "localStorage",
        {
          getItem: getItemSpy,
          setItem: setItemSpy,
        } as never,
      );
      const { setHelpMode: setter, useHelpMode: hook } = await import("./help-mode");
      const { result } = renderHook(() => hook());
      expect(result.current[1]).toBe(setter);
    });

    it("hook reads '1' from localStorage as true", async () => {
      localStorageMock = { "vf.console.help": "1" };
      getItemSpy = vi.fn((key: string) => localStorageMock[key] ?? null);
      setItemSpy = vi.fn((key: string, value: string) => {
        localStorageMock[key] = value;
      });
      vi.stubGlobal(
        "localStorage",
        {
          getItem: getItemSpy,
          setItem: setItemSpy,
        } as never,
      );
      const { useHelpMode: hook } = await import("./help-mode");
      vi.clearAllMocks();
      const { result } = renderHook(() => hook());
      expect(result.current[0]).toBe(true);
    });

    it("hook reads '0' from localStorage as false", async () => {
      localStorageMock = { "vf.console.help": "0" };
      getItemSpy = vi.fn((key: string) => localStorageMock[key] ?? null);
      setItemSpy = vi.fn((key: string, value: string) => {
        localStorageMock[key] = value;
      });
      vi.stubGlobal(
        "localStorage",
        {
          getItem: getItemSpy,
          setItem: setItemSpy,
        } as never,
      );
      const { useHelpMode: hook } = await import("./help-mode");
      vi.clearAllMocks();
      const { result } = renderHook(() => hook());
      expect(result.current[0]).toBe(false);
    });

    it("hook reads missing key as false", async () => {
      localStorageMock = {};
      getItemSpy = vi.fn((key: string) => localStorageMock[key] ?? null);
      setItemSpy = vi.fn((key: string, value: string) => {
        localStorageMock[key] = value;
      });
      vi.stubGlobal(
        "localStorage",
        {
          getItem: getItemSpy,
          setItem: setItemSpy,
        } as never,
      );
      const { useHelpMode: hook } = await import("./help-mode");
      vi.clearAllMocks();
      const { result } = renderHook(() => hook());
      expect(result.current[0]).toBe(false);
    });

    it("hook setter writes to localStorage", async () => {
      localStorageMock = {};
      getItemSpy = vi.fn((key: string) => localStorageMock[key] ?? null);
      setItemSpy = vi.fn((key: string, value: string) => {
        localStorageMock[key] = value;
      });
      vi.stubGlobal(
        "localStorage",
        {
          getItem: getItemSpy,
          setItem: setItemSpy,
        } as never,
      );
      const { useHelpMode: hook } = await import("./help-mode");
      const { result } = renderHook(() => hook());
      vi.clearAllMocks();
      act(() => {
        result.current[1](true);
      });
      expect(setItemSpy).toHaveBeenCalledWith("vf.console.help", "1");
    });

    it("hook reacts to setHelpMode calls", async () => {
      localStorageMock = {};
      getItemSpy = vi.fn((key: string) => localStorageMock[key] ?? null);
      setItemSpy = vi.fn((key: string, value: string) => {
        localStorageMock[key] = value;
      });
      vi.stubGlobal(
        "localStorage",
        {
          getItem: getItemSpy,
          setItem: setItemSpy,
        } as never,
      );
      const { setHelpMode: setter, useHelpMode: hook } = await import("./help-mode");
      const { result } = renderHook(() => hook());
      expect(result.current[0]).toBe(false);
      act(() => {
        setter(true);
      });
      expect(result.current[0]).toBe(true);
    });

    it("multiple instances share state", async () => {
      localStorageMock = {};
      getItemSpy = vi.fn((key: string) => localStorageMock[key] ?? null);
      setItemSpy = vi.fn((key: string, value: string) => {
        localStorageMock[key] = value;
      });
      vi.stubGlobal(
        "localStorage",
        {
          getItem: getItemSpy,
          setItem: setItemSpy,
        } as never,
      );
      const { useHelpMode: hook } = await import("./help-mode");
      const { result: r1 } = renderHook(() => hook());
      act(() => {
        r1.current[1](true);
      });
      const { result: r2 } = renderHook(() => hook());
      expect(r2.current[0]).toBe(true);
    });
  });

  describe("localStorage interaction", () => {
    beforeEach(() => {
      vi.resetModules();
    });

    it("reads on first hook mount", async () => {
      localStorageMock = { "vf.console.help": "1" };
      getItemSpy = vi.fn((key: string) => localStorageMock[key] ?? null);
      setItemSpy = vi.fn((key: string, value: string) => {
        localStorageMock[key] = value;
      });
      vi.stubGlobal(
        "localStorage",
        {
          getItem: getItemSpy,
          setItem: setItemSpy,
        } as never,
      );
      const { useHelpMode: hook } = await import("./help-mode");
      vi.clearAllMocks();
      renderHook(() => hook());
      expect(getItemSpy).toHaveBeenCalledWith("vf.console.help");
    });

    it("writes on setHelpMode call", async () => {
      localStorageMock = {};
      getItemSpy = vi.fn((key: string) => localStorageMock[key] ?? null);
      setItemSpy = vi.fn((key: string, value: string) => {
        localStorageMock[key] = value;
      });
      vi.stubGlobal(
        "localStorage",
        {
          getItem: getItemSpy,
          setItem: setItemSpy,
        } as never,
      );
      const { setHelpMode: setter } = await import("./help-mode");
      vi.clearAllMocks();
      act(() => {
        setter(true);
      });
      expect(setItemSpy).toHaveBeenCalledWith("vf.console.help", "1");
    });

    it("skips duplicate write", async () => {
      localStorageMock = {};
      getItemSpy = vi.fn((key: string) => localStorageMock[key] ?? null);
      setItemSpy = vi.fn((key: string, value: string) => {
        localStorageMock[key] = value;
      });
      vi.stubGlobal(
        "localStorage",
        {
          getItem: getItemSpy,
          setItem: setItemSpy,
        } as never,
      );
      const { setHelpMode: setter } = await import("./help-mode");
      setter(true);
      vi.clearAllMocks();
      act(() => {
        setter(true);
      });
      expect(setItemSpy).not.toHaveBeenCalled();
    });
  });

  describe("state management", () => {
    it("persists state across multiple renders", () => {
      const { result, rerender } = renderHook(() => useHelpMode());
      act(() => {
        result.current[1](true);
      });
      rerender();
      expect(result.current[0]).toBe(true);
    });

    it("setter function is stable across renders", () => {
      const { result, rerender } = renderHook(() => useHelpMode());
      const setter1 = result.current[1];
      rerender();
      const setter2 = result.current[1];
      expect(setter1).toBe(setter2);
    });

    it("hook reflects value from localStorage", () => {
      localStorageMock["vf.console.help"] = "1";
      vi.clearAllMocks();
      const { result } = renderHook(() => useHelpMode());
      expect(result.current[0]).toBe(true);
    });
  });

  describe("fresh module state", () => {
    beforeEach(() => {
      vi.resetModules();
    });

    it("initializes to false with no stored value", async () => {
      localStorageMock = {};
      getItemSpy = vi.fn((key: string) => localStorageMock[key] ?? null);
      setItemSpy = vi.fn((key: string, value: string) => {
        localStorageMock[key] = value;
      });
      vi.stubGlobal(
        "localStorage",
        {
          getItem: getItemSpy,
          setItem: setItemSpy,
        } as never,
      );
      const { useHelpMode: useHelpModeFresh } = await import("./help-mode");
      const { result } = renderHook(() => useHelpModeFresh());
      expect(result.current[0]).toBe(false);
    });

    it("handles rapid toggling with fresh state", async () => {
      localStorageMock = {};
      getItemSpy = vi.fn((key: string) => localStorageMock[key] ?? null);
      setItemSpy = vi.fn((key: string, value: string) => {
        localStorageMock[key] = value;
      });
      vi.stubGlobal(
        "localStorage",
        {
          getItem: getItemSpy,
          setItem: setItemSpy,
        } as never,
      );
      const { setHelpMode: setHelpModeFresh } = await import("./help-mode");
      vi.clearAllMocks();
      act(() => {
        setHelpModeFresh(true);
        setHelpModeFresh(false);
        setHelpModeFresh(true);
      });
      expect(setItemSpy).toHaveBeenCalledTimes(3);
      expect(setItemSpy).toHaveBeenNthCalledWith(1, "vf.console.help", "1");
      expect(setItemSpy).toHaveBeenNthCalledWith(2, "vf.console.help", "0");
      expect(setItemSpy).toHaveBeenNthCalledWith(3, "vf.console.help", "1");
    });
  });
});
