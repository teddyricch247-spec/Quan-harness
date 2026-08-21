import { useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { supabase } from './supabaseClient.js';
import Login from './pages/Login.jsx';
import ProjectList from './pages/ProjectList.jsx';
import SessionList from './pages/SessionList.jsx';
import SessionView from './pages/SessionView.jsx';

export default function App() {
  const [session, setSession] = useState(undefined); // undefined = not checked yet, null = signed out

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);

  if (session === undefined) return null; // brief blank frame while we check for an existing session

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={session ? <Navigate to="/" replace /> : <Login />} />
        <Route path="/" element={session ? <ProjectList /> : <Navigate to="/login" replace />} />
        <Route path="/project/:projectId" element={session ? <SessionList /> : <Navigate to="/login" replace />} />
        <Route
          path="/project/:projectId/session/:sessionId"
          element={session ? <SessionView /> : <Navigate to="/login" replace />}
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
