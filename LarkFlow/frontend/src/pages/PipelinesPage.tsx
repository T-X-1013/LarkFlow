import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { createPipelineFromDoc, listDemands } from "../lib/api";
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

function stageLabel(stage: DemandListItem["current_stage"]) {
  if (stage === "design") return "设计阶段";
  if (stage === "coding") return "编码阶段";
  if (stage === "test") return "测试阶段";
  if (stage === "review") return "审查阶段";
  return "待分配阶段";
}

export function PipelinesPage() {
  const [pipelines, setPipelines] = useState<DemandListItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [docUrl, setDocUrl] = useState("");
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
    const created = await createPipelineFromDoc(docUrl);
    setCreatedId(created.id);
    setDocUrl("");
    try {
      setPipelines(await listDemands());
    } catch {
      // 下次轮询会兜底刷新
    }
  }

  return (
    <section className="page">
      <div className="hero hero--stacked">
        <div className="hero__layout hero__layout--stacked">
          <div className="hero__content">
            <div>
              <p className="eyebrow">Pipeline 总览</p>
              <h2 className="hero__title hero__title--stacked">在一个页面里接入需求、筛选状态并追踪每条执行链路</h2>
            </div>
            <p className="hero__lede">
              这里是需求进入系统后的主操作页，用来查看当前状态、定位具体需求，并继续进入详情页处理审批、执行和交付结果
            </p>
            <div className="hero__signal hero__signal--inline">
              <p className="eyebrow">入口概览</p>
              <strong>先看全局分布，再进入单条需求继续处理</strong>
              <div className="signal-list">
                <div className="signal-list__item">
                  <span>筛选维度</span>
                  <span>状态 / Provider / 关键词</span>
                </div>
                <div className="signal-list__item">
                  <span>详情入口</span>
                  <span>运行态完成同步后可进入</span>
                </div>
                <div className="signal-list__item">
                  <span>创建方式</span>
                  <span>需求文档 URL</span>
                </div>
              </div>
            </div>
          </div>
          <aside className="hero__aside hero__aside--stacked">
            <div className="mini-stat-grid mini-stat-grid--hero-aside">
              <div className="mini-stat">
                <p className="eyebrow">总量</p>
                <div className="mini-stat__value">{summary.total}</div>
                <div className="mini-stat__label">当前 Pipeline 总量</div>
              </div>
              <div className="mini-stat">
                <p className="eyebrow">执行中</p>
                <div className="mini-stat__value">{summary.running}</div>
                <div className="mini-stat__label">持续执行中的需求</div>
              </div>
              <div className="mini-stat">
                <p className="eyebrow">待审批</p>
                <div className="mini-stat__value">{summary.waiting}</div>
                <div className="mini-stat__label">停在人工审批点</div>
              </div>
            </div>
          </aside>
        </div>
      </div>

      {loadError ? (
        <p className="flash-note" style={{ color: "crimson", borderColor: "crimson" }}>
          无法加载 Pipeline 列表：{loadError}
        </p>
      ) : null}

      <div className="metric-grid">
        <div className="stat-card">
            <p className="eyebrow">总量</p>
          <div className="stat-card__value">{summary.total}</div>
              <p className="muted">当前已进入系统并建立链路的需求总量</p>
        </div>
        <div className="stat-card">
            <p className="eyebrow">执行中</p>
          <div className="stat-card__value">{summary.running}</div>
              <p className="muted">当前仍在继续执行中的需求数量</p>
        </div>
        <div className="stat-card">
            <p className="eyebrow">待人工审批</p>
          <div className="stat-card__value">{summary.waiting}</div>
              <p className="muted">当前停在人工审批节点，等待继续处理</p>
        </div>
        <div className="stat-card">
            <p className="eyebrow">已暂停</p>
          <div className="stat-card__value">{summary.paused}</div>
              <p className="muted">已被主动暂停，后续可以继续恢复执行</p>
        </div>
      </div>

      <div className="details-grid">
        <form className="panel form" onSubmit={handleCreate}>
          <div>
            <p className="eyebrow">创建需求</p>
            <h3>从需求文档创建真实需求</h3>
          </div>
          <input
            className="input"
            type="url"
            placeholder="输入飞书需求文档 URL"
            value={docUrl}
            onChange={(event) => setDocUrl(event.target.value)}
            required
          />
          <button className="button" type="submit">
            创建真实需求
          </button>
          <p className="form__hint muted">提交需求文档 URL 后，后端会写入飞书多维表格，并把这条需求纳入后续执行链路</p>
          {createdId ? <p className="muted">最近创建：{createdId}</p> : null}
        </form>

        <div className="panel section-heading">
          <div>
            <p className="eyebrow">字段说明</p>
            <h3>当前页面依赖的核心字段</h3>
          </div>
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
                <td>`feature_multi` 会返回 `review_multi.subroles`，普通模板下该字段为空</td>
              </tr>
              <tr>
                <th>创建语义</th>
                <td>前端提交需求文档 URL，后端负责写入飞书多维表格并启动真实需求链路</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel section-heading">
        <div className="toolbar">
          <div>
            <p className="eyebrow">筛选面板</p>
            <h3>筛选与定位</h3>
          </div>
          <span className="muted">结果：{filteredPipelines.length} 条</span>
        </div>
        <div className="filter-grid">
          <input
            className="input"
            placeholder="按需求 ID、文档链接或需求内容搜索"
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
		                <span className="badge badge--pending">{stageLabel(pipeline.current_stage)}</span>
		                <span className="muted">{pipeline.provider ?? "Provider 待分配"}</span>
	              </div>
	              <div className="pipeline-card__body">
	                <h3>需求 ID：{pipeline.id}</h3>
	                <div className="pipeline-card__detail-list">
	                  <div className="pipeline-card__detail pipeline-card__detail--inline">
	                    <span className="pipeline-card__label">
	                      {pipeline.doc_url ? "需求方案：" : "需求内容："}
	                    </span>
	                    {pipeline.doc_url ? (
	                      <a
	                        className="pipeline-card__link"
	                        href={pipeline.doc_url}
	                        target="_blank"
	                        rel="noreferrer"
	                      >
	                        {pipeline.doc_url}
	                      </a>
	                    ) : (
	                      <span className="muted">{pipeline.requirement}</span>
	                    )}
	                  </div>
	                </div>
	              </div>
	              <div className="pipeline-card__info-pills">
	                <span className="pipeline-card__info-pill">模板：{pipeline.template}</span>
	                <span className="pipeline-card__info-pill">
	                  运行态：{pipeline.runtime_available ? "已同步" : "同步中"}
	                </span>
	                <span className="pipeline-card__info-pill">
	                  更新时间：{" "}
	                  {pipeline.updated_at
	                    ? new Date(pipeline.updated_at * 1000).toLocaleString()
	                    : "暂无"}
	                </span>
	              </div>
		              <div className="pipeline-card__footer">
		                <div className="pipeline-card__footer-content">
		                  <Link className="button--ghost" to={`/pipelines/${pipeline.id}`}>
		                    查看详情
		                  </Link>
		                  <span className="muted">
		                    {pipeline.runtime_available
		                      ? "完整执行信息已返回，可继续查看阶段、审批与产物"
		                      : "当前需求已进入系统，完整执行信息尚未返回，进入详情页后可继续查看基础信息"}
		                  </span>
		                </div>
		              </div>
            </article>
          ))
        ) : (
          <div className="panel empty-state">
            <p className="eyebrow">无匹配结果</p>
            <h3>当前筛选条件下没有结果</h3>
            <p className="muted">可以清空关键词、状态或 Provider 筛选，或者先提交新的需求文档 URL</p>
          </div>
        )}
      </div>
    </section>
  );
}
