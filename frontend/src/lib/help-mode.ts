"use client";

import { useSyncExternalStore } from "react";

/**
 * Help mode: persisted, in a small external store.
 *
 * Same shape and same reason as sidebar-state: the obvious version -- useState
 * plus an effect that restores the persisted value on mount -- calls setState
 * from inside an effect, which cascades a second render on every mount and is
 * what react-hooks/set-state-in-effect exists to catch. `getServerSnapshot`
 * renders help OFF on the server so the markup matches, and React re-reads from
 * localStorage once hydration finishes.
 *
 * Persisted rather than per-page for the same reason the sidebar is: somebody who
 * turned help on did so because they are learning the console, and having it
 * switch itself off on the next screen is precisely when they needed it.
 *
 * A separate key from the sidebar on purpose. They look alike, and one shared
 * key would mean collapsing the sidebar silently turned help off.
 */

const STORAGE_KEY = "vf.console.help";

let cached: boolean | null = null;
const listeners = new Set<() => void>();

function read(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(STORAGE_KEY) === "1";
}

// Cached because getSnapshot must return an identical value for identical state.
function getSnapshot(): boolean {
  if (cached === null) cached = read();
  return cached;
}

// Off on the server. Help is additive, so rendering it off first and letting
// hydration turn it on can only ever add elements -- the reverse would flash
// question marks onto the screen for anyone who never asked for them.
function getServerSnapshot(): boolean {
  return false;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function setHelpMode(next: boolean): void {
  if (next === cached) return;
  cached = next;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
  }
  for (const listener of listeners) listener();
}

export function useHelpMode(): [boolean, (next: boolean) => void] {
  const on = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return [on, setHelpMode];
}
