import { createContext, useContext } from "react";

/** Whether the active workspace is a demonstration (LEKA-449), said by the
 * shell. Its own context, apart from the shell's: false wherever no shell
 * says otherwise — a test, a page drawn before the session is known. */
export const InDemoContext = createContext(false);

export function useInDemo(): boolean {
  return useContext(InDemoContext);
}
