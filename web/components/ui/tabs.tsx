"use client"

import * as React from "react"
import { Tabs as TabsPrimitive } from "@base-ui/react/tabs"
import { cn } from "cn"

// Keyboard navigation (arrow keys, Home/End, looping) and the tablist/tab/
// tabpanel roles are the primitive's, the same way Popover and Menu already
// own their own focus handling in this codebase — nothing here reimplements
// it. What this wraps is only the look.

function Tabs({ className, ...props }: TabsPrimitive.Root.Props) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      className={cn("flex flex-col gap-2", className)}
      {...props}
    />
  )
}

function TabsList({ className, ...props }: TabsPrimitive.List.Props) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      className={cn(
        "relative inline-flex w-fit items-center gap-1 rounded-lg bg-muted p-1 text-muted-foreground",
        className
      )}
      {...props}
    />
  )
}

function TabsTab({ className, ...props }: TabsPrimitive.Tab.Props) {
  return (
    <TabsPrimitive.Tab
      data-slot="tabs-tab"
      className={cn(
        "inline-flex h-7 flex-1 items-center justify-center gap-1.5 rounded-md px-3 text-sm font-medium whitespace-nowrap text-foreground outline-none select-none",
        "data-[active]:bg-background data-[active]:text-foreground data-[active]:shadow-sm",
        "focus-visible:ring-3 focus-visible:ring-ring/50",
        "disabled:pointer-events-none disabled:opacity-50",
        "[&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
        className
      )}
      {...props}
    />
  )
}

function TabsPanel({ className, ...props }: TabsPrimitive.Panel.Props) {
  return (
    <TabsPrimitive.Panel
      data-slot="tabs-panel"
      className={cn("flex-1 outline-none focus-visible:ring-3 focus-visible:ring-ring/50", className)}
      {...props}
    />
  )
}

export { Tabs, TabsList, TabsTab, TabsPanel }
