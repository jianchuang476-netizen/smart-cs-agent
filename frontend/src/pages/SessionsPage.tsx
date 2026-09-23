import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";

export function SessionsPage() {
  const { data: sessions = [] } = useQuery({ queryKey: ["sessions"], queryFn: api.sessions });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const activeId = selectedId ?? sessions[0]?.id ?? null;
  const { data: activeMessages = [] } = useQuery({
    queryKey: ["messages", activeId],
    queryFn: () => api.messages(activeId!),
    enabled: Boolean(activeId),
  });

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">CONVERSATION ARCHIVE</span>
          <h1>会话记录</h1>
          <p>查看完整消息、引用来源和审批事件。</p>
        </div>
      </header>
      <div className="split-layout">
        <section className="list-card">
          {sessions.map((session) => (
            <button
              key={session.id}
              className={activeId === session.id ? "session-row active" : "session-row"}
              onClick={() => setSelectedId(session.id)}
            >
              <strong>{session.title}</strong>
              <small>{new Date(session.created_at).toLocaleString("zh-CN")}</small>
            </button>
          ))}
        </section>
        <section className="message-archive">
          {activeMessages.map((message) => (
            <article key={message.id} className={`archive-message ${message.role}`}>
              <span>{message.role === "assistant" ? "AI 客服" : "客户"}</span>
              <p>{message.content}</p>
              {!!message.event_metadata?.citations?.length && (
                <div className="citation-list">
                  {message.event_metadata.citations.map((citation, index) => (
                    <span key={`${citation.source}-${index}`}>{citation.title}</span>
                  ))}
                </div>
              )}
            </article>
          ))}
          {!activeMessages.length && <div className="empty-block">选择会话查看消息。</div>}
        </section>
      </div>
    </div>
  );
}
