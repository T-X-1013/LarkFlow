export type Stage = "design" | "coding" | "test" | "review";
export type StageStatus = "success" | "failed" | "rejected" | "pending";
export type PipelineStatus =
  | "pending"
  | "running"
  | "paused"
  | "waiting_approval"
  | "stopped"
  | "failed"
  | "rejected"
  | "succeeded";
export type CheckpointName = "design" | "deploy";

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
}

export interface PipelineCreateResponse {
  id: string;
}

export interface MetricsItem {
  pipeline_id: string;
  status: PipelineStatus;
  duration_ms: number;
  tokens: TokenUsage;
  stages: Partial<Record<Stage, StageResult>>;
}

export interface MetricsResponse {
  pipelines: MetricsItem[];
}

export interface ArtifactResponse {
  stage: Stage;
  artifact_path: string;
  content?: string | null;
}
