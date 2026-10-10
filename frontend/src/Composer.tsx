import { Building2, Check, FilePlus2, Plus, ShieldCheck, Truck, X } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import type { Catalog, CurrentUser, ProcurementRecord } from "./api";
import { api } from "./api";
import { formatMoney } from "./ui";

interface DraftLine {
  sku: string;
  quantity: string;
  unit_price: string;
}

export default function Composer({
  me,
  catalog,
  initial,
  onCancel,
  onSaved,
  notify,
}: {
  me: CurrentUser;
  catalog: Catalog;
  initial: ProcurementRecord | null;
  onCancel: () => void;
  onSaved: (record: ProcurementRecord) => void;
  notify: (message: string) => void;
}) {
  const isEditing = Boolean(initial);
  const [supplierRef, setSupplierRef] = useState(initial?.supplier.reference ?? catalog.suppliers[0]?.reference ?? "");
  const [reason, setReason] = useState(initial?.reason ?? "");
  const [lines, setLines] = useState<DraftLine[]>(() => initial
    ? initial.lines.map((line) => ({ sku: line.sku, quantity: line.quantity, unit_price: line.unit_price }))
    : [{ sku: catalog.products[0]?.sku ?? "", quantity: "1", unit_price: catalog.products[0]?.unit_price ?? "0.00" }]);
  const [saving, setSaving] = useState(false);

  const calculation = useMemo(() => {
    const rows = lines.map((line) => {
      const product = catalog.products.find((item) => item.sku === line.sku);
      const quantity = Math.max(0, Number(line.quantity) || 0);
      const price = Math.max(0, Number(line.unit_price) || 0);
      const net = roundMoney(quantity * price);
      const tax = roundMoney(net * Number(product?.tax_rate ?? 0) / 100);
      return { net, tax, total: net + tax };
    });
    return rows.reduce(
      (sum, item) => ({ net: sum.net + item.net, tax: sum.tax + item.tax, total: sum.total + item.total }),
      { net: 0, tax: 0, total: 0 },
    );
  }, [lines, catalog.products]);

  function updateLine(index: number, patch: Partial<DraftLine>) {
    setLines((current) => current.map((line, lineIndex) => {
      if (lineIndex !== index) return line;
      const next = { ...line, ...patch };
      if (patch.sku) {
        const product = catalog.products.find((item) => item.sku === patch.sku);
        if (product) next.unit_price = product.unit_price;
      }
      return next;
    }));
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      const body = {
        department_code: me.department_code ?? initial?.department.code ?? "",
        supplier_ref: supplierRef,
        reason: reason.trim(),
        currency_code: "CNY",
        lines: lines.map((line) => ({
          sku: line.sku,
          quantity: Number(line.quantity).toFixed(2),
          unit_price: Number(line.unit_price).toFixed(2),
        })),
      };
      const result = initial
        ? await api.updateDraft(initial.id, { ...body, expected_version: initial.version })
        : await api.createDraft(body, crypto.randomUUID());
      onSaved(result);
    } catch (error) {
      notify(error instanceof Error ? error.message : "无法保存采购申请。");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-scrim" onMouseDown={(event) => event.target === event.currentTarget && onCancel()}>
      <section className="composer-modal" role="dialog" aria-modal="true" aria-labelledby="composer-title">
        <header className="composer-header">
          <div className="composer-title-wrap">
            <span className="composer-icon"><FilePlus2 size={19} /></span>
            <div><div className="eyebrow">{isEditing ? "EDIT DRAFT" : "NEW PURCHASE REQUEST"}</div><h2 id="composer-title">{isEditing ? "编辑采购草稿" : "新建采购申请"}</h2></div>
          </div>
          <button className="icon-button" aria-label="关闭" onClick={onCancel} type="button"><X size={18} /></button>
        </header>
        <form onSubmit={(event) => void save(event)}>
          <div className="composer-scroll">
            <div className="form-section-title"><span>01</span><div><strong>申请信息</strong><small>说明采购目的与供应商</small></div></div>
            <div className="form-grid">
              <label className="field">
                <span>申请部门 <i>自动识别</i></span>
                <div className="input-shell readonly"><Building2 size={16} /><input value={me.department_name ?? initial?.department.name ?? "采购部门"} readOnly /></div>
              </label>
              <label className="field">
                <span>供应商 <b>*</b></span>
                <div className="input-shell select-shell"><Truck size={16} /><select value={supplierRef} onChange={(event) => setSupplierRef(event.target.value)} required aria-label="供应商">
                  {catalog.suppliers.map((supplier) => <option key={supplier.reference} value={supplier.reference}>{supplier.name}</option>)}
                </select><span className="select-caret">⌄</span></div>
              </label>
              <label className="field field-full">
                <span>采购事由 <b>*</b></span>
                <textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="说明采购背景、使用场景与预期用途…" minLength={5} maxLength={1000} required rows={3} />
                <small className="field-hint">提交后，事由将纳入审批快照并进入审计记录。</small>
              </label>
            </div>

            <div className="form-section-title line-section-title">
              <span>02</span><div><strong>采购明细</strong><small>从已验证的 Odoo 商品映射中选择</small></div>
              {!isEditing && lines.length < 3 && <button className="inline-add" onClick={() => setLines((current) => [...current, { sku: catalog.products[0]?.sku ?? "", quantity: "1", unit_price: catalog.products[0]?.unit_price ?? "0.00" }])} type="button"><Plus size={15} /> 添加一行</button>}
            </div>
            <div className="line-editor">
              <div className="line-editor-head"><span>商品 / 服务</span><span>数量</span><span>未税单价</span><span>税率</span><span>含税小计</span><span /></div>
              {lines.map((line, index) => {
                const product = catalog.products.find((item) => item.sku === line.sku);
                const subtotal = roundMoney((Number(line.quantity) || 0) * (Number(line.unit_price) || 0));
                const tax = roundMoney(subtotal * Number(product?.tax_rate ?? 0) / 100);
                return (
                  <div className="line-editor-row" key={index}>
                    <label className="product-select">
                      <select value={line.sku} onChange={(event) => updateLine(index, { sku: event.target.value })} aria-label={"商品明细 " + (index + 1)}>
                        {catalog.products.map((item) => <option value={item.sku} key={item.sku}>{item.name}</option>)}
                      </select>
                      <small>{line.sku}</small>
                    </label>
                    <label className="number-input"><input aria-label={"数量 " + (index + 1)} type="number" min="0.01" step="0.01" value={line.quantity} onChange={(event) => updateLine(index, { quantity: event.target.value })} required /></label>
                    <label className="number-input"><input aria-label={"未税单价 " + (index + 1)} type="number" min="0" step="0.01" value={line.unit_price} onChange={(event) => updateLine(index, { unit_price: event.target.value })} required /></label>
                    <span className="tax-rate">{product?.tax_rate ?? "0"}%</span>
                    <strong className="line-total">{formatMoney(subtotal + tax)}</strong>
                    <button className="line-remove" aria-label={"删除明细 " + (index + 1)} disabled={lines.length === 1 || isEditing} onClick={() => setLines((current) => current.filter((_, itemIndex) => itemIndex !== index))} type="button"><X size={15} /></button>
                  </div>
                );
              })}
            </div>
            <div className="form-summary">
              <div className="summary-note"><ShieldCheck size={15} /><span>预估金额仅供参考；审批金额由服务端 Decimal 规则计算。</span></div>
              <div className="summary-money">
                <div><span>未税金额</span><strong>{formatMoney(calculation.net)}</strong></div>
                <div><span>税额</span><strong>{formatMoney(calculation.tax)}</strong></div>
                <div className="summary-total"><span>含税总额</span><strong>{formatMoney(calculation.total)}</strong></div>
              </div>
            </div>
          </div>
          <footer className="composer-footer">
            <span className="required-note"><b>*</b> 必填字段</span>
            <div><button className="button button-ghost" onClick={onCancel} type="button">取消</button><button className="button button-primary" disabled={saving} type="submit">{saving ? <span className="button-spinner" /> : <><Check size={16} /> {isEditing ? "保存修改" : "保存草稿"}</>}</button></div>
          </footer>
        </form>
      </section>
    </div>
  );
}

function roundMoney(value: number) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}
