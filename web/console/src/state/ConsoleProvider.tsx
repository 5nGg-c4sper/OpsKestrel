import {
  createContext,
  useContext,
  type PropsWithChildren
} from "react";
import { api } from "../lib/api";
import { usePolling } from "../lib/hooks";
import type { Overview } from "../lib/types";

interface ConsoleContextValue {
  overview: Overview | null;
  error: Error | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

const ConsoleContext = createContext<ConsoleContextValue | null>(null);

export function ConsoleProvider({ children }: PropsWithChildren) {
  const polling = usePolling(api.overview, 5000, "overview");

  return (
    <ConsoleContext.Provider
      value={{
        overview: polling.data,
        error: polling.error,
        loading: polling.loading,
        refresh: polling.refresh
      }}
    >
      {children}
    </ConsoleContext.Provider>
  );
}

export function useConsole() {
  const value = useContext(ConsoleContext);
  if (!value) {
    throw new Error("useConsole must be used inside ConsoleProvider");
  }
  return value;
}
