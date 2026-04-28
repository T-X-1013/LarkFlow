import type {
  ArtifactResponse,
  MetricsResponse,
  PipelineCreateResponse,
  Stage,
  PipelineState,
  CheckpointName,
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
    throw new Error(`Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

export function createPipeline(requirement: string, template = "default") {
  return jsonRequest<PipelineCreateResponse>("/pipelines", {
    method: "POST",
    body: JSON.stringify({ requirement, template }),
  });
}

export function listMetrics() {
  return jsonRequest<MetricsResponse>("/metrics/pipelines");
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
