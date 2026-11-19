import { useCallback, useEffect, useState } from "react";
import { LOGOUT_EVENT, api, clearToken, getToken, saveToken } from "./api.js";
import AuthPage from "./components/AuthPage.jsx";
import Dashboard from "./components/Dashboard.jsx";

export default function App() {
  const [token, setToken] = useState(getToken);
  const [user, setUser] = useState(null);

  const logout = useCallback(() => {
    clearToken();
    setToken(null);
    setUser(null);
  }, []);

  function login(newToken) {
    saveToken(newToken);
    setToken(newToken);
  }

  useEffect(() => {
    window.addEventListener(LOGOUT_EVENT, logout);
    return () => window.removeEventListener(LOGOUT_EVENT, logout);
  }, [logout]);

  useEffect(() => {
    if (token) api.me().then(setUser).catch(logout);
  }, [token, logout]);

  if (!token) return <AuthPage onLogin={login} />;
  return <Dashboard user={user} onLogout={logout} />;
}
