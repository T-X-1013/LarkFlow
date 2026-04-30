import { getPipeline, listMetrics, shouldUseMsw } from "./api";
import type { MetricsItem, PipelineState } from "../types/api";

export interface PipelineCatalogItem {
  id: string;
  detailId: string;
  metric: MetricsItem;
  state: PipelineState | null;
}

export async function loadPipelineCatalog(): Promise<PipelineCatalogItem[]> {
  const metrics = await listMetrics();
  const details = await Promise.allSettled(
    metrics.pipelines.map((item) => getPipeline(item.pipeline_id)),
  );

  return metrics.pipelines.map((metric, index) => ({
    id: metric.pipeline_id,
    detailId: metric.pipeline_id,
    metric,
    state: details[index]?.status === "fulfilled" ? details[index].value : null,
  }));
}

export function getDataModeLabel() {
  return shouldUseMsw() ? "MSW mock" : "live API";
}
