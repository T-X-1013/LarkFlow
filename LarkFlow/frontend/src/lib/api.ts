import type {
  ArtifactResponse,
  MetricsResponse,
  PipelineCreateResponse,
  Stage,
  PipelineState,
  CheckpointName,
} from "../types/api";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function shouldUseMsw() {
  const explicitFlag = (import.meta.env.VITE_USE_MSW as string | undefined)?.trim();
  const baseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();

  if (explicitFlag === "1") {
    return true;
  }
  if (explicitFlag === "0") {
    return false;
  }
  return Boolean(import.meta.env.DEV && !baseUrl);
}

function buildUrl(path: string) {
  const baseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();
  if (!baseUrl) {
    return path;
  }
  return `${baseUrl.replace(/\/+$/, "")}${path}`;
}

async function jsonRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(buildUrl(path), {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = await response.json();
    } catch {
      detail = await response.text().catch(() => null);
    }
    const message =
      typeof detail === "object" && detail !== null && "detail" in detail
        ? String((detail as { detail: unknown }).detail)
        : `Request failed: ${response.status}`;
    throw new ApiError(message, response.status, detail);
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    const body = await response.text().catch(() => "");
    const looksLikeHtml = body.trim().startsWith("<!doctype") || body.trim().startsWith("<html");
    const message = looksLikeHtml
      ? "API 返回了 HTML，不是 JSON。开发态请使用 MSW mock，或设置 VITE_API_BASE_URL 指向后端。"
      : `Expected JSON response but received ${contentType || "unknown content type"}`;
    throw new ApiError(message, response.status, body);
  }

  try {
    return (await response.json()) as T;
  } catch (error) {
    throw new ApiError(
      error instanceof Error ? error.message : "Invalid JSON response",
      response.status,
      null,
    );
  }
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
