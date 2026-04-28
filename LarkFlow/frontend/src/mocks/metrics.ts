import type { MetricsResponse, PipelineState } from "../types/api";

export function buildMetricsResponse(pipelines: PipelineState[]): MetricsResponse {
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
