import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  BadgeCheck,
  CheckCircle2,
  CircleAlert,
  CircleDollarSign,
  ClipboardCheck,
  Clock3,
  FileCheck2,
  FilePlus2,
  PackageCheck,
  Sparkles,
  Workflow,
} from "lucide-react";
import type { CurrentUser, Overview, ProcurementRecord } from "./api";
import { formatDate, formatMoney, FlowStep, MetricCard, RequestTable, statusFor } from "./ui";
import type { Page } from "./ui";
import { EmptyState } from "./ui";

export default function Dashboard({
  me,
  requests,
  overview,
  pendingCount,
  onCreate,
  onOpen,
  onPage,
}: {
  me: CurrentUser;
  requests: ProcurementRecord[];
  overview: Overview | null;
  pendingCount: number;
  onCreate: () => void;
  onOpen: (record: ProcurementRecord) => void;
  onPage: (page: Page) => void;
}) {
  const verifiedCount = (overview?.by_status.erp_verified ?? 0) + (overview?.by_status.closed ?? 0);
  const exceptionCount =
    (overview?.by_status.erp_unknown ?? 0) +
    (overview?.by_status.erp_mismatch ?? 0) +
    (overview?.by_status.erp_failed ?? 0) +
    (overview?.by_status.erp_unavailable ?? 0);
  const monthTotal = requests.reduce((total, item) => total + Number(item.amount_total), 0);
  const salutation = new Date().getHours() < 12 ? "上午好" : "下午好";
  const visibleTasks = me.role === "requester"
    ? requests.filter((item) => ["draft", "pending_manager", "pending_finance", "policy_review"].includes(item.status))
    : requests.filter((item) => item.status.startsWith("erp_") || item.status.startsWith("pending") || item.status === "policy_review");
  const recent = [...requests].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 5);

  return (
    <div className="dashboard-page">
      <div className="dashboard-topline">
        <div>
          <div className="eyebrow">PURCHASE OPERATIONS</div>
          <h1>采购协作工作台</h1>
          <p>{salutation}，{me.name}。把复杂流程收进一张清晰的工作台。</p>
        </div>
        {me.role === "requester" && <button className="button button-primary" onClick={onCreate} type="button"><FilePlus2 size={17} /> 新建采购申请</button>}
      </div>

      <section className="hero-panel">
        <div className="hero-grid-texture" />
        <div className="hero-content">
          <div className="hero-eyebrow"><Sparkles size={14} /> FLOW HEALTHY <span className="hero-eyebrow-dot" /> DEMO ENVIRONMENT</div>
          <h2>采购有序，决策更有底气。</h2>
          <p>申请、审批与 Odoo 草稿核验在同一条流程里连接起来。</p>
          <div className="hero-bottom">
            <span className="hero-status"><span className="live-dot" />系统运行正常</span>
            <span className="hero-divider" /><span>真实 Odoo 19 Community</span>
            <span className="hero-divider" /><span>金额口径 CNY</span>
          </div>
        </div>
        <div className="hero-illustration" aria-hidden="true">
          <div className="hero-ring ring-large" /><div className="hero-ring ring-small" />
          <div className="hero-orb"><Workflow size={43} strokeWidth={1.45} /></div>
          <div className="hero-float float-top"><CheckCircle2 size={15} /> 权限已验证</div>
          <div className="hero-float float-bottom"><PackageCheck size={15} /> 草稿可核验</div>
          <div className="hero-spark spark-a" /><div className="hero-spark spark-b" />
        </div>
      </section>

      <section className="metric-grid">
        <MetricCard
          label={me.role === "requester" ? "待处理申请" : me.role === "admin" ? "政策复核" : "待我处理"}
          value={String(pendingCount)}
          hint={me.role === "requester" ? "包含草稿与待审批" : "按当前身份与权限筛选"}
          icon={ClipboardCheck}
          tone="moss"
          trend={pendingCount ? "需要关注" : "当前无待办"}
          trendTone={pendingCount ? "positive" : "muted"}
        />
        <MetricCard label="ERP 已核验" value={String(verifiedCount)} hint="已从 Odoo 独立读回" icon={BadgeCheck} tone="blue" trend="仅草稿状态" trendTone="muted" />
        <MetricCard label="需人工处理" value={String(exceptionCount)} hint="未知、不匹配或远端不可用" icon={CircleAlert} tone="amber" trend={exceptionCount ? "先查后操作" : "暂无异常"} trendTone={exceptionCount ? "warning" : "muted"} />
        <MetricCard label="可见采购总额" value={formatMoney(monthTotal)} hint="按当前身份可见记录统计" icon={CircleDollarSign} tone="sand" trend="含税金额" trendTone="muted" />
      </section>

      <div className="dashboard-grid">
        <section className="surface-card queue-card">
          <div className="card-heading">
            <div><div className="eyebrow">PRIORITY QUEUE</div><h3>{me.role === "requester" ? "申请进度" : "需要关注"}</h3></div>
            <button className="text-button" onClick={() => onPage(me.role === "requester" ? "requests" : "approvals")} type="button">查看全部 <ArrowUpRight size={15} /></button>
          </div>
          {visibleTasks.length > 0 ? (
            <div className="queue-list">
              {visibleTasks.slice(0, 4).map((item) => (
                <button className="queue-item" key={item.id} onClick={() => onOpen(item)} type="button">
                  <div className={"queue-icon tone-" + statusFor(item.status).tone}>{item.status.startsWith("erp_") ? <PackageCheck size={17} /> : <FileCheck2 size={17} />}</div>
                  <div className="queue-main"><strong>{item.request_number} · {item.supplier.name}</strong><span>{item.department.name} · {formatMoney(item.amount_total)} · {formatDate(item.created_at)}</span></div>
                  <span className={"status-pill tone-" + statusFor(item.status).tone}><span className="status-dot" />{statusFor(item.status).label}</span>
                  <ArrowUpRight className="queue-arrow" size={16} />
                </button>
              ))}
            </div>
          ) : <EmptyState title="目前没有待处理事项" body="新的申请或审批任务会显示在这里。" icon={CheckCircle2} />}
        </section>

        <section className="surface-card flow-card">
          <div className="card-heading"><div><div className="eyebrow">FLOW SNAPSHOT</div><h3>流程健康度</h3></div><div className="snapshot-badge"><Activity size={14} />实时</div></div>
          <div className="flow-steps">
            <FlowStep number="01" title="申请提交" subtitle="明细与供应商" value={overview?.by_status.pending_manager ?? 0} tone="moss" />
            <div className="step-line" />
            <FlowStep number="02" title="审批决策" subtitle="经理 / 财务" value={(overview?.by_status.pending_manager ?? 0) + (overview?.by_status.pending_finance ?? 0)} tone="blue" />
            <div className="step-line" />
            <FlowStep number="03" title="ERP 核验" subtitle="独立读回" value={verifiedCount} tone="green" />
          </div>
          <div className="flow-foot"><span><span className="flow-live" />本地工作流在线</span><button className="text-button" onClick={() => onPage("erp")} type="button">查看 ERP 状态 <ArrowRight size={14} /></button></div>
        </section>
      </div>

      <section className="surface-card recent-card">
        <div className="card-heading"><div><div className="eyebrow">RECENT ACTIVITY</div><h3>最近采购申请</h3></div><button className="text-button" onClick={() => onPage("requests")} type="button">申请列表 <ArrowUpRight size={15} /></button></div>
        {recent.length > 0 ? <RequestTable records={recent} onOpen={onOpen} compact /> : <EmptyState title="还没有申请记录" body="从一份采购申请开始，体验完整的审批与 ERP 核验流程。" icon={Clock3} />}
      </section>
    </div>
  );
}
