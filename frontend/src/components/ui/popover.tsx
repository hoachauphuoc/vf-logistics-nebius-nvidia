"use client"

import * as React from "react"
import { cn } from "cn"
import { Popover as PopoverPrimitive } from "radix-ui"

/**
 * Click-to-open surface, for content a reader needs time with.
 *
 * Distinct from Tooltip on purpose. A tooltip is hover-only and dismisses the
 * moment the pointer leaves, which is right for a one-line hint and wrong for an
 * explanation somebody is reading: it cannot be selected, cannot be reached on a
 * touch screen, and closes while the eye is still on the third line. Help content
 * is several sentences, so it gets a popover that stays until dismissed.
 *
 * Uses the `--popover` token that globals.css already defines, rather than the
 * inverted `bg-foreground` a tooltip uses, so a panel of body text reads as
 * body text and not as a large tooltip.
 */

function Popover({
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Root>) {
  return <PopoverPrimitive.Root data-slot="popover" {...props} />
}

function PopoverTrigger({
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Trigger>) {
  return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />
}

function PopoverAnchor({
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Anchor>) {
  return <PopoverPrimitive.Anchor data-slot="popover-anchor" {...props} />
}

function PopoverClose({
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Close>) {
  return <PopoverPrimitive.Close data-slot="popover-close" {...props} />
}

function PopoverContent({
  className,
  align = "start",
  sideOffset = 6,
  children,
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Content>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        data-slot="popover-content"
        align={align}
        sideOffset={sideOffset}
        // collisionPadding keeps a popover opened from a panel at the right edge
        // of the board from rendering half off-screen.
        collisionPadding={12}
        className={cn(
          "z-50 w-72 origin-(--radix-popover-content-transform-origin) rounded-lg border border-white/10 bg-popover p-3 text-popover-foreground shadow-xl outline-none",
          "data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2",
          "data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
          className
        )}
        {...props}
      >
        {children}
        <PopoverPrimitive.Arrow className="z-50 size-2.5 translate-y-[calc(-50%_-_2px)] rotate-45 rounded-[2px] border-r border-b border-white/10 bg-popover fill-popover" />
      </PopoverPrimitive.Content>
    </PopoverPrimitive.Portal>
  )
}

export {
  Popover,
  PopoverAnchor,
  PopoverClose,
  PopoverContent,
  PopoverTrigger,
}
