import { http, HttpResponse } from "msw";

import type { PipelineState } from "../types/api";
import {
  clonePipeline,
  findPipeline,
  getPipelineSnapshot,
  prependPipeline,
  replacePipeline,
} from "./store";

function buildMetricsResponse() {
  const pipelines = getPipelineSnapshot();
  return {
    pipelines: pipelines.map((pipeline) => {
      const stageList = Object.values(pipeline.stages).filter(Boolean);
      const duration_ms = stageList.reduce((sum, stage) => sum + (stage?.duration_ms ?? 0), 0);
      const input = stageList.reduce((sum, stage) => sum + (stage?.tokens.input ?? 0), 0);
      const output = stageList.reduce((sum, stage) => sum + (stage?.tokens.output ?? 0), 0);
      return {
        pipeline_id: pipeline.id,
        status: pipeline.status,
        duration_ms,
        tokens: { input, output },
        stages: pipeline.stages,
      };
    }),
  };
}

export const handlers = [
  http.post("/pipelines", async ({ request }) => {
    const body = (await request.json()) as { requirement: string; template?: string };
    const id = `DEMAND-${Math.random().toString(16).slice(2, 10)}`;
    const created: PipelineState = {
      id,
      requirement: body.requirement,
      template: body.template ?? "default",
      status: "pending",
      current_stage: "design",
      stages: {},
      checkpoints: {},
      provider: "anthropic",
      created_at: Math.floor(Date.now() / 1000),
      updated_at: Math.floor(Date.now() / 1000),
    };
    prependPipeline(created);
    return HttpResponse.json({ id });
  }),

  http.post("/pipelines/:pipelineId/start", ({ params }) => {
    const pipeline = clonePipeline(String(params.pipelineId));
    if (!pipeline) {
      return HttpResponse.json({ detail: "not found" }, { status: 404 });
    }
    pipeline.status = "running";
    pipeline.current_stage = pipeline.current_stage ?? "design";
    replacePipeline(pipeline);
    return HttpResponse.json(pipeline);
  }),

  http.post("/pipelines/:pipelineId/pause", ({ params }) => {
    const pipeline = clonePipeline(String(params.pipelineId));
    if (!pipeline) {
      return HttpResponse.json({ detail: "not found" }, { status: 404 });
    }
    pipeline.status = "paused";
    replacePipeline(pipeline);
    return HttpResponse.json(pipeline);
  }),

  http.post("/pipelines/:pipelineId/resume", ({ params }) => {
    const pipeline = clonePipeline(String(params.pipelineId));
    if (!pipeline) {
      return HttpResponse.json({ detail: "not found" }, { status: 404 });
    }
    pipeline.status = "running";
    replacePipeline(pipeline);
    return HttpResponse.json(pipeline);
  }),

  http.post("/pipelines/:pipelineId/stop", ({ params }) => {
    const pipeline = clonePipeline(String(params.pipelineId));
    if (!pipeline) {
      return HttpResponse.json({ detail: "not found" }, { status: 404 });
    }
    pipeline.status = "stopped";
    replacePipeline(pipeline);
    return HttpResponse.json(pipeline);
  }),

  http.get("/pipelines/:pipelineId", ({ params }) => {
    const pipeline = clonePipeline(String(params.pipelineId));
    if (!pipeline) {
      return HttpResponse.json({ detail: "not found" }, { status: 404 });
    }
    return HttpResponse.json(pipeline);
  }),

  http.get("/pipelines/:pipelineId/stages/:stage/artifact", ({ params }) => {
    const pipeline = findPipeline(String(params.pipelineId));
    if (!pipeline) {
      return HttpResponse.json({ detail: "not found" }, { status: 404 });
    }
    const stage = String(params.stage) as keyof PipelineState["stages"];
    const stageResult = pipeline.stages[stage];
    return HttpResponse.json({
      stage,
      artifact_path: stageResult?.artifact_path ?? "",
      content: stageResult?.artifact_path
        ? `# ${stage}\n\nArtifact preview for ${pipeline.id}`
        : null,
    });
  }),

  http.post("/pipelines/:pipelineId/checkpoints/:cp/approve", ({ params }) => {
    const pipeline = clonePipeline(String(params.pipelineId));
    if (!pipeline) {
      return HttpResponse.json({ detail: "not found" }, { status: 404 });
    }
    const checkpointName = String(params.cp) as "design" | "deploy";
    const checkpoint = pipeline.checkpoints[checkpointName];
    if (checkpoint) {
      checkpoint.status = "success";
      checkpoint.resolved_at = Math.floor(Date.now() / 1000);
    }
    pipeline.status = checkpointName === "deploy" ? "succeeded" : "running";
    replacePipeline(pipeline);
    return HttpResponse.json(pipeline);
  }),

  http.post("/pipelines/:pipelineId/checkpoints/:cp/reject", async ({ params, request }) => {
    const pipeline = clonePipeline(String(params.pipelineId));
    if (!pipeline) {
      return HttpResponse.json({ detail: "not found" }, { status: 404 });
    }
    const body = (await request.json()) as { reason: string };
    const checkpointName = String(params.cp) as "design" | "deploy";
    const checkpoint = pipeline.checkpoints[checkpointName];
    if (checkpoint) {
      checkpoint.status = "rejected";
      checkpoint.reason = body.reason;
      checkpoint.resolved_at = Math.floor(Date.now() / 1000);
    }
    pipeline.status = "rejected";
    replacePipeline(pipeline);
    return HttpResponse.json(pipeline);
  }),

  http.put("/pipelines/:pipelineId/provider", async ({ params, request }) => {
    const pipeline = clonePipeline(String(params.pipelineId));
    if (!pipeline) {
      return HttpResponse.json({ detail: "not found" }, { status: 404 });
    }
    const body = (await request.json()) as { provider: string };
    pipeline.provider = body.provider;
    replacePipeline(pipeline);
    return HttpResponse.json(pipeline);
  }),

  http.get("/metrics/pipelines", () => {
    return HttpResponse.json(buildMetricsResponse());
  }),

  http.get("/healthz", () => {
    return HttpResponse.json({ ok: true });
  }),
];
