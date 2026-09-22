"use client";

import { CircleQuestionMark } from "lucide-react";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { helpFor } from "@/lib/help-content";
import { useHelpMode } from "@/lib/help-mode";
import { cn } from "@/lib/utils";

/**
 * A question mark that only exists while Help mode is on.
 *
 * Returns null rather than hiding with CSS, deliberately. Help is meant to be
 * additive: an operator who never switches it on should not be paying for it in
 * layout, and a hidden-but-present element still occupies a flex row. The visible
 * consequence is that turning help on adds elements and never moves the numbers
 * they explain, which is the opposite of what `visibility: hidden` would give.
 *
 * Click rather than hover, because the content is several sentences. A tooltip
 * dismisses as soon as the pointer leaves, cannot be selected, and is unreachable
 * on a touch screen -- all fine for a one-line hint, none of it acceptable for
 * something a person is reading to learn the product.
 *
 * An unknown id renders nothing. The alternative -- an empty popover, or worse a
 * thrown error -- would make a missing help string into a broken screen.
 */
export function HelpDot({
  id,
  side = "bottom",
  className,
}: {
  id: string;
  side?: "top" | "right" | "bottom" | "left";
  className?: string;
}) {
  const [on] = useHelpMode();
  const entry = helpFor(id);

  if (!on || !entry) return null;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          // stopPropagation because these sit inside clickable cards and column
          // headers; without it, asking what a card means would also open it.
          onClick={(event) => event.stopPropagation()}
          aria-label={`What is ${entry.title}?`}
          className={cn(
            "inline-flex size-4 shrink-0 items-center justify-center rounded-full",
            "text-brand/70 transition-colors hover:text-brand focus-visible:outline-none",
            "focus-visible:ring-1 focus-visible:ring-brand/60",
            className,
          )}
        >
          <CircleQuestionMark className="size-4" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent side={side} className="w-80">
        <p className="text-[12px] font-medium tracking-display text-white">
          {entry.title}
        </p>
        <p className="mt-1.5 text-[11.5px] leading-relaxed text-dim">
          {entry.body}
        </p>
        {entry.note && (
          <p className="mt-2 border-t border-white/[0.08] pt-2 text-[11px] leading-relaxed text-faint">
            {entry.note}
          </p>
        )}
      </PopoverContent>
    </Popover>
  );
}
