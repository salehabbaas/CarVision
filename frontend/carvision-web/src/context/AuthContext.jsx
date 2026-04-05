import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { request } from '../lib/api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem('carvision_token') || '');
  const [user, setUser] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('carvision_user') || 'null');
    } catch {
      return null;
    }
  });
  const [loading, setLoading] = useState(Boolean(token));

  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }
    let alive = true;
    request('/api/v1/auth/me', { token })
      .then((me) => {
        if (!alive) return;
        setUser(me);
        localStorage.setItem('carvision_user', JSON.stringify(me));
      })
      .catch(() => {
        if (!alive) return;
        setToken('');
        setUser(null);
        localStorage.removeItem('carvision_token');
        localStorage.removeItem('carvision_user');
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [token]);

  const value = useMemo(
    () => ({
      token,
      user,
      loading,
      isAuthenticated: Boolean(token && user),
      async login(username, password) {
        const res = await request('/api/v1/auth/login', {
          method: 'POST',
          body: { username, password },
        });
        setToken(res.access_token);
        setUser(res.user);
        localStorage.setItem('carvision_token', res.access_token);
        localStorage.setItem('carvision_user', JSON.stringify(res.user));
      },
      logout() {
        setToken('');
        setUser(null);
        localStorage.removeItem('carvision_token');
        localStorage.removeItem('carvision_user');
      },
    }),
    [token, user, loading]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
