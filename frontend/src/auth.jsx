import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, getToken, setToken } from "./api.js";
import { clearQueries } from "./lib/query.js";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getToken()) return setReady(true);
    api("/auth/me")
      .then((d) => setUser(d.user))
      .catch(() => setToken(null))
      .finally(() => setReady(true));
  }, []);

  useEffect(() => {
    const out = () => { clearQueries(); setUser(null); };
    window.addEventListener("bf:logout", out);
    return () => window.removeEventListener("bf:logout", out);
  }, []);

  const login = useCallback(async (username, password) => {
    const d = await api("/auth/login", { method: "POST", body: { username, password } });
    clearQueries();              // aucune donnée d'un compte précédent ne reste en cache
    setToken(d.token);
    setUser(d.user);
    return d.user;
  }, []);

  const register = useCallback(async (payload) => {
    const d = await api("/auth/register", { method: "POST", body: payload });
    clearQueries();
    setToken(d.token);
    setUser(d.user);
    return d.user;
  }, []);

  const logout = useCallback(() => {
    clearQueries();
    setToken(null);
    setUser(null);
    window.location.hash = "/login";
  }, []);

  return <AuthCtx.Provider value={{ user, ready, login, register, logout }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
