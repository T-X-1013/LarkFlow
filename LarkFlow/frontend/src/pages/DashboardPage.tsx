import { useEffect, useMemo, useState } from "react";

import { listDemands, listMetrics } from "../lib/api";
import type { DemandListItem, MetricsResponse } from "../types/api";

export function DashboardPage() {
  const [demands, setDemands] = useState<DemandListItem[]>([]);
  const [metrics, setMetrics] = useState<MetricsResponse>({ pipelines: [] });

  useEffect(() => {
    let cancelled = false;
    async function loadDashboardData() {
      try {
        const [nextDemands, nextMetrics] = await Promise.all([
          listDemands(),
          listMetrics(),
        ]);
        if (cancelled) return;
        setDemands(nextDemands);
        setMetrics(nextMetrics);
      } catch {
        if (cancelled) return;
        setDemands([]);
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

  const baseDemandIds = useMemo(() => new Set(demands.map((item) => item.id)), [demands]);
  const filteredMetrics = useMemo(
    () => metrics.pipelines.filter((item) => baseDemandIds.has(item.pipeline_id)),
    [baseDemandIds, metrics],
  );

  const summary = useMemo(() => {
    const total = demands.length;
    const totalDuration = filteredMetrics.reduce((sum, item) => sum + item.duration_ms, 0);
    const totalTokens = filteredMetrics.reduce(
      (sum, item) => sum + item.tokens.input + item.tokens.output,
      0,
    );
    return {
      total,
      avgDuration: filteredMetrics.length ? Math.round(totalDuration / filteredMetrics.length) : 0,
      totalTokens,
      successful: demands.filter((item) => item.status === "succeeded").length,
    };
  }, [demands, filteredMetrics]);

  const bars = filteredMetrics.map((item) => ({
    label: item.pipeline_id,
    value: item.duration_ms,
  }));
  const maxBar = Math.max(...bars.map((item) => item.value), 1);
  const providerBreakdown = useMemo(() => {
    const counts = new Map<string, number>();
    for (const demand of demands) {
      const provider = demand.provider ?? "unknown";
      counts.set(provider, (counts.get(provider) ?? 0) + 1);
    }
    return Array.from(counts.entries()).map(([provider, count]) => ({ provider, count }));
  }, [demands]);
  const statusBreakdown = useMemo(() => {
    const counts = new Map<string, number>();
    for (const demand of demands) {
      counts.set(demand.status, (counts.get(demand.status) ?? 0) + 1);
    }
    return Array.from(counts.entries()).map(([status, count]) => ({ status, count }));
  }, [demands]);
  const roleTokenGroups = useMemo(() => {
    return filteredMetrics
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
  }, [filteredMetrics]);
  const roleMetricCount = roleTokenGroups.reduce((sum, group) => sum + group.roles.length, 0);
  const maxRoleTokens = Math.max(
    ...roleTokenGroups.flatMap((group) => group.roles.map((item) => item.total)),
    1,
  );

  return (
    <section className="page">
      <div className="hero hero--stacked">
        <div className="hero__layout hero__layout--stacked">
          <div className="hero__content">
            <div>
              <p className="eyebrow">运行观测</p>
              <h2 className="hero__title hero__title--stacked">让每条需求的运行状态、模型分布和资源消耗一眼可读</h2>
            </div>
            <p className="hero__lede">
              这里聚合需求记录和运行指标，用来快速判断当前链路是否顺畅、资源消耗是否合理，以及哪些需求需要继续关注
            </p>
            <div className="hero__signal hero__signal--inline">
              <p className="eyebrow">实时信号</p>
              <strong>仪表盘每 5 秒自动刷新一次</strong>
              <div className="signal-list">
                <div className="signal-list__item">
                  <span>主数据来源</span>
                  <span>/demands</span>
                </div>
                <div className="signal-list__item">
                  <span>指标来源</span>
                  <span>/metrics/pipelines</span>
                </div>
                <div className="signal-list__item">
                  <span>当前模式</span>
                  <span>需求记录 + 运行指标</span>
                </div>
              </div>
            </div>
          </div>
          <aside className="hero__aside hero__aside--stacked">
            <div className="mini-stat-grid mini-stat-grid--hero-aside">
              <div className="mini-stat">
                <p className="eyebrow">需求数</p>
                <div className="mini-stat__value">{summary.total}</div>
                <div className="mini-stat__label">纳入本次观测的需求数</div>
              </div>
              <div className="mini-stat">
                <p className="eyebrow">平均耗时</p>
                <div className="mini-stat__value">{summary.avgDuration}ms</div>
                <div className="mini-stat__label">平均运行耗时</div>
              </div>
              <div className="mini-stat">
                <p className="eyebrow">Token 总量</p>
                <div className="mini-stat__value">{summary.totalTokens}</div>
                <div className="mini-stat__label">累计输入输出 token</div>
              </div>
            </div>
          </aside>
        </div>
      </div>

      <div className="metric-grid">
        <div className="stat-card">
          <p className="eyebrow">需求数</p>
          <div className="stat-card__value">{summary.total}</div>
          <span className="stat-card__trend">实时观测范围</span>
        </div>
        <div className="stat-card">
          <p className="eyebrow">平均耗时</p>
          <div className="stat-card__value">{summary.avgDuration}ms</div>
          <span className="stat-card__trend">平均运行耗时</span>
        </div>
        <div className="stat-card">
          <p className="eyebrow">Token 总量</p>
          <div className="stat-card__value">{summary.totalTokens}</div>
          <span className="stat-card__trend">输入与输出总量</span>
        </div>
        <div className="stat-card">
          <p className="eyebrow">已完成</p>
          <div className="stat-card__value">{summary.successful}</div>
          <span className="stat-card__trend">已完成需求</span>
        </div>
      </div>

      <div className="details-grid">
        <div className="panel chart">
          <div>
            <p className="eyebrow">耗时排序</p>
            <h3>按耗时排序</h3>
          </div>
          <div className="bar-list">
            {bars.length ? (
              bars.map((bar) => (
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
              ))
            ) : (
              <p className="muted">当前暂无可用运行耗时</p>
            )}
          </div>
        </div>

        <div className="panel section-heading">
          <div>
            <p className="eyebrow">数据范围</p>
            <h3>当前页面展示的数据范围</h3>
          </div>
          <table>
            <tbody>
              <tr>
                <th>现阶段</th>
                <td>主数据来自 `/demands`，运行指标统计当前已接入系统的需求记录</td>
              </tr>
              <tr>
                <th>数据来源</th>
                <td>飞书需求记录与运行指标聚合结果</td>
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
        <div className="panel section-heading">
          <div>
            <p className="eyebrow">模型分布</p>
            <h3>Provider 分布</h3>
          </div>
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
        <div className="panel section-heading">
          <div>
            <p className="eyebrow">状态分布</p>
            <h3>状态分布</h3>
          </div>
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
              <p className="eyebrow">角色 Token</p>
              <h3>按 role 拆分 token 堆叠柱</h3>
            </div>
            <span className="badge badge--pending">{roleMetricCount} 个角色指标</span>
          </div>
          <div className="legend-row">
            <span><i className="legend-swatch legend-swatch--input" />输入</span>
            <span><i className="legend-swatch legend-swatch--output" />输出</span>
          </div>
          <div className="role-token-groups">
            {roleTokenGroups.map((group) => (
              <section key={group.pipeline_id} className="role-token-group">
                <div className="role-token-group__header">
                  <strong>{group.pipeline_id}</strong>
                  <span>{group.roles.length} 个角色</span>
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
