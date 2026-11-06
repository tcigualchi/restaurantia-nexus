// Mirrors the API DTOs (apps/api/src/nexus/application/views.py).
export type Role = "viewer" | "operator" | "manager" | "owner";

export interface Restaurant {
  id: string;
  name: string;
  template_key: string;
  timezone: string;
  kitchen_lines: number;
  kitchen_lines_available: number;
  prep_sla_minutes: number;
  is_demo: boolean;
  role: Role;
  permissions: string[];
}

export interface Simulation {
  id: string;
  scenario_key: string;
  scenario_name: string;
  seed: number;
  status: "running" | "paused" | "completed" | "cancelled";
  pause_reason: string | null;
  current_tick: number;
  total_ticks: number;
  tick_interval_ms: number;
  auto_pause_on_approval: boolean;
  sim_start: string;
  business_time: string;
  created_at: string;
}

export interface Kpis {
  orders_last_60: number;
  revenue_last_60_cents: number;
  queue_length: number;
  oldest_open_minutes: number | null;
  avg_prep_minutes: number | null;
  p90_prep_minutes: number | null;
  sla_minutes: number;
  sla_breach_rate: number | null;
  lost_orders_total: number;
  lost_revenue_total_cents: number;
  orders_total: number;
  revenue_total_cents: number;
  kitchen_lines: number;
  kitchen_lines_available: number;
  open_incidents: number;
  pending_approvals: number;
  ingredients_at_risk: number;
}

export interface IngredientRisk {
  ingredient_key: string;
  name: string;
  unit: string;
  stock: number;
  safety_stock: number;
  consumption_per_hour: number;
  eta_minutes: number | null;
  eta_to_safety_minutes: number | null;
  risk: "ok" | "watch" | "high" | "critical" | "out";
}

export interface AgentRunBrief {
  id: string;
  status: "queued" | "running" | "awaiting_approval" | "completed" | "failed";
  mode: string | null;
  provider: string;
  model: string | null;
  trigger: string;
  incident_title: string | null;
  summary: string | null;
  as_of: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  estimated_cost_usd: number | null;
  steps: number;
  approvals: number;
  error: string | null;
}

export interface Overview {
  restaurant: Restaurant;
  business_time: string;
  clock_mode: "simulation" | "live";
  data_label: string;
  simulation: Simulation | null;
  kpis: Kpis;
  ingredients_at_risk: IngredientRisk[];
  latest_agent_run: AgentRunBrief | null;
}

export interface TimeseriesPoint {
  t: string;
  orders: number;
  rejected: number;
  avg_prep_minutes: number | null;
  queue_length: number;
  stock: Record<string, number>;
}

export interface Timeseries {
  bucket_minutes: number;
  start: string;
  end: string;
  ingredients: Record<string, string>;
  units?: Record<string, string>;
  points: TimeseriesPoint[];
}

export interface OrderView {
  id: string;
  order_ref: string;
  channel: string;
  status: "received" | "ready" | "rejected" | "cancelled";
  created_at: string;
  ready_at: string | null;
  prep_minutes: number | null;
  total_cents: number;
  reject_reason: string | null;
  customer_note: string | null;
  note_flags: string[];
  items: { item_key: string; name: string; qty: number; unit_price_cents: number }[];
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  total: number | null;
}

export interface IngredientView {
  id: string;
  key: string;
  name: string;
  unit: string;
  stock: number;
  safety_stock: number;
  consumption_per_hour: number;
  eta_minutes: number | null;
  risk: IngredientRisk["risk"];
  pack_size: number;
  lead_time_minutes: number;
  unit_cost_cents: number;
  open_po_qty: number;
  used_by: string[];
}

export interface MenuItemView {
  id: string;
  key: string;
  name: string;
  category: string;
  course: string;
  price_cents: number;
  is_available: boolean;
  unavailable_reason: string | null;
  recipe: Record<string, number>;
}

export interface PurchaseOrderView {
  id: string;
  ingredient_key: string;
  ingredient_name: string;
  quantity: number;
  unit: string;
  status: "ordered" | "received" | "cancelled";
  estimated_cost_cents: number;
  expected_at: string;
  received_at: string | null;
  approval_id: string | null;
  created_at: string;
}

export interface InventoryView {
  business_time: string;
  ingredients: IngredientView[];
  menu_items: MenuItemView[];
  purchase_orders: PurchaseOrderView[];
}

export interface EventView {
  id: number;
  type: string;
  source: string;
  status: "pending" | "processed" | "rejected" | "dead_letter";
  tick: number | null;
  occurred_at: string;
  received_at: string;
  attempts: number;
  outcome: string | null;
  last_error: string | null;
  payload: Record<string, unknown>;
}

export interface Signal {
  kind: string;
  severity: string;
  subject: string;
  message: string;
  metrics: Record<string, unknown>;
}

export interface IncidentView {
  id: string;
  title: string;
  severity: string;
  status: string;
  detected_at: string;
  tick: number | null;
  signals: Signal[];
}

export interface StepView {
  id: string;
  seq: number;
  agent: string;
  kind: string;
  title: string;
  tool_name: string | null;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  status: string;
  latency_ms: number | null;
  flags: string[];
  created_at: string;
}

export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired" | "executed" | "failed" | "cancelled";

export interface ApprovalView {
  id: string;
  run_id: string | null;
  incident_id: string | null;
  action_type: "create_purchase_order" | "pause_menu_item";
  title: string;
  rationale: string;
  expected_impact: string;
  risk_level: string;
  payload: Record<string, unknown>;
  evidence: string[];
  required_role: Role;
  status: ApprovalStatus;
  version: number;
  requested_at: string;
  business_time: string | null;
  expires_at: string;
  decided_by_label: string | null;
  decided_at: string | null;
  decision_reason: string | null;
  executed_at: string | null;
  execution_result: { message?: string; error?: string; [k: string]: unknown } | null;
  can_decide: boolean;
}

export interface Candidate {
  candidate_id: string;
  action_type: string;
  title: string;
  rationale: string;
  expected_impact: string;
  risk_level: string;
  evidence: string[];
}

export interface PlanView {
  candidates: Candidate[];
  recommendations: { title: string; detail: string; category: string; evidence: string[] }[];
  capacity: {
    lines_available: number;
    estimated_service_minutes: number;
    capacity_orders_per_hour: number;
    projected_orders_per_hour: number;
    projected_utilization: number;
    queue_length: number;
    risk: string;
  } | null;
  assumptions: string[];
  priority: string[];
  approvals: string[];
}

export interface AgentOutcomeView {
  mode: string;
  summary: string;
  facts: { label: string; value: string; evidence: string }[];
  flags: string[];
  error: string | null;
  evidence: Record<string, string>;
}

export interface AgentRunDetail extends AgentRunBrief {
  plan: PlanView | null;
  outcomes: Record<string, AgentOutcomeView> | null;
  incident: IncidentView | null;
  step_list: StepView[];
  approval_list: ApprovalView[];
}

export interface AuditView {
  id: number;
  actor_type: "user" | "agent" | "system";
  actor_label: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  details: Record<string, unknown>;
  business_time: string | null;
  created_at: string;
}

export interface ScenarioView {
  key: string;
  name: string;
  description: string;
  total_ticks: number;
  featured: boolean;
  tags: string[];
  auto_pause_on_approval: boolean;
}

export interface Interval {
  expected: number;
  p10: number;
  p90: number;
}

export interface ForecastView {
  forecast: {
    as_of: string;
    horizon_minutes: number;
    model: string;
    orders: Interval;
    orders_adjusted: Interval;
    items: { item_key: string; name: string; baseline: Interval; adjusted: Interval }[];
    ingredients: { ingredient_key: string; name: string; unit: string; baseline: Interval; adjusted: Interval }[];
    nowcast: { window_minutes: number; observed_orders: number; expected_orders: number; raw_ratio: number | null; applied_ratio: number; note: string };
    backtest: {
      method: string;
      granularity: string;
      validation_window: [string, string];
      test_window: [string, string];
      validation: { model: string; mae: number; wape: number }[];
      test: { model: string; mae: number; wape: number }[];
      selected_model: string;
      dispersion: number;
      interval_level: number;
      interval_coverage_test: number;
      test_hours: number;
    };
    disclaimer: string;
  };
  history: { hour: string; orders: number; expected: number }[];
  data_label: string;
}

export interface SystemInfo {
  name: string;
  version: string;
  environment: string;
  agents: { mode: "llm" | "deterministic"; provider: string; model: string | null; label: string; cost_tracking: boolean };
  demo: { enabled: boolean; session_ttl_minutes: number };
  data_notice: string;
}

export interface Me {
  id: string;
  display_name: string;
  is_demo: boolean;
  demo_expires_at: string | null;
  restaurants: Restaurant[];
}

export interface LiveEvent {
  id: number;
  type: string;
  status: string;
  tick: number | null;
  occurred_at: string;
  order_ref: string | null;
  outcome: string | null;
}

export interface LiveAudit {
  id: number;
  action: string;
  actor: string;
  actor_type: string;
  target_type: string | null;
  target_id: string | null;
  title: string | null;
  created_at: string;
}

export interface LiveStatus {
  simulation: Simulation | null;
  business_time: string;
  agents_running: number;
  pending_approvals: number;
}

/** One poll of GET /restaurants/{id}/live: everything after `cursor`, plus the current status. */
export interface LiveSnapshot {
  events: LiveEvent[];
  audits: LiveAudit[];
  status: LiveStatus;
  cursor: string;
}
