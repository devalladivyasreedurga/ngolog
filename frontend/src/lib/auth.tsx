"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, getToken, setToken } from "./api";
import type { Role, User } from "./contracts";

interface AuthState {
  user: User | null;
  ready: boolean;
  signIn: (email: string, role: Role) => Promise<User>;
  signOut: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const check = getToken()
      ? api<User>("/api/auth/me").then(setUser).catch(() => setToken(null))
      : Promise.resolve();
    check.finally(() => setReady(true));
  }, []);

  const signIn = useCallback(async (email: string, role: Role) => {
    const res = await api<{ token: string; user: User }>("/api/auth/demo-login", { method: "POST", json: { email, role } });
    setToken(res.token);
    setUser(res.user);
    return res.user;
  }, []);

  const signOut = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  return <AuthContext.Provider value={{ user, ready, signIn, signOut }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
