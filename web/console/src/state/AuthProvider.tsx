import {
  createContext,
  useContext,
  useEffect,
  useState,
  type PropsWithChildren
} from "react";
import { api } from "../lib/api";
import type { OperatorSession } from "../lib/types";

const TOKEN_KEY = "opskestrel-review-token";

interface AuthContextValue {
  token: string;
  session: OperatorSession | null;
  loading: boolean;
  authenticate: (token: string) => Promise<OperatorSession>;
  disconnect: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const [token, setToken] = useState(
    () => sessionStorage.getItem(TOKEN_KEY) ?? ""
  );
  const [session, setSession] = useState<OperatorSession | null>(null);
  const [loading, setLoading] = useState(Boolean(token));

  const disconnect = () => {
    sessionStorage.removeItem(TOKEN_KEY);
    setToken("");
    setSession(null);
  };

  const authenticate = async (nextToken: string) => {
    const normalized = nextToken.trim();
    if (!normalized) {
      throw new Error("Enter the operator access token.");
    }
    setLoading(true);
    try {
      const nextSession = await api.operatorSession(normalized);
      sessionStorage.setItem(TOKEN_KEY, normalized);
      setToken(normalized);
      setSession(nextSession);
      return nextSession;
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }
    let active = true;
    api
      .operatorSession(token)
      .then((nextSession) => {
        if (active) {
          setSession(nextSession);
        }
      })
      .catch(() => {
        if (active) {
          disconnect();
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [token]);

  return (
    <AuthContext.Provider
      value={{
        token,
        session,
        loading,
        authenticate,
        disconnect
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return value;
}
