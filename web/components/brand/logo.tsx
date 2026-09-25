import Image from "next/image";

import { cn } from "cn";

/**
 * LEKA's logo, in the one place it is drawn.
 *
 * Every screen that shows the brand uses these two, never a file path or a
 * colour of its own: when the logo changes again, it changes here and in
 * public/brand/, and nowhere else. See docs/frontend/design-system.md.
 *
 *   Wordmark  "LEKΛ", for where there is room: the sidebar, the sign-in pages
 *   Mark      the Λ alone, for where there is not: icons, the folded rail
 *
 * The originals are in docs/product/mockups/ (logoleka.jpeg, lekalogo2.jpeg).
 * The mark is redrawn as a vector from them; the wordmark is the original
 * with its grey ground made transparent (public/brand/leka-wordmark.png).
 */

const WORDMARK = { src: "/brand/leka-wordmark.png", width: 300, height: 72 };

// Measured on logoleka.jpeg (203 × 150), symmetric about its centre.
const MARK_PATH = "M83 0H120L203 150H153.5L101.5 55.5L49.5 150H0Z";

export function Wordmark({ className, priority }: { className?: string; priority?: boolean }) {
  return (
    <Image
      src={WORDMARK.src}
      width={WORDMARK.width}
      height={WORDMARK.height}
      alt="LEKA"
      priority={priority}
      className={cn("h-6 w-auto select-none", className)}
    />
  );
}

export function Mark({ className, title = "LEKA" }: { className?: string; title?: string }) {
  return (
    <svg viewBox="0 0 203 150" role="img" aria-label={title} className={cn("h-5 w-auto", className)}>
      <defs>
        <linearGradient id="leka-mark-gradient" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#5037fb" />
          <stop offset="1" stopColor="#6243fd" />
        </linearGradient>
      </defs>
      <path fill="url(#leka-mark-gradient)" d={MARK_PATH} />
    </svg>
  );
}
