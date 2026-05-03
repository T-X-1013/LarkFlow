import type { ChangeEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import {
  approveCheckpoint,
  getPipeline,
  getStageArtifact,
  pausePipeline,
  rejectCheckpoint,
  resumePipeline,
  startPipeline,
  stopPipeline,
  updateProvider,
} from "../lib/api";
import type { ArtifactResponse, CheckpointName, PipelineState, Stage } from "../types/api";

export function PipelineDetailPage() {
  const { pipelineId = "" } = useParams();
  const [pipeline, setPipeline] = useState<PipelineState | null>(null);
  const [note, setNote] = useState<{ text: string; isError: boolean } | null>(null);
  const [selectedStage, setSelectedStage] = useState<Stage>("design");
  const [artifact, setArtifact] = useState<ArtifactResponse | null>(null);

  useEffect(() => {
    getPipeline(pipelineId).then(setPipeline).catch(() => setPipeline(null));
  }, [pipelineId]);

  useEffect(() => {
    if (!pipeline) return;
    const fallbackStage = (pipeline.current_stage ?? "design") as Stage;
    setSelectedStage((current) =>
      pipeline.stages[current] ? current : pipeline.stages[fallbackStage] ? fallbackStage : "design",
    );
  }, [pipeline]);

  useEffect(() => {
    if (!pipeline) return;
    getStageArtifact(pipeline.id, selectedStage)
      .then(setArtifact)
      .catch(() => setArtifact(null));
  }, [pipeline, selectedStage]);

  async function runAction(action: "start" | "pause" | "resume" | "stop") {
    if (!pipeline) return;
    const fn =
      action === "start"
        ? startPipeline
        : action === "pause"
          ? pausePipeline
          : action === "resume"
            ? resumePipeline
            : stopPipeline;
    try {
      setPipeline(await fn(pipeline.id));
      setNote({ text: `已执行 ${action.toUpperCase()} 操作`, isError: false });
    } catch (err) {
      setNote({ text: `${action.toUpperCase()} 失败：${(err as Error).message}`, isError: true });
    }
  }

  async function handleProviderChange(event: ChangeEvent<HTMLSelectElement>) {
    if (!pipeline) return;
    const provider = event.target.value;
    try {
      setPipeline(await updateProvider(pipeline.id, provider));
      setNote({ text: `Provider 已切换为 ${provider}`, isError: false });
    } catch (err) {
      setNote({
        text: `Provider 切换失败：${(err as Error).message}（pipeline 启动后不可再切换）`,
        isError: true,
      });
    }
  }

  async function handleCheckpoint(action: "approve" | "reject", checkpoint: CheckpointName) {
    if (!pipeline) return;
    let reason: string | null = null;
    if (action === "reject") {
      reason = window.prompt(`请输入驳回 ${checkpoint} checkpoint 的理由`, "");
      if (reason === null) return;
      if (reason.trim() === "") reason = "no reason provided";
    }
    try {
      const next =
        action === "approve"
          ? await approveCheckpoint(pipeline.id, checkpoint)
          : await rejectCheckpoint(pipeline.id, checkpoint, reason as string);
      setPipeline(next);
      setNote({
        text:
          action === "approve"
            ? `已批准 ${checkpoint} checkpoint`
            : `已驳回 ${checkpoint} checkpoint（理由：${reason}）`,
        isError: false,
      });
    } catch (err) {
      setNote({
        text: `${action} ${checkpoint} 失败：${(err as Error).message}`,
        isError: true,
      });
    }
  }

  async function copyArtifactPath(path: string) {
    try {
      await navigator.clipboard.writeText(path);
      setNote({ text: `已复制 artifact path：${path}`, isError: false });
    } catch (err) {
      setNote({ text: `复制 artifact path 失败：${(err as Error).message}`, isError: true });
    }
  }

  const stageRows = useMemo(() => Object.values(pipeline?.stages ?? {}).filter(Boolean), [pipeline]);
  const totalInput = stageRows.reduce((sum, stage) => sum + (stage?.tokens.input ?? 0), 0);
  const totalOutput = stageRows.reduce((sum, stage) => sum + (stage?.tokens.output ?? 0), 0);
  const totalDuration = stageRows.reduce((sum, stage) => sum + (stage?.duration_ms ?? 0), 0);
  const reviewSubroles = pipeline?.review_multi?.subroles ?? [];

  if (!pipeline) {
    return (
      <section className="page">
        <div className="panel">
          <h2>Pipeline 未找到</h2>
          <p className="muted">当前 detail 页依赖 MSW mock；请确认 URL 中的 pipeline id 存在于 fixtures。</p>
        </div>
      </section>
    );
  }

  return (
    <section className="page">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Pipeline Detail</p>
          <h2>{pipeline.id}</h2>
        </div>
        <span className="badge badge--running">{pipeline.status}</span>
      </div>

      <div className="metric-grid">
        <div className="stat-card">
          <p className="eyebrow">Current Stage</p>
          <div className="stat-card__value stat-card__value--small">{pipeline.current_stage ?? "n/a"}</div>
          <p className="muted">当前正在推进或等待恢复的阶段。</p>
        </div>
        <div className="stat-card">
          <p className="eyebrow">Input Tokens</p>
          <div className="stat-card__value stat-card__value--small">{totalInput}</div>
          <p className="muted">累积输入 token。</p>
        </div>
        <div className="stat-card">
          <p className="eyebrow">Output Tokens</p>
          <div className="stat-card__value stat-card__value--small">{totalOutput}</div>
          <p className="muted">累积输出 token。</p>
        </div>
        <div className="stat-card">
          <p className="eyebrow">Duration</p>
          <div className="stat-card__value stat-card__value--small">{totalDuration}ms</div>
          <p className="muted">已记录阶段耗时总和。</p>
        </div>
      </div>

      <div className="button-row">
        <button className="button" onClick={() => runAction("start")} type="button">
          Start
        </button>
        <button className="button--ghost" onClick={() => runAction("pause")} type="button">
          Pause
        </button>
        <button className="button--ghost" onClick={() => runAction("resume")} type="button">
          Resume
        </button>
        <button className="button--ghost" onClick={() => runAction("stop")} type="button">
          Stop
        </button>
      </div>
      {note ? (
        <p className="flash-note" style={note.isError ? { color: "crimson", borderColor: "crimson" } : undefined}>
          {note.text}
        </p>
      ) : null}

      <div className="details-grid">
        <div className="panel">
          <p className="eyebrow">Overview</p>
          <h3>运行状态</h3>
          <table>
            <tbody>
              <tr>
                <th>需求描述</th>
                <td>{pipeline.requirement}</td>
              </tr>
              <tr>
                <th>当前阶段</th>
                <td>{pipeline.current_stage ?? "n/a"}</td>
              </tr>
              <tr>
                <th>Provider</th>
                <td>
                  <select className="select" value={pipeline.provider ?? "anthropic"} onChange={handleProviderChange}>
                    <option value="anthropic">anthropic</option>
                    <option value="openai">openai</option>
                    <option value="doubao">doubao</option>
                    <option value="qwen">qwen</option>
                  </select>
                </td>
              </tr>
              <tr>
                <th>更新时间</th>
                <td>{new Date(pipeline.updated_at * 1000).toLocaleString()}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div className="panel">
          <p className="eyebrow">Checkpoints</p>
          <h3>人工审批点</h3>
          <div className="timeline">
            {Object.values(pipeline.checkpoints).map((checkpoint) =>
              checkpoint ? (
                <div key={checkpoint.name} className="timeline__item">
                  <div className="badge-row">
                    <span className="badge badge--pending">{checkpoint.name}</span>
                    <span className="badge badge--running">{checkpoint.status}</span>
                  </div>
                  <p className="muted">{checkpoint.reason ?? "暂无备注"}</p>
                  <div className="button-row">
                    <button
                      className="button"
                      type="button"
                      onClick={() => handleCheckpoint("approve", checkpoint.name)}
                    >
                      Approve
                    </button>
                    <button
                      className="button--ghost"
                      type="button"
                      onClick={() => handleCheckpoint("reject", checkpoint.name)}
                    >
                      Reject
                    </button>
                  </div>
                </div>
              ) : null,
            )}
          </div>
        </div>
      </div>

      <div className="details-grid">
        <div className="panel">
          <p className="eyebrow">Stages</p>
          <h3>阶段产物与 token</h3>
          <table>
            <thead>
              <tr>
                <th>Stage</th>
                <th>Status</th>
                <th>Artifact</th>
                <th>Tokens</th>
                <th>Duration</th>
              </tr>
            </thead>
            <tbody>
              {Object.values(pipeline.stages).map((stage) =>
                stage ? (
                  <tr
                    key={stage.stage}
                    className={selectedStage === stage.stage ? "row--selected" : undefined}
                    onClick={() => setSelectedStage(stage.stage)}
                  >
                    <td>{stage.stage}</td>
                    <td>{stage.status}</td>
                    <td>{stage.artifact_path ?? "—"}</td>
                    <td>
                      {stage.tokens.input}/{stage.tokens.output}
                    </td>
                    <td>{stage.duration_ms}ms</td>
                  </tr>
                ) : null,
              )}
            </tbody>
          </table>
        </div>

        <div className="panel artifact-panel">
          <p className="eyebrow">Artifact Preview</p>
          <h3>{selectedStage} 阶段预览</h3>
          <p className="muted">
            当前预览内容来自 <code>GET /pipelines/:id/stages/:stage/artifact</code> 的 MSW mock。
          </p>
          <pre className="artifact-preview">
            {artifact?.content ?? "当前阶段暂无 artifact 内容，或尚未产生产物。"}
          </pre>
        </div>
      </div>

      {reviewSubroles.length ? (
        <div className="panel">
          <div className="toolbar">
            <div>
              <p className="eyebrow">Review Roles</p>
              <h3>多视角 Review</h3>
            </div>
            <span className="badge badge--pending">{reviewSubroles.length} roles</span>
          </div>
          <table>
            <thead>
              <tr>
                <th>Role</th>
                <th>Status</th>
                <th>Tokens</th>
                <th>Duration</th>
                <th>Artifact</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {reviewSubroles.map((role) => (
                <tr key={role.role}>
                  <td>{role.role}</td>
                  <td>{role.status}</td>
                  <td>
                    {role.tokens_input}/{role.tokens_output}
                  </td>
                  <td>{role.duration_ms}ms</td>
                  <td className="cell-break">
                    {role.artifact_path ? (
                      <button
                        className="link-button"
                        type="button"
                        onClick={() => copyArtifactPath(role.artifact_path as string)}
                      >
                        {role.artifact_path}
                      </button>
                    ) : (
                      "-"
                    )}
                  </td>
                  <td>{role.error ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
