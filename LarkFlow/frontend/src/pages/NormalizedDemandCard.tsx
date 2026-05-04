import { useEffect, useMemo, useState } from "react";

import { clarifyPipeline } from "../lib/api";
import type { NormalizedDemandSnapshot, PipelineState } from "../types/api";

interface Props {
  snapshot?: NormalizedDemandSnapshot | null;
  pipelineId?: string;
  status?: PipelineState["status"];
  onClarified?: (next: PipelineState) => void;
}

function nfrBadges(nfr: NormalizedDemandSnapshot["nfr"]) {
  const on = Object.entries(nfr).filter(([, v]) => v).map(([k]) => k);
  if (on.length === 0) return <span className="muted">无显式约束</span>;
  return (
    <div className="badge-row">
      {on.map((flag) => (
        <span key={flag} className="badge">{flag}</span>
      ))}
    </div>
  );
}

export function NormalizedDemandCard({ snapshot, pipelineId, status, onClarified }: Props) {
  const awaitingClarification = status === "waiting_clarification";
  const initialAnswers = useMemo(
    () => (snapshot?.open_questions ?? []).map((q) => ({ question: q.text, answer: "" })),
    [snapshot],
  );
  const [answers, setAnswers] = useState(initialAnswers);
  const [submitting, setSubmitting] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    setAnswers(initialAnswers);
    setNote(null);
  }, [initialAnswers]);

  if (!snapshot || (!snapshot.raw_demand && !snapshot.goal)) return null;

  const hasApis = snapshot.apis.length > 0;
  const hasQuestions = snapshot.open_questions.length > 0;

  async function handleSubmit() {
    if (!pipelineId) return;
    setSubmitting(true);
    setNote(null);
    try {
      const filtered = answers.filter((a) => a.answer.trim().length > 0);
      const next = await clarifyPipeline(pipelineId, filtered);
      onClarified?.(next);
      if (next.status === "waiting_clarification") {
        setNote("部分问题仍未回答；请补充后再次提交。");
      } else {
        setNote("澄清已提交，Pipeline 已继续推进。");
      }
    } catch (err: unknown) {
      setNote(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="panel">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Phase 0 · Normalized Demand</p>
          <h3>结构化需求（Phase 1 权威输入）</h3>
          <p className="muted">
            由 <code>pipeline/phase0/normalizer.py</code> 从自然语言解析得到；Phase 1
            设计、Phase 2 实现、Phase 4 审查都以这份结构化快照为准。
          </p>
        </div>
        <div className="badge-row">
          <span className="badge">source: {snapshot.source}</span>
          <span className="badge">conf {snapshot.confidence.toFixed(2)}</span>
          {snapshot.touches_python ? (
            <span className="badge badge--pending">Python 代码改动</span>
          ) : null}
        </div>
      </div>

      <table>
        <tbody>
          <tr>
            <th style={{ width: "140px" }}>Goal</th>
            <td className="cell-break">{snapshot.goal || "—"}</td>
          </tr>
          <tr>
            <th>Out of scope</th>
            <td className="cell-break">
              {snapshot.out_of_scope.length
                ? snapshot.out_of_scope.join("；")
                : "—"}
            </td>
          </tr>
          <tr>
            <th>Entities</th>
            <td className="cell-break">
              {snapshot.entities.length ? snapshot.entities.join(", ") : "—"}
            </td>
          </tr>
          <tr>
            <th>Domain tags</th>
            <td>
              {snapshot.domain_tags.length ? (
                <div className="badge-row">
                  {snapshot.domain_tags.map((tag) => (
                    <span key={tag} className="badge badge--running">{tag}</span>
                  ))}
                </div>
              ) : (
                "—"
              )}
            </td>
          </tr>
          <tr>
            <th>NFR</th>
            <td>{nfrBadges(snapshot.nfr)}</td>
          </tr>
          <tr>
            <th>Persistence</th>
            <td className="cell-break">
              {snapshot.persistence.needs_storage || snapshot.persistence.needs_migration ? (
                <>
                  <span className="badge">
                    {snapshot.persistence.needs_migration ? "DDL 变更" : "仅读写"}
                  </span>{" "}
                  {snapshot.persistence.tables.length ? (
                    <span className="muted">表：{snapshot.persistence.tables.join(", ")}</span>
                  ) : null}
                  {snapshot.persistence.notes ? (
                    <div className="muted">{snapshot.persistence.notes}</div>
                  ) : null}
                </>
              ) : (
                "—"
              )}
            </td>
          </tr>
        </tbody>
      </table>

      {hasApis ? (
        <>
          <p className="eyebrow" style={{ marginTop: "1.5em" }}>APIs</p>
          <table>
            <thead>
              <tr>
                <th>Method</th>
                <th>Path</th>
                <th>Purpose</th>
              </tr>
            </thead>
            <tbody>
              {snapshot.apis.map((api, idx) => (
                <tr key={`${api.method}-${api.path}-${idx}`}>
                  <td>{api.method || "—"}</td>
                  <td className="cell-break">
                    <code>{api.path || "TBD"}</code>
                  </td>
                  <td className="cell-break">{api.purpose || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : null}

      {hasQuestions ? (
        <>
          <p className="eyebrow" style={{ marginTop: "1.5em" }}>Open Questions</p>
          {awaitingClarification ? (
            <>
              <p className="muted">
                Pipeline 已挂起（<code>waiting_clarification</code>）。回答下方 blocking 问题后提交，
                系统会重新规范化需求并继续 Phase 1。
              </p>
              <table>
                <thead>
                  <tr>
                    <th style={{ width: "40%" }}>问题</th>
                    <th>候选</th>
                    <th>你的答复</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.open_questions.map((q, idx) => (
                    <tr
                      key={idx}
                      style={q.blocking ? { backgroundColor: "rgba(220,20,60,0.06)" } : undefined}
                    >
                      <td className="cell-break">
                        {q.blocking ? <strong style={{ color: "crimson" }}>[BLOCKING] </strong> : null}
                        {q.text}
                      </td>
                      <td className="cell-break muted">
                        {q.candidates.length ? q.candidates.join(" / ") : "—"}
                      </td>
                      <td>
                        <input
                          className="select"
                          style={{ width: "100%" }}
                          value={answers[idx]?.answer ?? ""}
                          onChange={(e) => {
                            const next = [...answers];
                            next[idx] = {
                              question: q.text,
                              answer: e.target.value,
                            };
                            setAnswers(next);
                          }}
                          placeholder={q.blocking ? "请回答" : "可选"}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="button-row" style={{ marginTop: "0.75em" }}>
                <button
                  className="button"
                  type="button"
                  onClick={handleSubmit}
                  disabled={submitting || !pipelineId}
                >
                  {submitting ? "提交中…" : "提交澄清"}
                </button>
              </div>
              {note ? (
                <p
                  className="flash-note"
                  style={
                    note.includes("继续推进")
                      ? undefined
                      : { color: "crimson", borderColor: "crimson" }
                  }
                >
                  {note}
                </p>
              ) : null}
            </>
          ) : (
            <ul>
              {snapshot.open_questions.map((q, idx) => (
                <li key={idx} style={q.blocking ? { color: "crimson" } : undefined}>
                  {q.blocking ? <strong>[BLOCKING] </strong> : null}
                  {q.text}
                  {q.candidates.length ? (
                    <span className="muted"> — 候选: {q.candidates.join(" / ")}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </>
      ) : null}
    </div>
  );
}
