import type {
  SkillGateSnapshot,
  SkillRoutingReason,
  SkillRoutingSnapshot,
} from "../types/api";

interface Props {
  snapshot?: SkillRoutingSnapshot | null;
  gate?: SkillGateSnapshot | null;
}

const TIER_ORDER: Record<string, number> = { baseline: 0, conditional: 1, route: 2 };

const TIER_BADGE_CLASS: Record<string, string> = {
  baseline: "badge badge--running",
  conditional: "badge badge--pending",
  route: "badge",
};

const TIER_LABEL: Record<string, string> = {
  baseline: "必读",
  conditional: "触发必读",
  route: "权重召回",
};

const SOURCE_LABEL: Record<string, string> = {
  keyword: "关键词",
  semantic: "语义",
  both: "关键词+语义",
};

const MANDATORY_TIERS = new Set(["baseline", "conditional"]);

function groupReasonsBySkill(reasons: SkillRoutingReason[]) {
  const map = new Map<string, SkillRoutingReason>();
  for (const reason of reasons) {
    if (!reason.skill) continue;
    const existing = map.get(reason.skill);
    if (!existing || (TIER_ORDER[reason.tier] ?? 9) < (TIER_ORDER[existing.tier] ?? 9)) {
      map.set(reason.skill, reason);
    }
  }
  return map;
}

export function SkillRoutingCard({ snapshot, gate }: Props) {
  if (!snapshot || snapshot.skills.length === 0) return null;

  const reasonBySkill = groupReasonsBySkill(snapshot.reasons ?? []);
  const tierCounts = (snapshot.reasons ?? []).reduce<Record<string, number>>((acc, reason) => {
    acc[reason.tier] = (acc[reason.tier] ?? 0) + 1;
    return acc;
  }, {});

  const readSet = new Set(gate?.read ?? []);
  const missingMandatory = new Set(gate?.missing_mandatory ?? []);
  const missingOptional = new Set(gate?.missing_optional ?? []);

  return (
    <div className="panel">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Skill Routing</p>
          <h3>本次需求的必读 skill 清单</h3>
          <p className="muted">
            由 <code>pipeline/skills/router.py</code> 按 <code>rules/skill-routing.yaml</code> 算出；
            Phase1/2/4 的 system prompt 会注入同一份清单。闸门会在 Phase 2 结束前校验强约束 skill 是否读齐。
          </p>
        </div>
        <div className="badge-row">
          <span className="badge badge--running">baseline {tierCounts.baseline ?? 0}</span>
          <span className="badge badge--pending">conditional {tierCounts.conditional ?? 0}</span>
          <span className="badge">route {tierCounts.route ?? 0}</span>
          {gate ? (
            <span
              className={gate.passed ? "badge badge--running" : "badge"}
              style={gate.passed ? undefined : { color: "crimson", borderColor: "crimson" }}
            >
              闸门 {gate.passed ? "通过" : "未通过"}（第 {gate.attempt} 次判读）
            </span>
          ) : null}
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Skill</th>
            <th>Tier</th>
            <th>Detail</th>
            <th>Source</th>
            <th>已读</th>
          </tr>
        </thead>
        <tbody>
          {snapshot.skills.map((skill) => {
            const reason = reasonBySkill.get(skill);
            const tier = reason?.tier ?? "";
            const tierClass = TIER_BADGE_CLASS[tier] ?? "badge";
            const source = reason?.source ?? "";
            const isRead = readSet.has(skill);
            const mandatoryMiss = missingMandatory.has(skill);
            const optionalMiss = missingOptional.has(skill);
            let readCell: string;
            let readStyle: React.CSSProperties | undefined;
            if (isRead) {
              readCell = "✓ 已读";
            } else if (mandatoryMiss) {
              readCell = "✗ 未读（强约束）";
              readStyle = { color: "crimson", fontWeight: 600 };
            } else if (optionalMiss) {
              readCell = "⚠ 未读（建议）";
              readStyle = { color: "#b87a00" };
            } else if (gate) {
              readCell = "—";
            } else {
              readCell = "尚未判读";
            }
            const rowStyle = MANDATORY_TIERS.has(tier) && mandatoryMiss
              ? { backgroundColor: "rgba(220, 20, 60, 0.08)" }
              : undefined;
            return (
              <tr key={skill} style={rowStyle}>
                <td className="cell-break">
                  <code>{skill}</code>
                </td>
                <td>
                  <span className={tierClass}>{TIER_LABEL[tier] ?? tier ?? "-"}</span>
                </td>
                <td className="cell-break">{reason?.detail || "-"}</td>
                <td>
                  {source ? (
                    <span className="badge">{SOURCE_LABEL[source] ?? source}</span>
                  ) : (
                    "-"
                  )}
                </td>
                <td style={readStyle}>{readCell}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
