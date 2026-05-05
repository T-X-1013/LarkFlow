import type {
  ArtifactResponse,
  DemandListItem,
  MetricsResponse,
  PipelineCreateResponse,
  Stage,
  PipelineState,
  CheckpointName,
  VisualEditCommitPlan,
  VisualEditCommitResult,
  VisualEditDeliveryCheck,
  VisualEditPreviewRequest,
  VisualEditSession,
} from "../types/api";

async function jsonRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    let detail = "";
    try {
      const payload = (await response.json()) as { detail?: string };
      detail = payload.detail ? ` - ${payload.detail}` : "";
    } catch {
      detail = "";
    }
    throw new Error(`Request failed: ${response.status}${detail}`);
  }

  return (await response.json()) as T;
}

export function createPipeline(requirement: string, template = "default") {
  return jsonRequest<PipelineCreateResponse>("/pipelines", {
    method: "POST",
    body: JSON.stringify({ requirement, template }),
  });
}

export async function createAndStartPipeline(requirement: string, template = "default") {
  const created = await createPipeline(requirement, template);
  const state = await startPipeline(created.id);
  return { created, state };
}

export function createVisualEditPreview(body: VisualEditPreviewRequest) {
  return jsonRequest<VisualEditSession>("/visual-edits/preview", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getVisualEditSession(id: string) {
  return jsonRequest<VisualEditSession>(`/visual-edits/${id}`);
}

export function confirmVisualEdit(id: string) {
  return jsonRequest<VisualEditSession>(`/visual-edits/${id}/confirm`, {
    method: "POST",
  });
}

export function cancelVisualEdit(id: string) {
  return jsonRequest<VisualEditSession>(`/visual-edits/${id}/cancel`, {
    method: "POST",
  });
}

export function getVisualEditDeliveryCheck(id: string) {
  return jsonRequest<VisualEditDeliveryCheck>(`/visual-edits/${id}/delivery-check`);
}

export function prepareVisualEditCommit(id: string) {
  return jsonRequest<VisualEditCommitPlan>(`/visual-edits/${id}/prepare-commit`);
}

export function commitVisualEdit(id: string, force = false) {
  return jsonRequest<VisualEditCommitResult>(`/visual-edits/${id}/commit`, {
    method: "POST",
    body: JSON.stringify({ force }),
  });
}

export function listMetrics() {
  return jsonRequest<MetricsResponse>("/metrics/pipelines");
}

export function listPipelines() {
  return jsonRequest<PipelineState[]>("/pipelines");
}

export function listDemands() {
  return jsonRequest<DemandListItem[]>("/demands");
}

export function getPipeline(id: string) {
  return jsonRequest<PipelineState>(`/pipelines/${id}`);
}

export function getStageArtifact(id: string, stage: Stage) {
  return jsonRequest<ArtifactResponse>(`/pipelines/${id}/stages/${stage}/artifact`);
}

export function updateProvider(id: string, provider: string) {
  return jsonRequest<PipelineState>(`/pipelines/${id}/provider`, {
    method: "PUT",
    body: JSON.stringify({ provider }),
  });
}

export function approveCheckpoint(id: string, checkpoint: CheckpointName) {
  return jsonRequest<PipelineState>(`/pipelines/${id}/checkpoints/${checkpoint}/approve`, {
    method: "POST",
  });
}

export function rejectCheckpoint(id: string, checkpoint: CheckpointName, reason: string) {
  return jsonRequest<PipelineState>(`/pipelines/${id}/checkpoints/${checkpoint}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function startPipeline(id: string) {
  return jsonRequest<PipelineState>(`/pipelines/${id}/start`, { method: "POST" });
}

export function pausePipeline(id: string) {
  return jsonRequest<PipelineState>(`/pipelines/${id}/pause`, { method: "POST" });
}

export function resumePipeline(id: string) {
  return jsonRequest<PipelineState>(`/pipelines/${id}/resume`, { method: "POST" });
}

export function stopPipeline(id: string) {
  return jsonRequest<PipelineState>(`/pipelines/${id}/stop`, { method: "POST" });
}
