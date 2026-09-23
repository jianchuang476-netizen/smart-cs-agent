import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./AuthContext";
import { Layout } from "./components/Layout";
import { ApprovalsPage } from "./pages/ApprovalsPage";
import { ChatPage } from "./pages/ChatPage";
import { KnowledgePage } from "./pages/KnowledgePage";
import { LoginPage } from "./pages/LoginPage";
import { SessionsPage } from "./pages/SessionsPage";

function ProtectedLayout() {
  const { user, loading } = useAuth();
  if (loading) return <div className="page-loader">正在加载工作台…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <Layout />;
}

function AdminOnly({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  return user?.role === "admin" ? children : <Navigate to="/chat" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedLayout />}>
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/sessions" element={<SessionsPage />} />
        <Route
          path="/approvals"
          element={
            <AdminOrAgent>
              <ApprovalsPage />
            </AdminOrAgent>
          }
        />
        <Route
          path="/knowledge"
          element={
            <AdminOnly>
              <KnowledgePage />
            </AdminOnly>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/chat" replace />} />
    </Routes>
  );
}

function AdminOrAgent({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  return user?.role === "agent" || user?.role === "admin" ? (
    children
  ) : (
    <Navigate to="/chat" replace />
  );
}
