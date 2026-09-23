import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../AuthContext";

export function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login");
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">SC</span>
          <div>
            <strong>Smart CS</strong>
            <small>企业售后服务台</small>
          </div>
        </div>
        <nav>
          <NavLink to="/chat">客户聊天</NavLink>
          <NavLink to="/sessions">会话记录</NavLink>
          {(user?.role === "agent" || user?.role === "admin") && (
            <NavLink to="/approvals">审批队列</NavLink>
          )}
          {user?.role === "admin" && <NavLink to="/knowledge">知识库管理</NavLink>}
        </nav>
        <div className="profile-card">
          <span className={`role-dot ${user?.role}`} />
          <div>
            <strong>{user?.display_name}</strong>
            <small>{user?.role}</small>
          </div>
          <button className="icon-button" onClick={handleLogout} title="退出登录">↗</button>
        </div>
      </aside>
      <main className="main-panel">
        <Outlet />
      </main>
    </div>
  );
}
