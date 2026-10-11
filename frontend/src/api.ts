export type Role = "requester" | "manager" | "finance" | "procurement" | "admin";
export type Decision = "approve" | "reject";

export interface Identity {
  email: string;
  name: string;
  role: Role;
  department_code: string | null;
  department_name: string | null;
}

export interface CurrentUser {
  user_id: string;
  email: string;
  name: string;
  role: Role;
  department_code: string | null;
  department_name: string | null;
}

export interface Supplier {
  reference: string;
  name: string;
}

export interface CatalogProduct {
  sku: string;
  name: string;
  unit_price: string;
  tax_rate: string;
  currency_code: string;
}

export interface Catalog {
  currency_code: string;
  suppliers: Supplier[];
  products: CatalogProduct[];
}

export interface LineItem {
  id: string;
  line_number: number;
  sku: string;
  product_name: string;
  quantity: string;
  unit_price: string;
  tax_rate: string;
  amount_untaxed: string;
  amount_tax: string;
  amount_total: string;
  currency_code: string;
}

export interface ApprovalRecord {
  stage: string;
  actor: string;
  actor_id: string;
  decision: string;
  reason: string | null;
  request_version: number;
  decided_at: string;
}

export interface ERPView {
  state: string;
  remote_order_name: string | null;
  attempts: number;
  observation: {
    disposition?: string;
    observed_at?: string;
    differences?: Record<string, { expected?: unknown; actual?: unknown }>;
    [key: string]: unknown;
  } | null;
  observed_at: string | null;
  intent_id?: string;
  external_intent_id?: string;
  remote_order_id?: number | null;
  last_error?: string | null;
}

export interface PolicyReviewRecord {
  decision: string;
  actor: string;
  reason: string;
  policy_version: number;
  decided_at: string;
}

export interface AuditRecord {
  action: string;
  actor_user_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  metadata: Record<string, unknown> | null;
  occurred_at: string;
}

export interface ProcurementRecord {
  id: string;
  request_number: string;
  department: { id: string | null; code: string | null; name: string | null };
  requester: { id: string; email: string; name: string };
  supplier: { id: string; reference: string; name: string; odoo_partner_id?: number };
  reason: string;
  currency_code: string;
  status: string;
  version: number;
  policy_version: number | null;
  amount_untaxed: string;
  amount_tax: string;
  amount_total: string;
  lines: LineItem[];
  approvals: ApprovalRecord[];
  policy_review: PolicyReviewRecord | null;
  erp: ERPView | null;
  audit_events: AuditRecord[];
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  allowed_actions: string[];
}

export interface Overview {
  total: number;
  by_status: Record<string, number>;
  attention: ProcurementRecord[];
}

export interface Policy {
  version: number;
  manager_limit: string;
  policy_review_limit: string;
  tax_inclusive: boolean;
  currency_code: string;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {
    ...init,
    headers,
    credentials: "same-origin",
  });
  const data = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const message =
      typeof data?.detail === "string"
        ? data.detail
        : "请求失败（HTTP " + response.status + "）";
    throw new ApiError(response.status, message);
  }
  return data as T;
}

export const api = {
  me: () => request<CurrentUser>("/api/me"),
  identities: () => request<Identity[]>("/api/demo/identities"),
  login: async (identity: Identity) => {
    await request("/api/demo/sessions", {
      method: "POST",
      body: JSON.stringify({
        role: identity.role,
        email: identity.email,
        department_code: identity.department_code,
      }),
    });
    return request<CurrentUser>("/api/me");
  },
  logout: () => request<{ signed_out: boolean }>("/api/demo/sessions", { method: "DELETE" }),
  overview: () => request<Overview>("/api/overview"),
  procurements: () => request<ProcurementRecord[]>("/api/procurements"),
  procurement: (id: string) => request<ProcurementRecord>("/api/procurements/" + id),
  catalog: () => request<Catalog>("/api/catalog"),
  createDraft: (body: unknown, idempotencyKey: string) =>
    request<ProcurementRecord>("/api/procurements", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(body),
    }),
  updateDraft: (id: string, body: unknown) =>
    request<ProcurementRecord>("/api/procurements/" + id, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  submit: (id: string, version: number) =>
    request<ProcurementRecord>("/api/procurements/" + id + "/submit", {
      method: "POST",
      body: JSON.stringify({ expected_version: version }),
    }),
  cancel: (id: string, version: number) =>
    request<ProcurementRecord>("/api/procurements/" + id + "/cancel", {
      method: "POST",
      body: JSON.stringify({ expected_version: version }),
    }),
  decide: (id: string, version: number, decision: Decision, reason: string) =>
    request<ProcurementRecord>("/api/procurements/" + id + "/decision", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ expected_version: version, decision, reason: reason || null }),
    }),
  policyReview: (id: string, version: number, decision: Decision, reason: string) =>
    request<ProcurementRecord>("/api/procurements/" + id + "/policy-review", {
      method: "POST",
      body: JSON.stringify({ expected_version: version, decision, reason }),
    }),
  reconcile: (id: string) =>
    request<ProcurementRecord>("/api/procurements/" + id + "/reconcile", { method: "POST" }),
  retry: (id: string) =>
    request<ProcurementRecord>("/api/procurements/" + id + "/retry", { method: "POST" }),
  close: (id: string, version: number) =>
    request<ProcurementRecord>("/api/procurements/" + id + "/close", {
      method: "POST",
      body: JSON.stringify({ expected_version: version }),
    }),
  policy: () => request<Policy>("/api/admin/policy"),
  updatePolicy: (body: unknown) =>
    request<Policy>("/api/admin/policy", { method: "PUT", body: JSON.stringify(body) }),
  mappings: () =>
    request<{
      suppliers: Array<Record<string, unknown>>;
      products: Array<Record<string, unknown>>;
    }>("/api/admin/mappings"),
};
