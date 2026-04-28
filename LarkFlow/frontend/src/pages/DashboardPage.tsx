import { useEffect, useMemo, useState } from "react";

import { listMetrics } from "../lib/api";
import { getPipelineSnapshot, subscribePipelines } from "../mocks/store";
import type { MetricsResponse } from "../types/api";

export function DashboardPage() {
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [pipelines, setPipelines] = useState(() => getPipelineSnapshot());

  useEffect(() => {
    listMetrics().then(setMetrics).catch(() => setMetrics(null));
  }, []);

  useEffect(() => {
    return subscribePipelines(setPipelines);
  }, []);

  const summary = useMemo(() => {
    const pipelines = metrics?.pipelines ?? [];
    const total = pipelines.length;
    const totalDuration = pipelines.reduce((sum, item) => sum + item.duration_ms, 0);
    const totalTokens = pipelines.reduce(
      (sum, item) => sum + item.tokens.input + item.tokens.output,
      0,
    );
    return {
      total,
      avgDuration: total ? Math.round(totalDuration / total) : 0,
      totalTokens,
      successful: pipelines.filter((item) => item.status === "succeeded").length,
    };
  }, [metrics]);

  const bars = (metrics?.pipelines ?? []).map((item) => ({
    label: item.pipeline_id,
    value: item.duration_ms,
  }));
  const maxBar = Math.max(...bars.map((item) => item.value), 1);
  const providerBreakdown = useMemo(() => {
    const counts = new Map<string, number>();
    for (const pipeline of pipelines) {
      const provider = pipeline.provider ?? "unknown";
      counts.set(provider, (counts.get(provider) ?? 0) + 1);
    }
    return Array.from(counts.entries()).map(([provider, count]) => ({ provider, count }));
  }, [pipelines]);
  const statusBreakdown = useMemo(() => {
    const counts = new Map<string, number>();
    for (const pipeline of metrics?.pipelines ?? []) {
      counts.set(pipeline.status, (counts.get(pipeline.status) ?? 0) + 1);
    }
    return Array.from(counts.entries()).map(([status, count]) => ({ status, count }));
  }, [metrics]);

  return (
    <section className="page">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Observability View</p>
          <h2>仪表盘</h2>
        </div>
        <span className="badge badge--running">mock metrics</span>
      </div>

      <div className="metric-grid">
        <div className="stat-card">
          <p className="eyebrow">Pipelines</p>
          <div className="stat-card__value">{summary.total}</div>
        </div>
        <div className="stat-card">
          <p className="eyebrow">Avg Duration</p>
          <div className="stat-card__value">{summary.avgDuration}ms</div>
        </div>
        <div className="stat-card">
          <p className="eyebrow">Token Volume</p>
          <div className="stat-card__value">{summary.totalTokens}</div>
        </div>
        <div className="stat-card">
          <p className="eyebrow">Succeeded</p>
          <div className="stat-card__value">{summary.successful}</div>
        </div>
      </div>

      <div className="details-grid">
        <div className="panel chart">
          <div>
            <p className="eyebrow">Duration Ranking</p>
            <h3>按耗时排序</h3>
          </div>
          <div className="bar-list">
            {bars.map((bar) => (
              <div key={bar.label} className="bar">
                <div className="row">
                  <span>{bar.label}</span>
                  <span>{bar.value}ms</span>
                </div>
                <div className="bar__track">
                  <div
                    className="bar__fill"
                    style={{ width: `${Math.max(12, (bar.value / maxBar) * 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="panel">
          <p className="eyebrow">Scope</p>
          <h3>本页当前承载的指标语义</h3>
          <table>
            <tbody>
              <tr>
                <th>现阶段</th>
                <td>消费 `/metrics/pipelines` mock 返回</td>
              </tr>
              <tr>
                <th>后续接线</th>
                <td>替换成后端真实聚合，不改页面结构</td>
              </tr>
              <tr>
                <th>重点字段</th>
                <td>`duration_ms / tokens.input / tokens.output`</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="details-grid">
        <div className="panel">
          <p className="eyebrow">Provider Mix</p>
          <h3>Provider 分布</h3>
          <div className="timeline">
            {providerBreakdown.map((item) => (
              <div key={item.provider} className="timeline__item">
                <div className="row">
                  <strong>{item.provider}</strong>
                  <span className="badge badge--pending">{item.count}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="panel">
          <p className="eyebrow">Status Mix</p>
          <h3>状态分布</h3>
          <div className="timeline">
            {statusBreakdown.map((item) => (
              <div key={item.status} className="timeline__item">
                <div className="row">
                  <strong>{item.status}</strong>
                  <span className="badge badge--running">{item.count}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
