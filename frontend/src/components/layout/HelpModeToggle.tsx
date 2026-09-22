"use client";

import { CircleQuestionMark } from "lucide-react";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useHelpMode } from "@/lib/help-mode";
import { cn } from "@/lib/utils";

/**
 * Turns Help mode on and off, for the whole console.
 *
 * A button with aria-pressed rather than a switch: it matches the sidebar collapse
 * control that is already the precedent for a persisted shell-level preference,
 * and a 14-unit header has no room for a switch plus its label.
 *
 * The tooltip stays a tooltip. It is one line, it explains the control rather than
 * the data, and it must work before help mode is on -- otherwise the only way to
 * discover what the button does is to press it.
 */
export function HelpModeToggle() {
  const [on, setOn] = useHelpMode();

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={() => setOn(!on)}
          aria-pressed={on}
          aria-label={on ? "Turn help off" : "Turn help on"}
          className={cn(
            "inline-flex h-7 items-center gap-1.5 rounded-md border px-2 text-[11.5px] transition-colors",
            on
              ? "border-brand/40 bg-brand/[0.12] text-brand"
              : "border-white/10 text-dim hover:border-white/20 hover:text-white/80",
          )}
        >
          <CircleQuestionMark className="size-3.5" aria-hidden />
          <span className="hidden sm:inline">Help</span>
        </button>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-[20rem]">
        {on
          ? "Help is on. Press the question mark beside anything to see what it means."
          : "Adds a question mark beside each panel, tile and status label. Press one to see what it means."}
      </TooltipContent>
    </Tooltip>
  );
}
