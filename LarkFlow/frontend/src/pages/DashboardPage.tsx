import { useEffect, useMemo, useState } from "react";

import { listMetrics, listPipelines } from "../lib/api";
import type { MetricsResponse, PipelineState } from "../types/api";

export function DashboardPage() {
  const [pipelines, setPipelines] = useState<PipelineState[]>([]);
  const [metrics, setMetrics] = useState<MetricsResponse>({ pipelines: [] });

  useEffect(() => {
    let cancelled = false;
    async function loadDashboardData() {
      try {
        const [nextPipelines, nextMetrics] = await Promise.all([
          listPipelines(),
          listMetrics(),
        ]);
        if (cancelled) return;
        setPipelines(nextPipelines);
        setMetrics(nextMetrics);
      } catch {
        if (cancelled) return;
        setPipelines([]);
        setMetrics({ pipelines: [] });
      }
    }
    loadDashboardData();
    const timer = window.setInterval(loadDashboardData, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const summary = useMemo(() => {
    const metricPipelines = metrics.pipelines;
    const total = metricPipelines.length;
    const totalDuration = metricPipelines.reduce((sum, item) => sum + item.duration_ms, 0);
    const totalTokens = metricPipelines.reduce(
      (sum, item) => sum + item.tokens.input + item.tokens.output,
      0,
    );
    return {
      total,
      avgDuration: total ? Math.round(totalDuration / total) : 0,
      totalTokens,
      successful: metricPipelines.filter((item) => item.status === "succeeded").length,
    };
  }, [metrics]);

  const bars = metrics.pipelines.map((item) => ({
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
    for (const pipeline of metrics.pipelines) {
      counts.set(pipeline.status, (counts.get(pipeline.status) ?? 0) + 1);
    }
    return Array.from(counts.entries()).map(([status, count]) => ({ status, count }));
  }, [metrics]);
  const roleTokenGroups = useMemo(() => {
    return metrics.pipelines
      .map((pipeline) => {
        const roles = (pipeline.by_role ?? [])
          .map((role) => ({
            key: `${pipeline.pipeline_id}:${role.role}`,
            pipeline_id: pipeline.pipeline_id,
            role: role.role,
            input: role.tokens_input,
            output: role.tokens_output,
            total: role.tokens_input + role.tokens_output,
            duration_ms: role.duration_ms,
          }))
          .filter((role) => role.total > 0);
        return { pipeline_id: pipeline.pipeline_id, roles };
      })
      .filter((group) => group.roles.length > 0);
  }, [metrics]);
  const roleMetricCount = roleTokenGroups.reduce((sum, group) => sum + group.roles.length, 0);
  const maxRoleTokens = Math.max(
    ...roleTokenGroups.flatMap((group) => group.roles.map((item) => item.total)),
    1,
  );

  return (
    <section className="page">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Observability View</p>
          <h2>仪表盘</h2>
        </div>
        <span className="badge badge--running">live metrics</span>
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
                <td>消费 `/metrics/pipelines` 聚合返回</td>
              </tr>
              <tr>
                <th>数据来源</th>
                <td>后端 Pipeline session 与 stage 结果</td>
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

      {roleTokenGroups.length ? (
        <div className="panel chart">
          <div className="toolbar">
            <div>
              <p className="eyebrow">Review Role Tokens</p>
              <h3>按 role 拆分 token 堆叠柱</h3>
            </div>
            <span className="badge badge--pending">{roleMetricCount} role metrics</span>
          </div>
          <div className="legend-row">
            <span><i className="legend-swatch legend-swatch--input" />input</span>
            <span><i className="legend-swatch legend-swatch--output" />output</span>
          </div>
          <div className="role-token-groups">
            {roleTokenGroups.map((group) => (
              <section key={group.pipeline_id} className="role-token-group">
                <div className="role-token-group__header">
                  <strong>{group.pipeline_id}</strong>
                  <span>{group.roles.length} roles</span>
                </div>
                <div className="role-token-chart">
                  {group.roles.map((item) => (
                    <div key={item.key} className="role-token-column">
                      <div className="role-token-column__plot">
                        <div
                          className="role-token-column__stack"
                          style={{ height: `${Math.max(16, (item.total / maxRoleTokens) * 100)}%` }}
                          title={`${item.pipeline_id} / ${item.role}: ${item.total} tokens, input ${item.input}, output ${item.output}`}
                        >
                          <div
                            className="role-token-column__segment role-token-column__segment--output"
                            style={{ height: `${(item.output / item.total) * 100}%` }}
                          />
                          <div
                            className="role-token-column__segment role-token-column__segment--input"
                            style={{ height: `${(item.input / item.total) * 100}%` }}
                          />
                        </div>
                      </div>
                      <div className="role-token-column__meta">
                        <strong>{item.role}</strong>
                        <span>{item.total} tokens</span>
                        <span>{item.input}/{item.output}</span>
                        <span>{item.duration_ms}ms</span>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
