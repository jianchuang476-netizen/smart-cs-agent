import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, streamSse } from "../lib/api";
import type { Approval, Citation, Message, SseEvent } from "../types";

interface UiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  error?: string;
}

function toUiMessage(message: Message): UiMessage {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    citations: message.event_metadata?.citations,
    error: message.event_metadata?.error,
  };
}

export function ChatPage() {
  const queryClient = useQueryClient();
  const { data: sessions = [] } = useQuery({ queryKey: ["sessions"], queryFn: api.sessions });
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [status, setStatus] = useState("等待客户提问");
  const [approval, setApproval] = useState<Approval | null>(null);
  const [feedback, setFeedback] = useState("");
  const knownMessageIds = useRef<Set<string>>(new Set());
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!activeSession) {
      setMessages([]);
      knownMessageIds.current = new Set();
      return;
    }

    let cancelled = false;
    const loadMessages = async () => {
      const items = await api.messages(activeSession);
      if (cancelled) return;
      const newItems = items.filter((item) => !knownMessageIds.current.has(item.id));
      const approvalFeedback = newItems.find(
        (item) => item.role === "assistant" && item.event_metadata?.approval_status,
      );
      if (approvalFeedback) setFeedback(approvalFeedback.content);
      knownMessageIds.current = new Set(items.map((item) => item.id));
      setMessages(items.map(toUiMessage));
    };

    void loadMessages();
    const timer = window.setInterval(() => void loadMessages(), 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeSession]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, status]);

  async function sendMessage(text = input) {
    const content = text.trim();
    if (!content || sending) return;
    setInput("");
    setSending(true);
    setStatus("主管正在判断意图…");
    setApproval(null);
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: "user", content },
      { id: crypto.randomUUID(), role: "assistant", content: "" },
    ]);

    const handleEvent = (event: SseEvent) => {
      if (event.event === "session") {
        const sessionId = String(event.data.session_id);
        setActiveSession(sessionId);
      } else if (event.event === "token") {
        setStatus("正在生成回复…");
        setMessages((current) => {
          const next = [...current];
          const last = next[next.length - 1];
          if (last?.role === "assistant") last.content += String(event.data.content ?? "");
          return next;
        });
      } else if (event.event === "tool_call") {
        setStatus(event.data.phase === "start" ? `正在调用 ${event.data.tool}` : "工具调用完成");
      } else if (event.event === "citation") {
        setMessages((current) => {
          const next = [...current];
          const last = next[next.length - 1];
          if (last?.role === "assistant") {
            last.citations = [...(last.citations ?? []), event.data as unknown as Citation];
          }
          return next;
        });
      } else if (event.event === "approval_required") {
        setStatus("等待人工审批");
        setApproval(event.data as unknown as Approval);
      } else if (event.event === "done") {
        setStatus("处理完成");
      } else if (event.event === "error") {
        setStatus("处理失败");
        setMessages((current) => {
          const next = [...current];
          const last = next[next.length - 1];
          if (last?.role === "assistant") last.error = String(event.data.message);
          return next;
        });
      }
    };

    try {
      await streamSse(
        "/chat/stream",
        { message: content, session_id: activeSession, client_message_id: crypto.randomUUID() },
        handleEvent,
      );
      await queryClient.invalidateQueries({ queryKey: ["sessions"] });
    } catch (error) {
      setStatus("请求失败");
      setMessages((current) => {
        const next = [...current];
        const last = next[next.length - 1];
        if (last?.role === "assistant") {
          last.error = error instanceof Error ? error.message : "请求失败";
        }
        return next;
      });
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="chat-workspace">
      <section className="conversation-rail">
        <div className="section-heading">
          <div>
            <span className="eyebrow">CONVERSATIONS</span>
            <h2>客户会话</h2>
          </div>
          <button
            className="icon-button"
            onClick={() => {
              setActiveSession(null);
              setMessages([]);
              setApproval(null);
            }}
            title="新建会话"
          >
            +
          </button>
        </div>
        <div className="conversation-list">
          {sessions.map((session) => (
            <button
              key={session.id}
              className={activeSession === session.id ? "conversation active" : "conversation"}
              onClick={() => setActiveSession(session.id)}
            >
              <strong>{session.title}</strong>
              <small>{new Date(session.created_at).toLocaleString("zh-CN")}</small>
            </button>
          ))}
          {!sessions.length && <div className="empty-note">还没有会话，直接开始提问吧。</div>}
        </div>
      </section>

      <section className="chat-panel">
        <header className="chat-header">
          <div>
            <span className="eyebrow">LIVE AGENT</span>
            <h1>售后智能客服</h1>
          </div>
          <span className={sending ? "status-pill live" : "status-pill"}>{status}</span>
        </header>

        <div className="message-list">
          {feedback && (
            <div className="feedback-banner">
              <span>{feedback}</span>
              <button type="button" onClick={() => setFeedback("")}>×</button>
            </div>
          )}
          {!messages.length && (
            <div className="welcome-card">
              <span className="orb">SC</span>
              <h2>今天需要处理什么售后问题？</h2>
              <p>可以查询售后政策、订单物流，也可以发起需要人工审批的退款申请。</p>
              <div className="prompt-grid">
                <button onClick={() => sendMessage("七天无理由退货政策是什么？")}>查询退货政策</button>
                <button onClick={() => sendMessage("帮我查订单 ORD202600001 的物流")}>查询订单物流</button>
                <button onClick={() => sendMessage("订单 ORD202600002 我要退款 99 元")}>发起退款审批</button>
              </div>
            </div>
          )}
          {messages.map((message) => (
            <article key={message.id} className={`message ${message.role}`}>
              <div className="avatar">{message.role === "assistant" ? "AI" : "客"}</div>
              <div className="bubble">
                <p>{message.content || (message.role === "assistant" && sending ? "思考中…" : "")}</p>
                {!!message.citations?.length && (
                  <div className="citation-list">
                    {message.citations.map((citation, index) => (
                      <span key={`${citation.source}-${index}`} title={citation.content}>
                        [{index + 1}] {citation.title || citation.source}
                      </span>
                    ))}
                  </div>
                )}
                {message.error && <div className="inline-error">{message.error}</div>}
              </div>
            </article>
          ))}
          {approval && (
            <div className="approval-callout">
              <div>
                <span className="eyebrow">HUMAN IN THE LOOP</span>
                <strong>退款申请已暂停，等待客服审批</strong>
                <p>审批编号：{approval.id ?? approval.approval_id ?? "已创建"}</p>
              </div>
              <span className="pending-dot">待处理</span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <form
          className="composer"
          onSubmit={(event) => {
            event.preventDefault();
            void sendMessage();
          }}
        >
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="输入订单、物流或退款问题…"
            rows={2}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void sendMessage();
              }
            }}
          />
          <button className="primary-button" disabled={sending || !input.trim()}>
            发送
          </button>
        </form>
      </section>
    </div>
  );
}
