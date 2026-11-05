import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setUnauthorizedHandler } from "./api";
import type { Category, Field, Format, Meta, Prefs, Role, User } from "./types";

interface AppState {
  user: User | null;
  meta: Meta | null;
  loading: boolean;
  setUser: (u: User | null) => void;
  refreshMeta: () => Promise<void>;
  setMeta: (m: Meta) => void;
  savePrefs: (p: Partial<Prefs>) => Promise<void>;
  can: (role: Role) => boolean;
  formatById: (id: number) => Format | undefined;
  categoryById: (id: number) => Category | undefined;
  fieldsFor: (formatIds: number[]) => Field[];
}

const Ctx = createContext<AppState | null>(null);

const RANK: Record<Role, number> = { viewer: 0, editor: 1, admin: 2 };

export function applyTheme(theme: Prefs["theme"]) {
  const root = document.documentElement;
  if (!theme || theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
  try {
    localStorage.setItem("mt-theme", theme || "system");
  } catch {
    /* storage unavailable */
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshMeta = useCallback(async () => {
    setMeta(await api.get<Meta>("/api/meta"));
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    api
      .get<User>("/api/auth/me")
      .then(async (u) => {
        setUser(u);
        applyTheme(u.prefs.theme);
        await refreshMeta();
      })
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, [refreshMeta]);

  useEffect(() => {
    if (user && !meta) refreshMeta().catch(() => {});
  }, [user, meta, refreshMeta]);

  const savePrefs = useCallback(
    async (p: Partial<Prefs>) => {
      if (!user) return;
      setUser({ ...user, prefs: { ...user.prefs, ...p } });
      const prefs = await api.put<Prefs>("/api/auth/prefs", p);
      setUser((u) => (u ? { ...u, prefs } : u));
    },
    [user]
  );

  const value = useMemo<AppState>(() => {
    const formats = new Map(meta?.formats.map((f) => [f.id, f]) ?? []);
    const cats = new Map(meta?.categories.map((c) => [c.id, c]) ?? []);
    return {
      user,
      meta,
      loading,
      setUser,
      refreshMeta,
      setMeta,
      savePrefs,
      can: (role) => !!user && RANK[user.role] >= RANK[role],
      formatById: (id) => formats.get(id),
      categoryById: (id) => cats.get(id),
      fieldsFor: (formatIds) =>
        (meta?.fields ?? []).filter((f) => f.applies_all || formatIds.some((id) => f.format_ids.includes(id))),
    };
  }, [user, meta, loading, refreshMeta, savePrefs]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp outside AppProvider");
  return v;
}
