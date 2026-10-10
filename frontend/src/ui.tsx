export type Page = "dashboard" | "requests" | "approvals" | "erp" | "settings";
import {
  Activity,
  ArrowRight,
  BadgeCheck,
  ChevronRight,
  CircleAlert,
  CircleDollarSign,
  Clock3,
  FileText,
  PackageCheck,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import type { ProcurementRecord } from "./api";

export const statusMeta: Record<string, { label: string; tone: string; description: string }> = {
  draft: { label: "草稿", tone: "neutral", description: "尚未提交审批" },
  pending_manager: { label: "待部门审批", tone: "amber", description: "等待部门负责人审核" },
  pending_finance: { label: "待财务复核", tone: "blue", description: "等待另一名财务复核人" },
  policy_review: { label: "政策复核", tone: "violet", description: "超过自动审批范围，需人工判断" },
  rejected: { label: "已拒绝", tone: "red", description: "申请未通过" },
  cancelled: { label: "已撤销", tone: "neutral", description: "申请人已撤销" },
  approved: { label: "审批完成", tone: "green", description: "等待 ERP 草稿同步" },
  erp_pending: { label: "同步处理中", tone: "blue", description: "正在核对 Odoo 采购草稿" },
  erp_unavailable: { label: "ERP 不可用", tone: "amber", description: "远端暂不可查询，未盲目重试" },
  erp_unknown: { label: "结果待确认", tone: "amber", description: "写入结果未知，需先查询再处理" },
  erp_mismatch: { label: "数据不匹配", tone: "red", description: "远端字段与已批准版本不一致" },
  erp_failed: { label: "同步失败", tone: "red", description: "确定性错误，需要人工处理" },
  erp_verified: { label: "ERP 已核验", tone: "green", description: "草稿已从 Odoo 独立读回核对" },
  closed: { label: "已结案", tone: "neutral", description: "采购记录已归档" },
};

export function statusFor(status: string) {
  return statusMeta[status] ?? { label: status, tone: "neutral", description: "" };
}

export function formatMoney(value: string | number, currency = "CNY") {
  const numeric = typeof value === "number" ? value : Number(value || 0);
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(numeric);
}

export function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function initials(name: string) {
  return name.replace(/\s+/g, "").slice(0, 2);
}

export function StatusPill({ status }: { status: string }) {
  const meta = statusFor(status);
  return (
    <span className={"status-pill tone-" + meta.tone}>
      <span className="status-dot" />
      {meta.label}
    </span>
  );
}

export function SectionHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="section-heading">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function EmptyState({
  title,
  body,
  icon: Icon = FileText,
}: {
  title: string;
  body: string;
  icon?: LucideIcon;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon"><Icon size={23} strokeWidth={1.7} /></div>
      <strong>{title}</strong>
      <p>{body}</p>
    </div>
  );
}

export function MetricCard({
  label,
  value,
  hint,
  icon: Icon,
  tone,
  trend,
  trendTone,
}: {
  label: string;
  value: string;
  hint: string;
  icon: LucideIcon;
  tone: string;
  trend: string;
  trendTone: string;
}) {
  return (
    <article className="metric-card">
      <div className="metric-top">
        <span>{label}</span>
        <span className={"metric-icon tone-" + tone}><Icon size={18} strokeWidth={1.8} /></span>
      </div>
      <strong className="metric-value">{value}</strong>
      <div className="metric-bottom">
        <span>{hint}</span>
        <span className={"metric-trend " + trendTone}>{trend}</span>
      </div>
    </article>
  );
}

export function FlowStep({
  number,
  title,
  subtitle,
  value,
  tone,
}: {
  number: string;
  title: string;
  subtitle: string;
  value: number;
  tone: string;
}) {
  return (
    <div className="flow-step">
      <div className={"flow-number tone-" + tone}>{number}</div>
      <div className="flow-step-copy"><strong>{title}</strong><span>{subtitle}</span></div>
      <span className="flow-value">{value}</span>
    </div>
  );
}

export function RequestTable({
  records,
  onOpen,
  compact = false,
}: {
  records: ProcurementRecord[];
  onOpen: (record: ProcurementRecord) => void;
  compact?: boolean;
}) {
  return (
    <div className={"table-scroll " + (compact ? "compact-table" : "")}>
      <table className="request-table">
        <thead>
          <tr>
            <th>申请编号</th>
            <th>申请人 / 部门</th>
            <th>供应商</th>
            <th className="amount-column">含税总额</th>
            <th>状态</th>
            <th>更新时间</th>
            <th aria-label="操作" />
          </tr>
        </thead>
        <tbody>
          {records.map((item) => (
            <tr
              key={item.id}
              onClick={() => onOpen(item)}
              tabIndex={0}
              onKeyDown={(event) => event.key === "Enter" && onOpen(item)}
            >
              <td>
                <div className="request-ref"><span className="ref-icon"><FileText size={15} /></span><strong>{item.request_number}</strong></div>
                <small>{item.reason}</small>
              </td>
              <td>
                <strong className="table-primary">{item.requester.name}</strong>
                <small>{item.department.name}</small>
              </td>
              <td>
                <strong className="table-primary">{item.supplier.name}</strong>
                <small>{item.lines.length} 个明细 · {item.currency_code}</small>
              </td>
              <td className="amount-column">
                <strong className="table-amount">{formatMoney(item.amount_total, item.currency_code)}</strong>
                <small>未税 {formatMoney(item.amount_untaxed, item.currency_code)}</small>
              </td>
              <td><StatusPill status={item.status} /></td>
              <td><span className="table-date">{formatDate(item.updated_at)}</span></td>
              <td>
                <button
                  className="table-open"
                  aria-label={"查看 " + item.request_number}
                  onClick={(event) => { event.stopPropagation(); onOpen(item); }}
                  type="button"
                >
                  <ChevronRight size={17} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ApprovalTrackStep({
  title,
  person,
  done,
  active,
  result,
  last,
}: {
  title: string;
  person: string;
  done: boolean;
  active: boolean;
  result?: string;
  last?: boolean;
}) {
  const Icon = done ? BadgeCheck : active ? Clock3 : result === "mismatch" ? CircleAlert : PackageCheck;
  return (
    <div className={"approval-track-step " + (done ? "done" : active ? "active" : "")}>
      <div className="track-marker"><Icon size={13} /></div>
      <div className="track-copy"><strong>{title}</strong><span>{person}</span>{result && <small>{result === "approved" ? "已通过" : result === "rejected" ? "已拒绝" : result === "mismatch" ? "需复核" : "处理中"}</small>}</div>
      {!last && <span className="track-connector"><ArrowRight size={11} /></span>}
    </div>
  );
}

export function AuditIcon({ action }: { action: string }) {
  if (action.startsWith("erp.")) return <PackageCheck size={13} />;
  if (action.includes("policy")) return <CircleDollarSign size={13} />;
  return <Activity size={13} />;
}
