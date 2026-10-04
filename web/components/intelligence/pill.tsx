import { cn } from "cn";

import { TILE_TONES, type TileTone } from "@/components/environment/parts";

/**
 * A word in a coloured pill — a line's tag, a priority, a recommendation's
 * chip, as the mockups draw them (LEKA-341). Always a word: the colour only
 * repeats it.
 */
export function Pill({
  tone,
  dot = false,
  className,
  children,
  ...rest
}: {
  tone: TileTone;
  /** A dot before the word, as the mockups' "● Élevée". */
  dot?: boolean;
  className?: string;
  children: React.ReactNode;
} & Omit<React.HTMLAttributes<HTMLSpanElement>, "className" | "children">) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap",
        TILE_TONES[tone],
        className,
      )}
      {...rest}
    >
      {dot ? <span aria-hidden="true" className="size-1.5 rounded-full bg-current" /> : null}
      {children}
    </span>
  );
}
