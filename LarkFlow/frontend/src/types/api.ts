export type Stage = "design" | "coding" | "test" | "review";
export type StageStatus = "success" | "failed" | "rejected" | "pending";
export type PipelineStatus =
  | "pending"
  | "running"
  | "paused"
  | "waiting_approval"
  | "waiting_clarification"
  | "stopped"
  | "failed"
  | "rejected"
  | "succeeded";
export type CheckpointName = "clarification" | "design" | "deploy";
export type VisualEditSessionStatus =
  | "draft"
  | "editing"
  | "preview_ready"
  | "confirming"
  | "confirmed"
  | "cancelling"
  | "cancelled"
  | "failed";

export interface TokenUsage {
  input: number;
  output: number;
}

export interface StageResult {
  stage: Stage;
  status: StageStatus;
  artifact_path: string | null;
  tokens: TokenUsage;
  duration_ms: number;
  errors: string[];
}

export interface Checkpoint {
  name: CheckpointName;
  status: StageStatus;
  requested_at: number | null;
  resolved_at: number | null;
  reason: string | null;
}

export interface ReviewSubRoleResult {
  role: string;
  status: string;
  artifact_path: string | null;
  tokens_input: number;
  tokens_output: number;
  duration_ms: number;
  error: string | null;
}

export interface ReviewMultiSnapshot {
  subroles: ReviewSubRoleResult[];
}

export type SkillRoutingTier = "baseline" | "conditional" | "route";
export type SkillRoutingSource = "" | "keyword" | "semantic" | "both";

export interface SkillRoutingReason {
  skill: string;
  tier: SkillRoutingTier | string;
  detail: string;
  score: number;
  source: SkillRoutingSource | string;
}

export interface SkillRoutingSnapshot {
  skills: string[];
  reasons: SkillRoutingReason[];
}

export interface SkillGateSnapshot {
  passed: boolean;
  missing_mandatory: string[];
  missing_optional: string[];
  read: string[];
  attempt: number;
}

export interface ApiSketchSnapshot {
  method: string;
  path: string;
  purpose: string;
}

export interface PersistenceSnapshot {
  needs_storage: boolean;
  needs_migration: boolean;
  tables: string[];
  notes: string;
}

export interface NfrSnapshot {
  auth: boolean;
  idempotent: boolean;
  rate_limit: boolean;
  transactional: boolean;
  high_concurrency: boolean;
}

export interface OpenQuestionSnapshot {
  text: string;
  blocking: boolean;
  candidates: string[];
}

export interface NormalizedDemandSnapshot {
  raw_demand: string;
  goal: string;
  out_of_scope: string[];
  entities: string[];
  apis: ApiSketchSnapshot[];
  persistence: PersistenceSnapshot;
  nfr: NfrSnapshot;
  domain_tags: string[];
  touches_python: boolean;
  open_questions: OpenQuestionSnapshot[];
  confidence: number;
  source: string;
}

export interface PipelineState {
  id: string;
  requirement: string;
  template: string;
  status: PipelineStatus;
  current_stage: Stage | null;
  stages: Partial<Record<Stage, StageResult>>;
  checkpoints: Partial<Record<CheckpointName, Checkpoint>>;
  provider: string | null;
  created_at: number;
  updated_at: number;
  review_multi?: ReviewMultiSnapshot | null;
  skill_routing?: SkillRoutingSnapshot | null;
  skill_gate?: SkillGateSnapshot | null;
  normalized_demand?: NormalizedDemandSnapshot | null;
}

export interface PipelineCreateResponse {
  id: string;
}

export interface RoleMetrics {
  role: string;
  tokens_input: number;
  tokens_output: number;
  duration_ms: number;
}

export interface MetricsItem {
  pipeline_id: string;
  status: PipelineStatus;
  duration_ms: number;
  tokens: TokenUsage;
  stages: Partial<Record<Stage, StageResult>>;
  by_role: RoleMetrics[];
}

export interface MetricsResponse {
  pipelines: MetricsItem[];
}

export interface ArtifactResponse {
  stage: Stage;
  artifact_path: string;
  content?: string | null;
}

export interface ElementRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

export interface VisualEditTarget {
  lark_src?: string | null;
  css_selector: string;
  tag: string;
  id: string;
  class_name: string;
  text: string;
  rect?: ElementRect | null;
}

export interface VisualEditPreviewRequest {
  requirement: string;
  page_url: string;
  page_path: string;
  target: VisualEditTarget;
  intent: string;
}

export interface VisualEditSession {
  id: string;
  requirement: string;
  page_url: string;
  page_path: string;
  intent: string;
  target: VisualEditTarget;
  status: VisualEditSessionStatus;
  preview_url: string | null;
  changed_files: string[];
  diff: string | null;
  diff_summary: string[];
  delivery_summary: string | null;
  confirmed_files: string[];
  error: string | null;
  created_at: number;
  updated_at: number;
}

export interface VisualEditDeliveryCheck {
  session_id: string;
  confirmed_files: string[];
  deliverable_files: string[];
  dirty_file_count: number;
  unrelated_dirty_count: number;
  safe_to_commit: boolean;
}

export interface VisualEditCommitPlan {
  session_id: string;
  files: string[];
  commit_message: string;
  summary: string;
  safe_to_commit: boolean;
  requires_manual_confirmation: boolean;
  warnings: string[];
}

export interface VisualEditCommitResult {
  session_id: string;
  commit_hash: string | null;
  commit_message: string;
  committed_files: string[];
  warnings: string[];
}
