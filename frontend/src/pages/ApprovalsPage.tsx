import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, streamSse } from "../lib/api";
import type { Approval, SseEvent } from "../types";

export function ApprovalsPage() {
  const queryClient = useQueryClient();
  const { data: approvals = [], refetch } = useQuery({
    queryKey: ["approvals"],
    queryFn: api.approvals,
  });
  const [selected, setSelected] = useState<Approval | null>(null);
  const [comment, setComment] = useState("");
  const [result, setResult] = useState("");
  const [working, setWorking] = useState(false);

  async function decide(decision: "approved" | "rejected") {
    if (!selected) return;
    setWorking(true);
    setResult("审批处理中…");
    try {
      await streamSse(
        `/approvals/${selected.id}/decision`,
        { decision, comment, version: selected.version },
        (event: SseEvent) => {
          if (event.event === "token") {
            setResult((current) => current + String(event.data.content ?? ""));
          } else if (event.event === "error") {
            setResult(`失败：${String(event.data.message)}`);
          } else if (event.event === "done") {
            setResult((current) => current || (decision === "approved" ? "操作已执行。" : "申请已拒绝。"));
          }
        },
      );
      await refetch();
      await queryClient.invalidateQueries({ queryKey: ["sessions"] });
    } catch (error) {
      setResult(error instanceof Error ? error.message : "审批失败");
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">HUMAN REVIEW</span>
          <h1>审批队列</h1>
          <p>资金、退款和订单状态变更在人工确认前不会执行。</p>
        </div>
        <span className="count-badge">{approvals.length} 待处理</span>
      </header>

      <div className="approval-layout">
        <section className="list-card">
          {approvals.map((approval) => (
            <button
              key={approval.id}
              className={selected?.id === approval.id ? "approval-row active" : "approval-row"}
              onClick={() => {
                setSelected(approval);
                setResult("");
                setComment("");
              }}
            >
              <span className="risk-tag">{approval.action_type}</span>
              <strong>{String(approval.payload.order_no ?? "未关联订单")}</strong>
              <small>{new Date(approval.created_at).toLocaleString("zh-CN")}</small>
            </button>
          ))}
          {!approvals.length && <div className="empty-block">暂无待审批操作。</div>}
        </section>

        <section className="detail-card">
          {selected ? (
            <>
              <span className="eyebrow">REQUEST DETAIL</span>
              <h2>{selected.action_type}</h2>
              {selected.error_message && <div className="inline-error">{selected.error_message}</div>}
              <dl className="detail-grid">
                {Object.entries(selected.payload).map(([key, value]) => (
                  <div key={key}>
                    <dt>{key}</dt>
                    <dd>{String(value ?? "-")}</dd>
                  </div>
                ))}
              </dl>
              <label>
                审批意见
                <textarea
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="可选：说明批准或拒绝原因"
                  rows={3}
                />
              </label>
              <div className="button-row">
                <button className="danger-button" disabled={working} onClick={() => decide("rejected")}>
                  拒绝
                </button>
                <button className="primary-button" disabled={working} onClick={() => decide("approved")}>
                  批准并执行
                </button>
              </div>
              {result && <div className="result-box">{result}</div>}
            </>
          ) : (
            <div className="empty-block">选择左侧申请查看详情。</div>
          )}
        </section>
      </div>
    </div>
  );
}
