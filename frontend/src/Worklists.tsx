import {
  ArrowRight,
  BadgeCheck,
  CheckCircle2,
  ChevronDown,
  Clock3,
  ChevronRight,
  Filter,
  PackageCheck,
  Search,
  ShieldCheck,
  Truck,
} from "lucide-react";
import { useMemo, useState } from "react";
import type { CurrentUser, ProcurementRecord } from "./api";
import { EmptyState, formatDate, formatMoney, RequestTable, SectionHeading, StatusPill, statusMeta } from "./ui";

export function RequestList({
  me,
  requests,
  onCreate,
  onOpen,
}: {
  me: CurrentUser;
  requests: ProcurementRecord[];
  onCreate: () => void;
  onOpen: (record: ProcurementRecord) => void;
}) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const filtered = useMemo(() => requests.filter((item) => {
    const matchSearch = [item.request_number, item.supplier.name, item.reason, item.requester.name]
      .join(" ").toLowerCase().includes(search.toLowerCase());
    return matchSearch && (statusFilter === "all" || item.status === statusFilter);
  }), [requests, search, statusFilter]);
  const isRequester = me.role === "requester";

  return (
    <div className="list-page">
      <SectionHeading
        eyebrow="PROCUREMENT REGISTER"
        title={isRequester ? "我的采购申请" : "采购申请"}
        description={isRequester ? "集中查看草稿、审批进度与 ERP 核验结果。" : "按组织权限查看申请、审批与远端同步状态。"}
        action={isRequester ? <button className="button button-primary" onClick={onCreate} type="button"><span>＋</span> 新建申请</button> : undefined}
      />
      <section className="surface-card list-surface">
        <div className="list-toolbar">
          <div className="search-field">
            <Search size={17} />
            <input aria-label="搜索采购申请" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索编号、供应商或申请事由" />
            <kbd>⌘ K</kbd>
          </div>
          <div className="toolbar-right">
            <label className="filter-select">
              <Filter size={15} />
              <select aria-label="按状态筛选" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="all">全部状态</option>
                {Object.entries(statusMeta).map(([value, meta]) => <option value={value} key={value}>{meta.label}</option>)}
              </select>
              <ChevronDown size={14} />
            </label>
            <span className="result-count">{filtered.length} 条记录</span>
          </div>
        </div>
        {filtered.length > 0 ? <RequestTable records={filtered} onOpen={onOpen} /> : <EmptyState title="没有找到采购申请" body="尝试更换搜索词或筛选条件。" icon={Search} />}
      </section>
    </div>
  );
}

export function ApprovalsPage({
  me,
  requests,
  onOpen,
}: {
  me: CurrentUser;
  requests: ProcurementRecord[];
  onOpen: (record: ProcurementRecord) => void;
}) {
  const queue = requests.filter((item) => {
    if (me.role === "admin") return item.status === "policy_review";
    if (me.role === "manager") return item.status === "pending_manager";
    if (me.role === "finance") return item.status === "pending_finance";
    return false;
  });
  const title = me.role === "admin" ? "政策复核" : me.role === "finance" ? "财务复核" : "部门审批";
  const description = me.role === "admin"
    ? "超过演示政策范围的申请进入人工复核，不会自动写入 ERP。"
    : "审批前核对事由、明细、未税金额、税额与含税总额。";

  return (
    <div className="approval-page">
      <SectionHeading eyebrow="REVIEW QUEUE" title={title} description={description} />
      <div className="approval-hero">
        <div className="approval-hero-icon"><ShieldCheck size={23} /></div>
        <div><strong>审批事实已冻结</strong><span>申请提交后，供应商、商品、数量、币种与金额不可修改。</span></div>
        <div className="approval-hero-side"><span>当前待处理</span><strong>{queue.length.toString().padStart(2, "0")}</strong></div>
      </div>
      {queue.length > 0 ? (
        <div className="approval-grid">
          {queue.map((item) => (
            <button className="approval-card" key={item.id} onClick={() => onOpen(item)} type="button">
              <div className="approval-card-top"><StatusPill status={item.status} /><span className="approval-age"><Clock3 size={13} />{formatDate(item.created_at)}</span></div>
              <div className="approval-card-title">{item.request_number}</div>
              <p>{item.reason}</p>
              <div className="approval-card-vendor"><span className="vendor-monogram">{item.supplier.name.replace(/\s/g, "").slice(0, 2)}</span><span><strong>{item.supplier.name}</strong><small>{item.requester.name} · {item.department.name}</small></span></div>
              <div className="approval-card-amount"><span>含税总额</span><strong>{formatMoney(item.amount_total)}</strong></div>
              <div className="approval-card-foot"><span>{item.lines.length} 项明细 · {item.currency_code}</span><span className="review-link">打开复核 <ArrowRight size={14} /></span></div>
            </button>
          ))}
        </div>
      ) : <section className="surface-card approval-empty-card"><EmptyState title="当前没有待处理申请" body="新申请进入审批队列后，会在这里显示完整金额口径与审批事实。" icon={CheckCircle2} /></section>}
    </div>
  );
}

export function ErpPage({
  requests,
  onOpen,
}: {
  requests: ProcurementRecord[];
  onOpen: (record: ProcurementRecord) => void;
}) {
  const erpRequests = requests.filter((item) => item.erp || item.status === "approved");
  const completed = erpRequests.filter((item) => item.status === "erp_verified" || item.status === "closed").length;
  const attention = erpRequests.filter((item) => ["erp_unknown", "erp_mismatch", "erp_failed", "erp_unavailable"].includes(item.status)).length;
  return (
    <div className="erp-page">
      <SectionHeading eyebrow="ODOO DRAFT CONTROL" title="ERP 草稿核验" description="只把已经批准的版本写入 Odoo；响应成功不是完成，独立读回才是。" />
      <div className="erp-summary-grid">
        <div className="erp-summary-card"><span className="erp-summary-icon green"><CheckCircle2 size={19} /></span><div><small>已核验草稿</small><strong>{completed}</strong><em>Odoo 独立读回匹配</em></div></div>
        <div className="erp-summary-card"><span className="erp-summary-icon amber"><Clock3 size={19} /></span><div><small>人工处理</small><strong>{attention}</strong><em>先查结果，再决定是否重试</em></div></div>
        <div className="erp-summary-card wide">
          <div className="erp-flow-mini"><span><CheckCircle2 size={15} />已批准</span><i /><span><Truck size={15} />创建草稿</span><i /><span><BadgeCheck size={15} />独立核验</span></div>
          <small>自动化边界</small><p>不会确认采购单、收货、开票或付款。所有接口调用使用受限 Odoo 集成用户。</p>
        </div>
      </div>
      <section className="surface-card list-surface">
        <div className="card-heading erp-list-heading"><div><div className="eyebrow">SYNC REGISTER</div><h3>采购同步记录</h3></div><span className="quiet-label"><span className="live-dot dark" />独立 PostgreSQL · CNY</span></div>
        {erpRequests.length > 0 ? (
          <div className="erp-request-list">
            {erpRequests.map((item) => (
              <button className="erp-row" key={item.id} onClick={() => onOpen(item)} type="button">
                <span className={"erp-row-icon " + (item.status === "erp_verified" ? "verified" : "attention")}><PackageCheck size={18} /></span>
                <span className="erp-row-main"><strong>{item.request_number}</strong><small>{item.supplier.name} · {item.lines.length} 项 · {formatMoney(item.amount_total)}</small></span>
                {item.erp?.remote_order_name && <span className="odoo-ref"><span>ODOO</span>{item.erp.remote_order_name}</span>}
                <StatusPill status={item.status} />
                <ChevronRight size={17} className="queue-arrow" />
              </button>
            ))}
          </div>
        ) : <EmptyState title="暂无 ERP 同步记录" body="所有批准后的请求会进入异步队列，并通过稳定意图标记核对 Odoo。" icon={PackageCheck} />}
      </section>
    </div>
  );
}
