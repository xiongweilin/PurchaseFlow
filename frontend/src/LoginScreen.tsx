import {
  Building2,
  Check,
  CircleDollarSign,
  FilePlus2,
  PackageCheck,
  Settings2,
  ShieldCheck,
  Users,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import type { Identity, Role } from "./api";
import { initials } from "./ui";

const roleLabels: Record<Role, string> = {
  requester: "申请人",
  manager: "部门负责人",
  finance: "财务复核",
  procurement: "采购运营",
  admin: "系统管理员",
};

const groups: Array<{ role: Role; title: string; icon: LucideIcon }> = [
  { role: "requester", title: "发起采购", icon: FilePlus2 },
  { role: "manager", title: "部门审批", icon: Users },
  { role: "finance", title: "财务复核", icon: CircleDollarSign },
  { role: "procurement", title: "ERP 核验", icon: PackageCheck },
  { role: "admin", title: "系统设置", icon: Settings2 },
];

export default function LoginScreen({
  identities,
  selectedEmail,
  onSelect,
  onLogin,
  loading,
}: {
  identities: Identity[];
  selectedEmail: string;
  onSelect: (email: string) => void;
  onLogin: () => void;
  loading: boolean;
}) {
  return (
    <div className="login-shell">
      <section className="login-story">
        <div className="login-grain" />
        <div className="login-story-top">
          <div className="brand-mark light"><Workflow size={22} /></div>
          <span>采购 · 审批 · ERP</span>
        </div>
        <div className="login-story-copy">
          <div className="eyebrow light-eyebrow"><span className="eyebrow-line" />采购从容，流程清晰</div>
          <h1>让每一笔采购<br /><em>有据可循</em></h1>
          <p>从部门申请到 Odoo 草稿核验，PurchaseFlow 把审批规则、金额口径与远端结果放在同一条可信流程里。</p>
          <div className="login-stat-row">
            <div><strong>2</strong><span>审批层级</span></div>
            <i />
            <div><strong>CNY</strong><span>本币核算</span></div>
            <i />
            <div><strong>Odoo 19</strong><span>真实草稿核验</span></div>
          </div>
        </div>
        <div className="login-story-foot">
          <div className="story-seal"><ShieldCheck size={17} /></div>
          <span>默认最小权限 · 所有金额由服务端 Decimal 计算</span>
        </div>
        <div className="story-orbit orbit-one" />
        <div className="story-orbit orbit-two" />
        <div className="story-orbit orbit-three" />
      </section>

      <section className="login-panel">
        <div className="login-card">
          <div className="login-card-heading">
            <div className="eyebrow">演示身份</div>
            <h2>进入采购协作空间</h2>
            <p>选择角色与演示成员，体验不同权限下的真实业务操作。</p>
          </div>
          <div className="identity-groups">
            {groups.map(({ role, title, icon: Icon }) => {
              const members = identities.filter((identity) => identity.role === role);
              if (members.length === 0) return null;
              return (
                <div className="identity-group" key={role}>
                  <div className="identity-group-title"><Icon size={15} /><span>{title}</span></div>
                  <div className="identity-options">
                    {members.map((identity) => {
                      const active = selectedEmail === identity.email;
                      return (
                        <button
                          className={"identity-option " + (active ? "selected" : "")}
                          key={identity.email}
                          onClick={() => onSelect(identity.email)}
                          type="button"
                          aria-pressed={active}
                        >
                          <span className={"identity-avatar role-" + role}>{initials(identity.name)}</span>
                          <span className="identity-copy"><strong>{identity.name}</strong><small>{identity.department_name ?? roleLabels[role]}</small></span>
                          {active ? <span className="radio-selected"><Check size={12} /></span> : <span className="radio-empty" />}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
          <button className="button button-primary login-submit" onClick={onLogin} disabled={!selectedEmail || loading} type="button">
            {loading ? <span className="button-spinner" /> : <>进入工作台 <span className="login-arrow">→</span></>}
          </button>
          <div className="login-note"><ShieldCheck size={14} /><span>受限演示身份，不是真实账号登录；角色由服务端校验。</span></div>
          {identities.length === 0 && <div className="login-error">演示数据尚未初始化。请先运行 bootstrap 脚本。</div>}
          <div className="login-organization">
            <Building2 size={15} /><span>Demo Office Ltd.</span><span className="org-dot" /><span>仅本地演示数据</span>
          </div>
        </div>
        <div className="login-footnote">安全演示 · 不会连接个人服务或真实外部邮箱</div>
      </section>
    </div>
  );
}
