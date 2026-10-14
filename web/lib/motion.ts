/**
 * A spinner says « LEKA is working »: its turning is the state itself, so it
 * turns for everyone. Reduced motion asked, it turns slowly rather than not
 * at all. A still spinner reads as stuck (2026-10-14: « ça charge, ça ne
 * tourne pas »).
 */
export const SPINNING = "animate-spin motion-reduce:[animation-duration:2.4s]";
