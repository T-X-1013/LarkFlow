import type { ChangeEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import {
  ApiError,
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

function toActionErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 404) return "目标 Pipeline 不存在或已被清理。";
    if (error.status === 409) return error.message || "当前状态不允许执行该操作。";
    if (error.status === 400) return error.message || "请求参数校验失败。";
    return `请求失败（${error.status}）: ${error.message}`;
  }
  return error instanceof Error ? error.message : "请求失败，请稍后重试。";
}

export function PipelineDetailPage() {
  const { pipelineId = "" } = useParams();
  const [pipeline, setPipeline] = useState<PipelineState | null>(null);
  const [lastAction, setLastAction] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [selectedStage, setSelectedStage] = useState<Stage>("design");
  const [artifact, setArtifact] = useState<ArtifactResponse | null>(null);

  useEffect(() => {
    let active = true;
    getPipeline(pipelineId)
      .then((next) => {
        if (active) {
          setPipeline(next);
          setErrorMessage(null);
        }
      })
      .catch((error) => {
        if (active) {
          setPipeline(null);
          setErrorMessage(toActionErrorMessage(error));
        }
      });
    return () => {
      active = false;
    };
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

  useEffect(() => {
    if (!pipeline) return;
    if (pipeline.status !== "running" && pipeline.status !== "waiting_approval") return;

    const timer = window.setInterval(() => {
      getPipeline(pipeline.id)
        .then((next) => {
          setPipeline(next);
          setErrorMessage(null);
        })
        .catch((error) => {
          setErrorMessage(toActionErrorMessage(error));
        });
    }, 2500);

    return () => {
      window.clearInterval(timer);
    };
  }, [pipeline]);

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
      setLastAction(`已执行 ${action.toUpperCase()} 操作`);
      setErrorMessage(null);
    } catch (error) {
      setErrorMessage(toActionErrorMessage(error));
    }
  }

  async function handleProviderChange(event: ChangeEvent<HTMLSelectElement>) {
    if (!pipeline) return;
    const provider = event.target.value;
    try {
      setPipeline(await updateProvider(pipeline.id, provider));
      setLastAction(`Provider 已切换为 ${provider}`);
      setErrorMessage(null);
    } catch (error) {
      setErrorMessage(toActionErrorMessage(error));
    }
  }

  async function handleCheckpoint(action: "approve" | "reject", checkpoint: CheckpointName) {
    if (!pipeline) return;
    try {
      const next =
        action === "approve"
          ? await approveCheckpoint(pipeline.id, checkpoint)
          : await rejectCheckpoint(pipeline.id, checkpoint, "reject from console");
      setPipeline(next);
      setLastAction(
        action === "approve"
          ? `已批准 ${checkpoint} checkpoint`
          : `已驳回 ${checkpoint} checkpoint`,
      );
      setErrorMessage(null);
    } catch (error) {
      setErrorMessage(toActionErrorMessage(error));
    }
  }

  const stageRows = useMemo(() => Object.values(pipeline?.stages ?? {}).filter(Boolean), [pipeline]);
  const totalInput = stageRows.reduce((sum, stage) => sum + (stage?.tokens.input ?? 0), 0);
  const totalOutput = stageRows.reduce((sum, stage) => sum + (stage?.tokens.output ?? 0), 0);
  const totalDuration = stageRows.reduce((sum, stage) => sum + (stage?.duration_ms ?? 0), 0);

  if (!pipeline) {
    return (
      <section className="page">
        <div className="panel">
          <h2>Pipeline 未找到</h2>
          <p className="muted">{errorMessage ?? "请确认 URL 中的 pipeline id 存在且后端服务可访问。"}</p>
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
      {lastAction ? <p className="flash-note">{lastAction}</p> : null}
      {errorMessage ? <p className="flash-note flash-note--error">{errorMessage}</p> : null}

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
            当前预览内容来自 <code>GET /pipelines/:id/stages/:stage/artifact</code>。
          </p>
          <pre className="artifact-preview">
            {artifact?.content ?? "当前阶段暂无 artifact 内容，或尚未产生产物。"}
          </pre>
        </div>
      </div>
    </section>
  );
}
