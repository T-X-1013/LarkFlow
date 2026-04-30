import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { createPipeline } from "../lib/api";
import { getDataModeLabel, loadPipelineCatalog } from "../lib/pipelineCatalog";
import type { PipelineCatalogItem } from "../lib/pipelineCatalog";
import type { PipelineStatus } from "../types/api";

function badgeClass(status: PipelineStatus) {
  if (status === "running" || status === "succeeded") return "badge badge--running";
  if (status === "paused" || status === "pending" || status === "waiting_approval") {
    return "badge badge--paused";
  }
  return "badge badge--failed";
}

export function PipelinesPage() {
  const [catalog, setCatalog] = useState<PipelineCatalogItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [requirement, setRequirement] = useState("");
  const [template, setTemplate] = useState("default");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<PipelineStatus | "all">("all");
  const [providerFilter, setProviderFilter] = useState<string>("all");
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);

  useEffect(() => {
    let active = true;

    async function refreshCatalog() {
      setIsLoading(true);
      setLoadError(null);
      try {
        const catalog = await loadPipelineCatalog();
        if (!active) return;
        setCatalog(catalog);
      } catch (error) {
        if (!active) return;
        setLoadError(error instanceof Error ? error.message : "加载 Pipeline 列表失败");
        setCatalog([]);
      } finally {
        if (active) {
          setIsLoading(false);
        }
      }
    }

    void refreshCatalog();
    return () => {
      active = false;
    };
  }, [reloadTick]);

  const filteredPipelines = useMemo(() => {
    return catalog.filter((item) => {
      const pipeline = item.state;
      const provider = pipeline?.provider ?? "unknown";
      const requirementText = pipeline?.requirement ?? "";
      const status = pipeline?.status ?? item.metric.status;
      const matchesQuery =
        !query ||
        item.id.toLowerCase().includes(query.toLowerCase()) ||
        requirementText.toLowerCase().includes(query.toLowerCase());
      const matchesStatus = statusFilter === "all" || status === statusFilter;
      const matchesProvider = providerFilter === "all" || provider === providerFilter;
      return matchesQuery && matchesStatus && matchesProvider;
    });
  }, [catalog, providerFilter, query, statusFilter]);

  const summary = useMemo(() => {
    const running = catalog.filter((item) => item.metric.status === "running").length;
    const waiting = catalog.filter((item) => item.metric.status === "waiting_approval").length;
    const paused = catalog.filter((item) => item.metric.status === "paused").length;
    return { total: catalog.length, running, waiting, paused };
  }, [catalog]);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    const created = await createPipeline(requirement, template);
    setCreatedId(created.id);
    setRequirement("");
    setReloadTick((current) => current + 1);
  }

  return (
    <section className="page">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Pipeline Catalog</p>
          <h2>列表页</h2>
        </div>
        <span className="badge badge--running">
          {getDataModeLabel()}: {summary.total} 条
        </span>
      </div>

      {loadError ? <p className="flash-note flash-note--error">{loadError}</p> : null}

      <div className="metric-grid">
        <div className="stat-card">
          <p className="eyebrow">Total</p>
          <div className="stat-card__value">{summary.total}</div>
          <p className="muted">当前控制面中可被发现的 Pipeline 总量。</p>
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
            <h3>手工创建入口</h3>
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
          </select>
          <button className="button" type="submit">
            创建 Pipeline
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
                <th>后续联调</th>
                <td>当前已统一走 HTTP API；live 模式先读取 metrics，再按 id 补全详情</td>
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
        {isLoading ? (
          <div className="panel empty-state">
            <p className="eyebrow">Loading</p>
            <h3>正在拉取 Pipeline 列表</h3>
            <p className="muted">当前页面先读取 `/metrics/pipelines`，再补全每条 Pipeline 详情。</p>
          </div>
        ) : filteredPipelines.length ? (
          filteredPipelines.map((pipeline) => (
            <article key={pipeline.id} className="pipeline-card">
              <div className="pipeline-card__meta">
                <span className={badgeClass(pipeline.state?.status ?? pipeline.metric.status)}>
                  {pipeline.state?.status ?? pipeline.metric.status}
                </span>
                <span className="badge badge--pending">
                  {pipeline.state?.current_stage ?? "n/a"}
                </span>
                <span className="muted">{pipeline.state?.provider ?? "provider pending"}</span>
              </div>
              <div>
                <h3>{pipeline.id}</h3>
                <p className="muted">
                  {pipeline.state?.requirement ?? "详情补全失败，当前仅展示 metrics 快照。"}
                </p>
              </div>
              <div className="row">
                <span>template: {pipeline.state?.template ?? "n/a"}</span>
                <span>tokens: {pipeline.metric.tokens.input}/{pipeline.metric.tokens.output}</span>
                <span>
                  updated:{" "}
                  {pipeline.state
                    ? new Date(pipeline.state.updated_at * 1000).toLocaleString()
                    : "n/a"}
                </span>
              </div>
              <Link className="button--ghost" to={`/pipelines/${pipeline.detailId}`}>
                查看详情
              </Link>
            </article>
          ))
        ) : (
          <div className="panel empty-state">
            <p className="eyebrow">No Match</p>
            <h3>当前筛选条件下没有结果</h3>
            <p className="muted">可以清空关键词、状态或 Provider 筛选，或者先创建新的 Pipeline。</p>
          </div>
        )}
      </div>
    </section>
  );
}
