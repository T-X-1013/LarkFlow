import type { MetricsResponse } from "../../types/api";

export const metricsFixture: MetricsResponse = {
  pipelines: [
    {
      pipeline_id: "DEMAND-a1f2c3d4",
      status: "running",
      duration_ms: 428000,
      tokens: { input: 2134, output: 1493 },
      stages: {},
      by_role: [],
    },
    {
      pipeline_id: "DEMAND-b5e6f7g8",
      status: "waiting_approval",
      duration_ms: 696000,
      tokens: { input: 2873, output: 1659 },
      stages: {},
      by_role: [],
    },
    {
      pipeline_id: "DEMAND-h9i0j1k2",
      status: "paused",
      duration_ms: 436000,
      tokens: { input: 1920, output: 1182 },
      stages: {},
      by_role: [],
    },
  ],
};
