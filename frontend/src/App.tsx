import {
  Bell,
  CheckCircle2,
  Building2,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  FileText,
  LayoutDashboard,
  LogOut,
  PackageCheck,
  Plus,
  RefreshCw,
  Settings2,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Catalog, type CurrentUser, type Identity, type Overview, type ProcurementRecord, type Role } from "./api";
import Composer from "./Composer";
import Dashboard from "./Dashboard";
import LoginScreen from "./LoginScreen";
import RequestDetail from "./RequestDetail";
import SettingsPage from "./SettingsPage";
import { ApprovalsPage, ErpPage, RequestList } from "./Worklists";
import { initials } from "./ui";
import type { Page } from "./ui";

const roleLabels: Record<Role, string> = {
  requester: "申请人",
  manager: "部门负责人",
  finance: "财务复核",
  procurement: "采购运营",
  admin: "系统管理员",
};

const navForRole: Record<Role, Array<{ page: Page; label: string; icon: LucideIcon }>> = {
  requester: [
    { page: "dashboard", label: "工作台", icon: LayoutDashboard },
    { page: "requests", label: "我的申请", icon: FileText },
  ],
  manager: [
    { page: "dashboard", label: "工作台", icon: LayoutDashboard },
    { page: "approvals", label: "部门审批", icon: ClipboardCheck },
    { page: "requests", label: "本部门申请", icon: FileText },
  ],
  finance: [
    { page: "dashboard", label: "工作台", icon: LayoutDashboard },
    { page: "approvals", label: "财务复核", icon: ClipboardCheck },
    { page: "requests", label: "采购全景", icon: FileText },
    { page: "erp", label: "ERP 状态", icon: PackageCheck },
  ],
  procurement: [
    { page: "dashboard", label: "工作台", icon: LayoutDashboard },
    { page: "erp", label: "ERP 核验", icon: PackageCheck },
    { page: "requests", label: "采购申请", icon: FileText },
  ],
  admin: [
    { page: "dashboard", label: "工作台", icon: LayoutDashboard },
    { page: "approvals", label: "政策复核", icon: ClipboardCheck },
    { page: "requests", label: "全部申请", icon: FileText },
    { page: "erp", label: "ERP 状态", icon: PackageCheck },
    { page: "settings", label: "系统设置", icon: Settings2 },
  ],
};

export default function App() {
  const [me, setMe] = useState<CurrentUser | null>(null);
  const [identities, setIdentities] = useState<Identity[]>([]);
  const [selectedIdentity, setSelectedIdentity] = useState("");
  const [page, setPage] = useState<Page>("dashboard");
  const [requests, setRequests] = useState<ProcurementRecord[]>([]);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [detail, setDetail] = useState<ProcurementRecord | null>(null);
  const [composer, setComposer] = useState<ProcurementRecord | null | "new">(null);
  const [toast, setToast] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const notify = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 4200);
  }, []);

  const loadUserData = useCallback(async () => {
    setRefreshing(true);
    try {
      const [nextRequests, nextOverview, nextCatalog] = await Promise.all([
        api.procurements(),
        api.overview(),
        api.catalog(),
      ]);
      setRequests(nextRequests);
      setOverview(nextOverview);
      setCatalog(nextCatalog);
    } catch (error) {
      notify(error instanceof Error ? error.message : "无法载入工作台数据。");
    } finally {
      setRefreshing(false);
    }
  }, [notify]);

  useEffect(() => {
    let live = true;
    api.me()
      .then((user) => {
        if (live) setMe(user);
      })
      .catch(async () => {
        try {
          const options = await api.identities();
          if (!live) return;
          setIdentities(options);
          const first = options.find((item) => item.role === "requester") ?? options[0];
          setSelectedIdentity(first?.email ?? "");
        } catch {
          if (live) setIdentities([]);
        }
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (me) void loadUserData();
  }, [me, loadUserData]);

  async function handleLogin() {
    const identity = identities.find((item) => item.email === selectedIdentity);
    if (!identity) return;
    setLoading(true);
    try {
      const user = await api.login(identity);
      setMe(user);
      setPage("dashboard");
      notify("欢迎回来，" + user.name);
    } catch (error) {
      notify(error instanceof Error ? error.message : "无法登录演示身份。");
    } finally {
      setLoading(false);
    }
  }

  async function handleLogout() {
    await api.logout().catch(() => undefined);
    setMe(null);
    setRequests([]);
    setOverview(null);
    setCatalog(null);
    setDetail(null);
    setComposer(null);
    const options = await api.identities().catch(() => []);
    setIdentities(options);
    setSelectedIdentity((options.find((item) => item.role === "requester") ?? options[0])?.email ?? "");
  }

  async function handleSaved(record: ProcurementRecord, isNew: boolean) {
    setComposer(null);
    await loadUserData();
    setDetail(record);
    notify(isNew ? "草稿已保存，可在详情中提交审批。" : "草稿已更新。");
  }

  async function handleChanged(record: ProcurementRecord, message: string) {
    setDetail(record);
    await loadUserData();
    notify(message);
  }

  const roleNav = me ? navForRole[me.role] : [];
  const pendingCount = useMemo(() => {
    if (!overview || !me) return 0;
    const count = overview.by_status;
    if (me.role === "requester") return count.draft ?? 0;
    if (me.role === "manager") return count.pending_manager ?? 0;
    if (me.role === "finance") return count.pending_finance ?? 0;
    if (me.role === "admin") return count.policy_review ?? 0;
    return (count.erp_unknown ?? 0) + (count.erp_mismatch ?? 0) + (count.erp_failed ?? 0);
  }, [overview, me]);

  if (loading && !me && identities.length === 0) {
    return <div className="boot-screen"><div className="boot-mark"><Workflow size={24} /></div><span>正在打开采购协作空间…</span></div>;
  }

  if (!me) {
    return <LoginScreen identities={identities} selectedEmail={selectedIdentity} onSelect={setSelectedIdentity} onLogin={() => void handleLogin()} loading={loading} />;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark"><Workflow size={21} strokeWidth={2.15} /></div>
          <div><div className="brand-name">PurchaseFlow</div><div className="brand-caption">采购协作平台</div></div>
        </div>
        <button className="tenant-switch" type="button">
          <div className="tenant-avatar"><Building2 size={17} /></div>
          <div className="tenant-copy"><strong>Demo Office Ltd.</strong><span>演示工作空间 · CNY</span></div>
          <ChevronDown size={15} />
        </button>
        <div className="nav-label">工作空间</div>
        <nav className="side-nav" aria-label="主导航">
          {roleNav.map((item) => {
            const Icon = item.icon;
            return (
              <button className={"nav-item " + (page === item.page ? "active" : "")} key={item.page} onClick={() => setPage(item.page)} type="button">
                <Icon size={18} strokeWidth={1.8} /><span>{item.label}</span>
                {item.page === "approvals" && pendingCount > 0 && <span className="nav-count">{pendingCount}</span>}
              </button>
            );
          })}
        </nav>
        {me.role === "requester" && <button className="sidebar-create" onClick={() => setComposer("new")} type="button"><Plus size={17} /> 创建采购申请</button>}
        <div className="sidebar-spacer" />
        <div className="sidebar-health"><div className="health-mark"><PackageCheck size={16} /></div><div><strong>连接状态正常</strong><span>本地流程服务已就绪</span></div></div>
        <div className="sidebar-footer">
          <div className="avatar avatar-sidebar">{initials(me.name)}</div>
          <div className="user-mini"><strong>{me.name}</strong><span>{roleLabels[me.role]}{me.department_name ? " · " + me.department_name : ""}</span></div>
          <button className="icon-button subtle" aria-label="退出演示身份" onClick={() => void handleLogout()} type="button"><LogOut size={16} /></button>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="mobile-brand"><div className="brand-mark"><Workflow size={19} /></div><strong>PurchaseFlow</strong></div>
          <div className="breadcrumbs"><span>Demo Office Ltd.</span><ChevronRight size={14} /><strong>{roleNav.find((item) => item.page === page)?.label ?? "工作台"}</strong></div>
          <div className="topbar-actions">
            <span className="environment-badge"><span />本地演示</span>
            <button className="icon-button topbar-icon" aria-label="刷新工作台" onClick={() => void loadUserData()} type="button"><RefreshCw size={17} className={refreshing ? "spin" : ""} /></button>
            <button className="icon-button topbar-icon notification-button" aria-label="通知" onClick={() => setPage(me.role === "requester" ? "requests" : "approvals")} type="button"><Bell size={17} />{pendingCount > 0 && <span className="notification-dot" />}</button>
            <button className="profile-chip" onClick={() => void handleLogout()} type="button" title="切换演示身份">
              <span className="avatar">{initials(me.name)}</span><span className="profile-text"><strong>{me.name}</strong><small>{roleLabels[me.role]}</small></span><ChevronDown size={14} />
            </button>
          </div>
        </header>

        <main className="page-content">
          {page === "dashboard" && <Dashboard me={me} requests={requests} overview={overview} pendingCount={pendingCount} onCreate={() => setComposer("new")} onOpen={setDetail} onPage={setPage} />}
          {page === "requests" && <RequestList me={me} requests={requests} onCreate={() => setComposer("new")} onOpen={setDetail} />}
          {page === "approvals" && <ApprovalsPage me={me} requests={requests} onOpen={setDetail} />}
          {page === "erp" && <ErpPage requests={requests} onOpen={setDetail} />}
          {page === "settings" && me.role === "admin" && <SettingsPage notify={notify} />}
          <footer className="page-footer"><span>PurchaseFlow Mini · 仅创建 Odoo 草稿，不确认采购、不付款</span><span>安全运行 <span className="footer-dot" /> CNY · 中国</span></footer>
        </main>
      </div>

      {composer && catalog && <Composer me={me} catalog={catalog} initial={composer === "new" ? null : composer} onCancel={() => setComposer(null)} onSaved={(item) => void handleSaved(item, composer === "new")} notify={notify} />}
      {detail && <RequestDetail record={detail} me={me} onClose={() => setDetail(null)} onEdit={(item) => { setDetail(null); setComposer(item); }} onChanged={handleChanged} notify={notify} />}
      {toast && <div className="toast"><CheckCircle2 size={17} />{toast}</div>}
    </div>
  );
}
