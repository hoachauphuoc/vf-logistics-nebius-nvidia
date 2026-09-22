"use client";

import { useSyncExternalStore } from "react";

/**
 * Sidebar collapse, persisted, in a small external store.
 *
 * Same shape and same reason as tenant-context: the obvious version -- useState
 * plus an effect that restores the persisted value on mount -- calls setState
 * from inside an effect, which cascades a second render on every mount and is
 * what react-hooks/set-state-in-effect exists to catch. `getServerSnapshot`
 * renders expanded on the server so the markup matches, and React re-reads from
 * localStorage once hydration finishes.
 *
 * A collapsed sidebar that silently expands on every navigation is the kind of
 * small wrongness that makes an operator stop trusting the rest of the screen.
 */

const STORAGE_KEY = "vf.console.sidebar.collapsed";

let cached: boolean | null = null;
const listeners = new Set<() => void>();

function read(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(STORAGE_KEY) === "1";
}

// Cached because getSnapshot must return an identical value for identical
// state. Reading localStorage on every call is fine for a boolean, but keeping
// the same discipline as the tenant store means one pattern to remember.
function getSnapshot(): boolean {
  if (cached === null) cached = read();
  return cached;
}

function getServerSnapshot(): boolean {
  return false;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function setCollapsed(next: boolean): void {
  if (next === cached) return;
  cached = next;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
  }
  for (const listener of listeners) listener();
}

export function useSidebarCollapsed(): [boolean, (next: boolean) => void] {
  const collapsed = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getServerSnapshot,
  );
  return [collapsed, setCollapsed];
}
