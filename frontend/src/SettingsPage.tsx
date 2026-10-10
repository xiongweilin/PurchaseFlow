import { ArrowRight, CheckCircle2, FileCheck2, HelpCircle, PackageCheck, ShieldCheck, Truck } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { api, type Policy } from "./api";
import { SectionHeading } from "./ui";

type Mappings = {
  suppliers: Array<Record<string, unknown>>;
  products: Array<Record<string, unknown>>;
};

export default function SettingsPage({ notify }: { notify: (message: string) => void }) {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [mappings, setMappings] = useState<Mappings | null>(null);
  const [managerLimit, setManagerLimit] = useState("");
  const [reviewLimit, setReviewLimit] = useState("");
  const [taxInclusive, setTaxInclusive] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    Promise.all([api.policy(), api.mappings()])
      .then(([nextPolicy, nextMappings]) => {
        setPolicy(nextPolicy);
        setMappings(nextMappings);
        setManagerLimit(nextPolicy.manager_limit);
        setReviewLimit(nextPolicy.policy_review_limit);
        setTaxInclusive(nextPolicy.tax_inclusive);
      })
      .catch((error) => notify(error instanceof Error ? error.message : "无法载入系统设置。"));
  }, []);

  async function savePolicy(event: FormEvent) {
    event.preventDefault();
    if (!policy) return;
    setSaving(true);
    try {
      const updated = await api.updatePolicy({
        expected_version: policy.version,
        manager_limit: Number(managerLimit).toFixed(2),
        policy_review_limit: Number(reviewLimit).toFixed(2),
        tax_inclusive: taxInclusive,
      });
      setPolicy(updated);
      notify("审批政策已更新；新版本仅作用于之后提交的申请。");
    } catch (error) {
      notify(error instanceof Error ? error.message : "无法保存审批政策。");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="settings-page">
      <SectionHeading eyebrow="POLICY & MAPPINGS" title="演示系统设置" description="政策按版本生效；已提交的申请保留原有规则与金额快照。" />
      <div className="settings-grid">
        <section className="surface-card settings-policy-card">
          <div className="card-heading"><div><div className="eyebrow">APPROVAL POLICY</div><h3>审批阈值</h3></div><span className="policy-version">政策 V{policy?.version ?? "—"}</span></div>
          {policy ? (
            <form className="policy-form" onSubmit={(event) => void savePolicy(event)}>
              <label className="field">
                <span>部门负责人审批上限 <i>CNY · 含税</i></span>
                <div className="input-shell money-input"><span>¥</span><input type="number" min="0" step="0.01" value={managerLimit} onChange={(event) => setManagerLimit(event.target.value)} required /><small>CNY</small></div>
                <small className="field-hint">超过此金额必须由另一名财务人员复核。</small>
              </label>
              <label className="field">
                <span>自动审批政策上限 <i>CNY · 含税</i></span>
                <div className="input-shell money-input"><span>¥</span><input type="number" min="0.01" step="0.01" value={reviewLimit} onChange={(event) => setReviewLimit(event.target.value)} required /><small>CNY</small></div>
                <small className="field-hint">超过此金额转入人工政策复核，不会自动写入 ERP。</small>
              </label>
              <label className="toggle-row">
                <span><strong>审批口径按含税总额</strong><small>税额也计入政策阈值判断</small></span>
                <button className={"toggle " + (taxInclusive ? "on" : "")} type="button" aria-label="切换含税审批口径" onClick={() => setTaxInclusive((value) => !value)}><span /></button>
              </label>
              <div className="policy-callout"><ShieldCheck size={16} /><span>每次修改都会递增政策版本；已提交的申请不会被静默重算。</span></div>
              <button className="button button-primary save-policy" disabled={saving} type="submit">{saving ? <span className="button-spinner" /> : <>保存政策版本 <ArrowRight size={15} /></>}</button>
            </form>
          ) : <div className="skeleton-panel" />}
        </section>

        <section className="surface-card settings-mapping-card">
          <div className="card-heading"><div><div className="eyebrow">ODOO MASTER DATA</div><h3>已验证映射</h3></div><span className="mapping-live"><span />已连接</span></div>
          <p className="mapping-intro">供应商、商品与税率源自真实 Odoo 19 主数据，并以映射版本锁定到草稿。</p>
          <div className="mapping-subhead"><Truck size={15} />供应商 <span>{mappings?.suppliers.length ?? 0}</span></div>
          <div className="mapping-list">
            {mappings?.suppliers.map((supplier) => (
              <div className="mapping-row" key={String(supplier.reference)}>
                <span className="mapping-icon vendor"><Truck size={15} /></span>
                <span><strong>{String(supplier.name)}</strong><small>{String(supplier.reference)}</small></span>
                <CheckCircle2 size={16} className="mapping-check" />
              </div>
            ))}
          </div>
          <div className="mapping-subhead product-subhead"><PackageCheck size={15} />可采购商品 <span>{mappings?.products.length ?? 0}</span></div>
          <div className="mapping-list">
            {mappings?.products.map((product) => (
              <div className="mapping-row" key={String(product.sku)}>
                <span className="mapping-icon product"><FileCheck2 size={15} /></span>
                <span><strong>{String(product.name)}</strong><small>{String(product.sku)} · 税率 {String(product.tax_rate)}%</small></span>
                <CheckCircle2 size={16} className="mapping-check" />
              </div>
            ))}
          </div>
          <div className="mapping-note"><HelpCircle size={15} /><span>Odoo 主数据为权威来源；修改映射需重新验证并递增版本。</span></div>
        </section>
      </div>
    </div>
  );
}
