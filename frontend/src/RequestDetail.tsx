import {
  Activity,
  ArrowRight,
  BadgeCheck,
  Check,
  CheckCircle2,
  Clock3,
  PackageCheck,
  RefreshCw,
  ShieldCheck,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api, type CurrentUser, type Decision, type ProcurementRecord } from "./api";
import { ApprovalTrackStep, AuditIcon, EmptyState, formatDate, formatMoney, StatusPill, statusFor } from "./ui";

export default function RequestDetail({
  record,
  me,
  onClose,
  onEdit,
  onChanged,
  notify,
}: {
  record: ProcurementRecord;
  me: CurrentUser;
  onClose: () => void;
  onEdit: (record: ProcurementRecord) => void;
  onChanged: (record: ProcurementRecord, message: string) => Promise<void>;
  notify: (message: string) => void;
}) {
  const [current, setCurrent] = useState(record);
  const [working, setWorking] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [activeTab, setActiveTab] = useState<"overview" | "history">("overview");
  const erpDifferences = current.erp?.observation?.differences;

  useEffect(() => {
    setCurrent(record);
    let live = true;
    api.procurement(record.id)
      .then((fresh) => { if (live) setCurrent(fresh); })
      .catch(() => undefined);
    return () => { live = false; };
  }, [record.id]);

  async function applyAction(action: string) {
    setWorking(true);
    try {
      let updated: ProcurementRecord;
      let message = "操作已完成。";
      if (action === "submit") {
        updated = await api.submit(current.id, current.version);
        message = "申请已提交，进入审批队列。";
      } else if (action === "cancel") {
        updated = await api.cancel(current.id, current.version);
        message = "申请已撤销。";
      } else if (action === "approve" || action === "reject") {
        const reason = action === "reject" ? (window.prompt("请填写拒绝原因") ?? "") : "";
        if (action === "reject" && !reason.trim()) return;
        updated = await api.decide(current.id, current.version, action as Decision, reason);
        message = action === "approve" ? "审批已记录。" : "申请已拒绝。";
      } else if (action === "policy-approve" || action === "policy-reject") {
        const reason = window.prompt("请记录政策例外的判断依据") ?? "";
        if (reason.trim().length < 5) return;
        updated = await api.policyReview(current.id, current.version, action === "policy-approve" ? "approve" : "reject", reason);
        message = action === "policy-approve" ? "例外已记录，仍需完成部门与财务审批。" : "政策复核已拒绝。";
      } else if (action === "reconcile") {
        updated = await api.reconcile(current.id);
        message = "已执行只读核验，没有发送新的创建请求。";
      } else if (action === "retry") {
        updated = await api.retry(current.id);
        message = "远端缺失已确认，原稳定意图已重新排队。";
      } else if (action === "close") {
        updated = await api.close(current.id, current.version);
        message = "采购记录已结案。";
      } else {
        return;
      }
      setCurrent(updated);
      await onChanged(updated, message);
    } catch (error) {
      notify(error instanceof Error ? error.message : "操作未完成。");
      try {
        const fresh = await api.procurement(current.id);
        setCurrent(fresh);
      } catch {
        // API 不可用时保留最后一次已授权的快照。
      }
    } finally {
      setWorking(false);
    }
  }

  async function refreshRemote() {
    setRefreshing(true);
    try {
      const fresh = await api.procurement(current.id);
      setCurrent(fresh);
      notify("已刷新最新状态。");
    } catch (error) {
      notify(error instanceof Error ? error.message : "无法刷新。");
    } finally {
      setRefreshing(false);
    }
  }

  const status = statusFor(current.status);
  const managerApproval = current.approvals.find((item) => item.stage === "manager");
  const financeApproval = current.approvals.find((item) => item.stage === "finance");

  return (
    <div className="drawer-scrim" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="detail-drawer" role="dialog" aria-modal="true" aria-labelledby="detail-title">
        <header className="detail-header">
          <div className="detail-header-overline"><span>采购申请</span><span className="crumb-slash">/</span><span>{current.request_number}</span></div>
          <div className="detail-header-main">
            <div><h2 id="detail-title">{current.request_number}</h2><StatusPill status={current.status} /></div>
            <div className="detail-header-actions">
              <button className="icon-button" aria-label="刷新申请状态" onClick={() => void refreshRemote()} type="button"><RefreshCw size={16} className={refreshing ? "spin" : ""} /></button>
              <button className="icon-button" aria-label="关闭详情" onClick={onClose} type="button"><X size={18} /></button>
            </div>
          </div>
        </header>

        <div className="detail-tabs">
          <button className={activeTab === "overview" ? "active" : ""} onClick={() => setActiveTab("overview")} type="button">申请详情</button>
          <button className={activeTab === "history" ? "active" : ""} onClick={() => setActiveTab("history")} type="button">审批与审计 <span>{current.audit_events.length + current.approvals.length}</span></button>
        </div>

        <div className="detail-body">
          {activeTab === "overview" ? (
            <>
              <div className={"detail-status-banner banner-" + status.tone}>
                <div className="detail-status-icon">{current.status === "erp_verified" ? <BadgeCheck size={18} /> : current.status.startsWith("erp_") ? <PackageCheck size={18} /> : <Clock3 size={18} />}</div>
                <div><strong>{status.label}</strong><span>{status.description}</span></div>
                <span className="version-tag">V{current.version}</span>
              </div>

              <section className="detail-section">
                <div className="detail-section-title"><span>01</span><h3>申请概览</h3></div>
                <div className="detail-facts">
                  <div><span>申请人</span><strong>{current.requester.name}</strong><small>{current.department.name} · {current.requester.email}</small></div>
                  <div><span>供应商</span><strong>{current.supplier.name}</strong><small>{current.supplier.reference}</small></div>
                  <div className="fact-full"><span>采购事由</span><p>{current.reason}</p></div>
                </div>
              </section>

              <section className="detail-section">
                <div className="detail-section-title"><span>02</span><h3>采购明细</h3><span className="detail-section-meta">{current.lines.length} 行 · {current.currency_code}</span></div>
                <div className="detail-lines">
                  <div className="detail-line-head"><span>商品</span><span>数量</span><span>未税单价</span><span>税额</span><span>含税金额</span></div>
                  {current.lines.map((line) => (
                    <div className="detail-line" key={line.id}>
                      <div><strong>{line.product_name}</strong><small>{line.sku} · {line.tax_rate}%</small></div>
                      <span>{line.quantity}</span>
                      <span>{formatMoney(line.unit_price)}</span>
                      <span>{formatMoney(line.amount_tax)}</span>
                      <strong>{formatMoney(line.amount_total)}</strong>
                    </div>
                  ))}
                </div>
                <div className="detail-totals">
                  <div><span>未税金额</span><strong>{formatMoney(current.amount_untaxed)}</strong></div>
                  <div><span>税额</span><strong>{formatMoney(current.amount_tax)}</strong></div>
                  <div className="detail-grand-total"><span>含税总额</span><strong>{formatMoney(current.amount_total)}</strong></div>
                </div>
              </section>

              <section className="detail-section approval-track-section">
                <div className="detail-section-title"><span>03</span><h3>审批路径</h3><span className="policy-version">政策 V{current.policy_version ?? "—"}</span></div>
                <div className="approval-track">
                  <ApprovalTrackStep title="申请提交" person={current.requester.name} done={current.status !== "draft"} active={current.status === "draft"} />
                  <ApprovalTrackStep title="部门负责人" person={managerApproval?.actor ?? current.department.name ?? "待指派"} done={Boolean(managerApproval)} active={current.status === "pending_manager"} result={managerApproval?.decision} />
                  <ApprovalTrackStep title="财务复核" person={financeApproval?.actor ?? "另一名财务人员"} done={Boolean(financeApproval)} active={current.status === "pending_finance"} result={financeApproval?.decision} />
                  <ApprovalTrackStep title="Odoo 草稿核验" person={current.erp?.remote_order_name ?? "等待审批完成"} done={current.status === "erp_verified" || current.status === "closed"} active={current.status === "erp_pending"} result={current.status === "erp_mismatch" ? "mismatch" : undefined} last />
                </div>
              </section>

              {(current.erp || current.status === "policy_review" || current.policy_review) && (
                <section className="detail-section">
                  <div className="detail-section-title"><span>04</span><h3>{current.status === "policy_review" ? "政策复核" : "ERP 核验结果"}</h3></div>
                  {current.policy_review && <div className="policy-review-result"><ShieldCheck size={16} /><div><strong>{current.policy_review.decision === "approved" ? "例外已批准" : "例外已拒绝"}</strong><span>{current.policy_review.reason}</span></div></div>}
                  {current.erp && (
                    <div className={"erp-detail-box erp-" + current.erp.state}>
                      <div className="erp-detail-main">
                        <span className="erp-detail-icon">{current.erp.state === "verified" ? <CheckCircle2 size={18} /> : <CircleAlertIcon />}</span>
                        <div><strong>{current.erp.state === "verified" ? "Odoo 采购草稿已核验" : current.erp.state === "unknown" ? "写入结果未知" : current.erp.state === "mismatch" ? "远端事实不匹配" : current.erp.state === "failed" ? "同步失败" : "Odoo 暂不可用"}</strong><small>{current.erp.remote_order_name ? "订单编号 " + current.erp.remote_order_name : status.description}</small></div>
                      </div>
                      {(me.role === "procurement" || me.role === "admin" || me.role === "finance") && current.erp.last_error && <p className="erp-error-message">{current.erp.last_error}</p>}
                      {current.erp.state === "mismatch" && erpDifferences && Object.keys(erpDifferences).length > 0 && (
                        <div className="erp-differences" role="alert">
                          <strong>结案已阻止：Odoo 实际字段与审批快照不一致</strong>
                          {Object.entries(erpDifferences).map(([field, difference]) => (
                            <div className="erp-difference-entry" key={field}>
                              <span>{field}</span>
                              <p><b>审批快照</b> {formatDifference(difference.expected)}</p>
                              <p><b>Odoo 实际</b> {formatDifference(difference.actual)}</p>
                            </div>
                          ))}
                        </div>
                      )}
                      <div className="erp-detail-meta"><span>稳定意图 {current.erp.external_intent_id ?? "已封装"}</span><span>尝试 {current.erp.attempts} 次</span></div>
                      <small className="erp-caution">结果成功后只保留草稿状态；不会确认采购。</small>
                    </div>
                  )}
                </section>
              )}
            </>
          ) : (
            <div className="history-timeline">
              {current.approvals.map((item) => (
                <div className="history-item" key={item.stage}>
                  <span className={"history-node " + (item.decision === "approved" ? "done" : "rejected")}><Check size={13} /></span>
                  <div className="history-copy"><strong>{item.stage === "manager" ? "部门负责人审批" : "财务复核"} · {item.decision === "approved" ? "通过" : "拒绝"}</strong><span>{item.actor} · {formatDate(item.decided_at)}</span>{item.reason && <p>{item.reason}</p>}</div>
                </div>
              ))}
              {current.policy_review && <div className="history-item"><span className="history-node done"><ShieldCheck size={13} /></span><div className="history-copy"><strong>政策例外 · {current.policy_review.decision === "approved" ? "批准" : "拒绝"}</strong><span>{current.policy_review.actor} · {formatDate(current.policy_review.decided_at)}</span><p>{current.policy_review.reason}</p></div></div>}
              {current.audit_events.map((item, index) => (
                <div className="history-item" key={item.action + item.occurred_at + index}>
                  <span className="history-node system"><AuditIcon action={item.action} /></span>
                  <div className="history-copy"><strong>{auditLabel(item.action)}</strong><span>{formatDate(item.occurred_at)}</span></div>
                </div>
              ))}
              {!current.approvals.length && !current.policy_review && !current.audit_events.length && <EmptyState title="暂无历史记录" body="流程事件将在这里依时间顺序呈现。" icon={Activity} />}
            </div>
          )}
        </div>

        <footer className="detail-footer">
          <div className="detail-footer-note"><span className="footer-lock"><ShieldCheck size={14} /></span><span>变更与审批已记录</span></div>
          <div className="detail-actions">
            {current.allowed_actions.includes("edit") && <button className="button button-ghost" onClick={() => onEdit(current)} type="button">编辑草稿</button>}
            {current.allowed_actions.includes("cancel") && <button className="button button-ghost danger-ghost" onClick={() => void applyAction("cancel")} disabled={working} type="button">撤销</button>}
            {current.allowed_actions.includes("submit") && <button className="button button-primary" onClick={() => void applyAction("submit")} disabled={working} type="button">{working ? <span className="button-spinner" /> : <>提交审批 <ArrowRight size={15} /></>}</button>}
            {current.allowed_actions.includes("approve") && <button className="button button-ghost" onClick={() => void applyAction("reject")} disabled={working} type="button">拒绝</button>}
            {current.allowed_actions.includes("approve") && <button className="button button-primary" onClick={() => void applyAction("approve")} disabled={working} type="button">{working ? <span className="button-spinner" /> : <>通过申请 <Check size={15} /></>}</button>}
            {current.allowed_actions.includes("policy_review") && <><button className="button button-ghost" onClick={() => void applyAction("policy-reject")} disabled={working} type="button">拒绝例外</button><button className="button button-primary" onClick={() => void applyAction("policy-approve")} disabled={working} type="button">记录例外通过</button></>}
            {current.allowed_actions.includes("reconcile") && <button className="button button-ghost" onClick={() => void applyAction("reconcile")} disabled={working} type="button"><RefreshCw size={15} /> 只读核验</button>}
            {current.allowed_actions.includes("retry") && <button className="button button-primary" onClick={() => void applyAction("retry")} disabled={working} type="button">确认缺失并重试</button>}
            {current.allowed_actions.includes("close") && <button className="button button-primary" onClick={() => void applyAction("close")} disabled={working} type="button">结案归档 <Check size={15} /></button>}
          </div>
        </footer>
      </aside>
    </div>
  );
}

function formatDifference(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.map(formatDifference).join(" · ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function CircleAlertIcon() {
  return <Clock3 size={18} />;
}

function auditLabel(action: string) {
  const labels: Record<string, string> = {
    "procurement.created": "申请草稿已创建",
    "procurement.draft_updated": "草稿信息已更新",
    "procurement.submitted": "申请已提交审批",
    "procurement.manager_approve": "部门审批已通过",
    "procurement.finance_approve": "财务复核已通过",
    "procurement.manager_reject": "部门审批已拒绝",
    "procurement.finance_reject": "财务复核已拒绝",
    "erp.intent_created": "稳定 ERP 意图已建立",
    "erp.verified": "Odoo 草稿已独立核验",
    "erp.unknown": "ERP 写入结果未知",
    "erp.mismatch": "远端事实出现差异",
    "erp.unavailable": "Odoo 暂不可用",
    "procurement.closed": "申请已结案",
    "procurement.cancelled": "申请已撤销",
  };
  return labels[action] ?? action.replaceAll(".", " · ");
}
