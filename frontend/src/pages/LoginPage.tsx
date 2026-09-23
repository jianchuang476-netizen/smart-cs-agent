import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../AuthContext";

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("customer@example.com");
  const [password, setPassword] = useState("Demo123!");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  if (user) return <Navigate to="/chat" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      await login(email, password);
      navigate("/chat");
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <section className="login-story">
        <span className="eyebrow">SMART CS AGENT</span>
        <h1>让售后 Agent 有判断，也有边界。</h1>
        <p>政策检索、订单查询、风险审批和审计追踪，在一条可观测的 LangGraph 流程中完成。</p>
        <div className="story-grid">
          <span>混合 RAG</span>
          <span>人工审批</span>
          <span>全链路观测</span>
        </div>
      </section>
      <form className="login-card" onSubmit={submit}>
        <div>
          <span className="eyebrow">欢迎回来</span>
          <h2>登录客服工作台</h2>
          <p>演示密码统一为 Demo123!</p>
        </div>
        <label>
          邮箱
          <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" />
        </label>
        <label>
          密码
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            type="password"
          />
        </label>
        {error && <div className="form-error">{error}</div>}
        <button className="primary-button" disabled={loading}>
          {loading ? "登录中…" : "进入工作台"}
        </button>
        <div className="demo-accounts">
          <button type="button" onClick={() => setEmail("customer@example.com")}>客户</button>
          <button type="button" onClick={() => setEmail("agent@example.com")}>客服</button>
          <button type="button" onClick={() => setEmail("admin@example.com")}>管理员</button>
        </div>
      </form>
    </div>
  );
}
