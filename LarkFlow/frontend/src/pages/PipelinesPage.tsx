import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { createPipeline, listDemands } from "../lib/api";
import type { DemandListItem, PipelineStatus } from "../types/api";

const POLL_INTERVAL_MS = 3000;

function badgeClass(status: PipelineStatus) {
  if (status === "running" || status === "succeeded") return "badge badge--running";
  if (status === "paused" || status === "pending" || status === "waiting_approval") {
    return "badge badge--paused";
  }
  return "badge badge--failed";
}

function statusLabel(status: PipelineStatus, currentStage: DemandListItem["current_stage"]) {
  if (status === "waiting_approval") {
    if (currentStage === "design") return "设计审批中";
    return "部署审批中";
  }
  if (status === "running") {
    if (currentStage === "coding") return "编码中";
    if (currentStage === "test") return "测试中";
    if (currentStage === "review") return "审查中";
    return "运行中";
  }
  if (status === "paused") return "已暂停";
  if (status === "pending") return "待启动";
  if (status === "stopped") return "已停止";
  if (status === "failed") return "失败";
  if (status === "rejected") return "驳回";
  if (status === "succeeded") return "已完成";
  return status;
}

export function PipelinesPage() {
  const [pipelines, setPipelines] = useState<DemandListItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [requirement, setRequirement] = useState("");
  const [template, setTemplate] = useState("default");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<PipelineStatus | "all">("all");
  const [providerFilter, setProviderFilter] = useState<string>("all");
  const [createdId, setCreatedId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await listDemands();
        if (cancelled) return;
        setPipelines(data);
        setLoadError(null);
      } catch (err) {
        if (cancelled) return;
        setLoadError((err as Error).message);
      }
    }
    load();
    const timer = window.setInterval(load, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const filteredPipelines = useMemo(() => {
    return pipelines.filter((pipeline) => {
      const matchesQuery =
        !query ||
        pipeline.id.toLowerCase().includes(query.toLowerCase()) ||
        pipeline.requirement.toLowerCase().includes(query.toLowerCase());
      const matchesStatus = statusFilter === "all" || pipeline.status === statusFilter;
      const matchesProvider =
        providerFilter === "all" || (pipeline.provider ?? "unknown") === providerFilter;
      return matchesQuery && matchesStatus && matchesProvider;
    });
  }, [pipelines, providerFilter, query, statusFilter]);

  const summary = useMemo(() => {
    const running = pipelines.filter((item) => item.status === "running").length;
    const waiting = pipelines.filter((item) => item.status === "waiting_approval").length;
    const paused = pipelines.filter((item) => item.status === "paused").length;
    return { total: pipelines.length, running, waiting, paused };
  }, [pipelines]);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    const created = await createPipeline(requirement, template);
    setCreatedId(created.id);
    setRequirement("");
    try {
      setPipelines(await listDemands());
    } catch {
      // 下次轮询会兜底刷新
    }
  }

  return (
    <section className="page">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Pipeline Catalog</p>
          <h2>列表页</h2>
        </div>
        <span className="badge badge--running">pipelines: {summary.total} 条</span>
      </div>

      {loadError ? (
        <p className="flash-note" style={{ color: "crimson", borderColor: "crimson" }}>
          无法加载 Pipeline 列表：{loadError}
        </p>
      ) : null}

      <div className="metric-grid">
        <div className="stat-card">
          <p className="eyebrow">Total</p>
          <div className="stat-card__value">{summary.total}</div>
          <p className="muted">当前 mock 池中的 Pipeline 总量。</p>
        </div>
        <div className="stat-card">
          <p className="eyebrow">Running</p>
          <div className="stat-card__value">{summary.running}</div>
          <p className="muted">正在推进阶段循环的需求。</p>
        </div>
        <div className="stat-card">
          <p className="eyebrow">Waiting HITL</p>
          <div className="stat-card__value">{summary.waiting}</div>
          <p className="muted">停在人工审批点，等待继续。</p>
        </div>
        <div className="stat-card">
          <p className="eyebrow">Paused</p>
          <div className="stat-card__value">{summary.paused}</div>
          <p className="muted">已主动暂停，允许后续恢复。</p>
        </div>
      </div>

      <div className="details-grid">
        <form className="panel form" onSubmit={handleCreate}>
          <div>
            <p className="eyebrow">Create Pipeline</p>
            <h3>模拟创建入口</h3>
          </div>
          <input
            className="input"
            placeholder="输入需求描述"
            value={requirement}
            onChange={(event) => setRequirement(event.target.value)}
            required
          />
          <select
            className="select"
            value={template}
            onChange={(event) => setTemplate(event.target.value)}
          >
            <option value="default">default</option>
            <option value="feature">feature</option>
            <option value="bugfix">bugfix</option>
            <option value="refactor">refactor</option>
            <option value="feature_multi">feature_multi</option>
          </select>
          <button className="button" type="submit">
            创建 mock Pipeline
          </button>
          {createdId ? <p className="muted">最近创建：{createdId}</p> : null}
        </form>

        <div className="panel">
          <p className="eyebrow">Contract Notes</p>
          <h3>当前视图消费的冻结字段</h3>
          <table>
            <tbody>
              <tr>
                <th>状态</th>
                <td>`status / current_stage / provider / updated_at`</td>
              </tr>
              <tr>
                <th>详情页</th>
                <td>`stages / checkpoints / artifact_path / tokens / duration_ms`</td>
              </tr>
              <tr>
                <th>多视角 Review</th>
                <td>`feature_multi` 返回 `review_multi.subroles`，普通模板为空</td>
              </tr>
              <tr>
                <th>后续联调</th>
                <td>仅替换数据源，不调整页面结构</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel">
        <div className="toolbar">
          <div>
            <p className="eyebrow">Explorer</p>
            <h3>筛选与定位</h3>
          </div>
          <span className="muted">结果：{filteredPipelines.length} 条</span>
        </div>
        <div className="filter-grid">
          <input
            className="input"
            placeholder="按需求 ID 或需求描述搜索"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <select
            className="select"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as PipelineStatus | "all")}
          >
            <option value="all">全部状态</option>
            <option value="pending">pending</option>
            <option value="running">running</option>
            <option value="paused">paused</option>
            <option value="waiting_approval">waiting_approval</option>
            <option value="stopped">stopped</option>
            <option value="failed">failed</option>
            <option value="rejected">rejected</option>
            <option value="succeeded">succeeded</option>
          </select>
          <select
            className="select"
            value={providerFilter}
            onChange={(event) => setProviderFilter(event.target.value)}
          >
            <option value="all">全部 Provider</option>
            <option value="anthropic">anthropic</option>
            <option value="openai">openai</option>
            <option value="doubao">doubao</option>
            <option value="qwen">qwen</option>
          </select>
        </div>
      </div>

      <div className="pipeline-grid">
        {filteredPipelines.length ? (
          filteredPipelines.map((pipeline) => (
            <article key={pipeline.id} className="pipeline-card">
              <div className="pipeline-card__meta">
                <span className={badgeClass(pipeline.status)}>
                  {statusLabel(pipeline.status, pipeline.current_stage)}
                </span>
                <span className="badge badge--pending">{pipeline.current_stage ?? "n/a"}</span>
                <span className="muted">{pipeline.provider ?? "provider pending"}</span>
              </div>
              <div>
                <h3>{pipeline.id}</h3>
                <p className="muted">{pipeline.requirement}</p>
              </div>
              <div className="row">
                <span>template: {pipeline.template}</span>
                <span>runtime: {pipeline.runtime_available ? "available" : "base only"}</span>
                <span>
                  updated:{" "}
                  {pipeline.updated_at
                    ? new Date(pipeline.updated_at * 1000).toLocaleString()
                    : "n/a"}
                </span>
              </div>
              {pipeline.runtime_available ? (
                <Link className="button--ghost" to={`/pipelines/${pipeline.id}`}>
                  查看详情
                </Link>
              ) : (
                <div className="muted" style={{ display: "grid", gap: 6 }}>
                  <span
                    className="button--ghost"
                    aria-disabled="true"
                    style={{ opacity: 0.45, display: "inline-block" }}
                  >
                    仅同步 Base 状态
                  </span>
                  <span>当前状态来自多维表格，详情运行态需等待后端重新接管。</span>
                </div>
              )}
            </article>
          ))
        ) : (
          <div className="panel empty-state">
            <p className="eyebrow">No Match</p>
            <h3>当前筛选条件下没有结果</h3>
            <p className="muted">可以清空关键词、状态或 Provider 筛选，或者先创建新的 mock Pipeline。</p>
          </div>
        )}
      </div>
    </section>
  );
}
