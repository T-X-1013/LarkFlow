import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

type CapabilityKey = "intake" | "approval" | "execution" | "observability";

type CapabilityTab = {
  key: CapabilityKey;
  label: string;
  headline: string;
  summary: string;
  metric: string;
  metricLabel: string;
  cards: Array<{ title: string; desc: string }>;
  previewTitle: string;
  previewEyebrow: string;
  previewTone: string;
};

const capabilityTabs: CapabilityTab[] = [
  {
    key: "intake",
    label: "需求接入",
    headline: "让飞书需求文档以统一方式进入 LarkFlow 并形成可追踪链路",
    summary: "提交需求文档 URL 后，系统会写入飞书多维表格并纳入执行控制流程，后续可继续查看状态、审批与运行观测",
    metric: "4 类核心链路",
    metricLabel: "覆盖需求进入、审批、执行、观测四类核心路径",
    cards: [
      { title: "飞书需求", desc: "打通飞书多维表格，根据需求文档进行处理" },
      { title: "模板选择", desc: "feature、refactor、feature_multi 等多种模板可供选择" },
      { title: "状态登记", desc: "可实时查看需求状态，便于跟进项目进度" },
      { title: "列表定位", desc: "可按关键词、状态和 Provider 快速检索需求" },
    ],
    previewTitle: "需求接入流程",
    previewEyebrow: "Demand Intake",
    previewTone: "浅量化展示需求如何进入平台，而不是占位图。",
  },
  {
    key: "approval",
    label: "审批流转",
    headline: "把人工审批节点组织成清晰、可追踪、可恢复的流程能力",
    summary: "设计审批与部署审批会直接影响需求推进状态，前端负责把审批动作、结果反馈和后续流转清晰呈现",
    metric: "2 个关键审批点",
    metricLabel: "设计审批与部署审批都已经拥有前端交互位置",
    cards: [
      { title: "设计审批", desc: "设计阶段完成后进入人工确认，明确记录当前审批状态" },
      { title: "部署审批", desc: "交付前保留最终确认节点，避免需求直接进入发布流程" },
      { title: "审批动作", desc: "支持 approve / reject，并保留结果反馈与处理理由" },
      { title: "状态恢复", desc: "审批完成后可继续推进需求，也可中断后续执行链路" },
    ],
    previewTitle: "审批状态视图",
    previewEyebrow: "Approval Flow",
    previewTone: "展示审批节点当前状态、处理动作和后续推进结果",
  },
  {
    key: "execution",
    label: "Agent 执行",
    headline: "把执行过程组织成可感知、可控制、可追踪的阶段链路",
    summary: "设计、编码、测试、审查四个阶段会在同一条 Pipeline 中连续推进，前端负责呈现当前阶段、控制动作和产物状态",
    metric: "4 个标准阶段",
    metricLabel: "设计、编码、测试、审查被组织进一条连续交付路径",
    cards: [
      { title: "阶段推进", desc: "从设计到审查逐步推进，当前阶段在前端中清晰可见" },
      { title: "运行控制", desc: "支持 Start、Pause、Resume、Stop 等执行控制动作" },
      { title: "Provider 切换", desc: "可在详情页调整模型 Provider，并查看变更结果反馈" },
      { title: "产物预览", desc: "阶段产物可继续承接到详情页中的 artifact 预览与检查" },
    ],
    previewTitle: "执行链路视图",
    previewEyebrow: "Execution Surface",
    previewTone: "展示当前阶段、执行控制、Provider 与产物状态，形成更真实的执行界面",
  },
  {
    key: "observability",
    label: "运行观测",
    headline: "平台视图直观展示运行指标",
    summary: "系统会持续聚合 duration、token、Provider 与状态分布等信息，帮助用户快速判断当前链路的运行情况",
    metric: "多维运行指标",
    metricLabel: "支持 duration、tokens、Provider 分布和 role 级统计拆分",
    cards: [
      { title: "Duration", desc: "快速识别高耗时需求，帮助判断当前链路的执行效率" },
      { title: "Token", desc: "统一统计输入输出 token，承接成本、吞吐与效率视角" },
      { title: "Provider", desc: "清晰展示不同模型供应方的分布与当前使用情况" },
      { title: "Role 统计", desc: "在 review multi 场景下支持 role 级指标拆分与聚合" },
    ],
    previewTitle: "运行指标概览",
    previewEyebrow: "Observability",
    previewTone: "展示高价值运行指标摘要，帮助用户快速进入 Dashboard 查看完整数据",
  },
];

function PreviewPanel({ capability }: { capability: CapabilityTab }) {
  if (capability.key === "intake") {
    return (
      <div className="preview-scene">
        <div className="preview-scene__route">
          <div className="preview-stage">
            <span className="preview-stage__chip">输入</span>
            <strong>需求文档 URL</strong>
            <p className="muted">提交飞书需求文档链接，作为真实需求入口</p>
          </div>
          <div className="preview-stage preview-stage--accent">
            <span className="preview-stage__chip">写入</span>
            <strong>飞书多维表格</strong>
            <p className="muted">后端写入需求记录，并同步基础状态信息</p>
          </div>
          <div className="preview-stage">
            <span className="preview-stage__chip">管理</span>
            <strong>Pipeline 列表</strong>
            <p className="muted">进入执行控制页，继续查看状态、审批和运行进展</p>
          </div>
        </div>
        <div className="preview-note-grid">
          <div className="preview-note">
            <span>支持来源</span>
            <strong>飞书需求文档</strong>
          </div>
          <div className="preview-note">
            <span>进入方式</span>
            <strong>多维表格、页面提交URL</strong>
          </div>
        </div>
      </div>
    );
  }

  if (capability.key === "approval") {
    return (
      <div className="preview-approval">
        <div className="preview-approval__lane">
          <div className="preview-approval__item">
            <div className="preview-approval__item-head">
              <strong>设计审批</strong>
              <span className="badge badge--pending">waiting approval</span>
            </div>
            <p className="muted">设计产物准备完成，等待人工确认后继续推进</p>
          </div>
          <div className="preview-approval__item">
            <div className="preview-approval__item-head">
              <strong>部署审批</strong>
              <span className="badge badge--running">ready to release</span>
            </div>
            <p className="muted">交付前保留人工确认，确保关键阶段有最终把关</p>
          </div>
        </div>
        <div className="preview-approval__actions">
          <button type="button" className="button">
            Approve
          </button>
          <button type="button" className="button--ghost">
            Reject
          </button>
        </div>
        <div className="preview-note">
          <span>流程意义</span>
          <strong>把审批从状态字段变成可视化决策界面</strong>
        </div>
      </div>
    );
  }

  if (capability.key === "execution") {
    return (
      <div className="preview-runtime">
        <div className="preview-runtime__header">
          <span className="preview-stage__chip">当前链路</span>
          <strong>feature_multi / 编码阶段</strong>
        </div>
        <div className="preview-runtime__stages">
          <div className="preview-runtime__step preview-runtime__step--done">设计</div>
          <div className="preview-runtime__step preview-runtime__step--active">编码</div>
          <div className="preview-runtime__step">测试</div>
          <div className="preview-runtime__step">审查</div>
        </div>
        <div className="preview-runtime__meta">
          <div className="preview-note">
            <span>Provider</span>
            <strong>OpenAI / Qwen</strong>
          </div>
          <div className="preview-note">
            <span>产物状态</span>
            <strong>可预览</strong>
          </div>
        </div>
        <div className="preview-runtime__controls">
          <span className="preview-window__footer-pill">Start</span>
          <span className="preview-window__footer-pill">Pause</span>
          <span className="preview-window__footer-pill">Resume</span>
          <span className="preview-window__footer-pill">Stop</span>
        </div>
      </div>
    );
  }

  return (
    <div className="preview-observability">
      <div className="preview-observability__chart">
        <div className="preview-observability__bar preview-observability__bar--a" />
        <div className="preview-observability__bar preview-observability__bar--b" />
        <div className="preview-observability__bar preview-observability__bar--c" />
      </div>
      <div className="preview-observability__stats">
        <div className="preview-note">
          <span>平均耗时</span>
          <strong>2.8s</strong>
        </div>
        <div className="preview-note">
          <span>Token 总量</span>
          <strong>18.4k</strong>
        </div>
        <div className="preview-note">
          <span>Provider 分布</span>
          <strong>OpenAI / Doubao / Qwen / Anthropic</strong>
        </div>
      </div>
      <div className="preview-window__footer">
        <span className="preview-window__footer-pill">耗时</span>
        <span className="preview-window__footer-pill">Token</span>
        <span className="preview-window__footer-pill">角色分布</span>
      </div>
    </div>
  );
}

export function HomePage() {
  const [activeTab, setActiveTab] = useState<CapabilityKey>("intake");

  const activeCapability = useMemo(
    () => capabilityTabs.find((item) => item.key === activeTab) ?? capabilityTabs[0],
    [activeTab],
  );

  return (
    <section className="page page--home">
      <div className="hero hero--landing">
        <div className="hero__announcement hero__announcement--soft">
          <span className="hero__announcement-tag">LarkFlow</span>
          <span>统一需求进入、执行控制和运行观测，让交付链路更像一款对外可用的平台产品</span>
        </div>
        <div className="landing-hero__body">
          <p className="landing-hero__eyebrow">LarkFlow Open Delivery Platform</p>
          <div className="landing-hero__titlewrap">
            <h2 className="landing-hero__title">让需求流转、执行控制和运行观测更加高效</h2>
          </div>
          <p className="landing-hero__summary">
            LarkFlow 把飞书需求入口、审批节点、Agent 执行和运行指标组织进一套清爽的前端体验
          </p>
          <div className="landing-hero__actions">
            <Link className="button" to="/pipelines">
              立即体验
            </Link>
            <Link className="button--ghost" to="/dashboard">
              查看运行观测
            </Link>
          </div>
        </div>
      </div>

      <section className="landing-tabs" aria-label="Capability tabs">
        <div className="landing-tabs__rail">
          {capabilityTabs.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`landing-tabs__item${activeCapability.key === item.key ? " landing-tabs__item--active" : ""}`}
              onClick={() => setActiveTab(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </section>

      <section id="platform-entry" className="landing-showcase">
        <div className="landing-showcase__copy">
          <div className="landing-showcase__metric">
            <div className="landing-showcase__metric-value">{activeCapability.metric}</div>
            <p className="muted">{activeCapability.metricLabel}</p>
          </div>

          <div className="landing-showcase__intro">
            <h3>{activeCapability.headline}</h3>
            <p className="muted">{activeCapability.summary}</p>
          </div>

          <div className="landing-card-grid">
            {activeCapability.cards.map((card) => (
              <article key={card.title} className="landing-card">
                <strong>{card.title}</strong>
                <p className="muted">{card.desc}</p>
              </article>
            ))}
          </div>
        </div>

        <aside className="landing-showcase__preview">
          <div className="preview-board">
            <div className="preview-board__top">
              <div>
                <p className="eyebrow">{activeCapability.previewEyebrow}</p>
                <h3>{activeCapability.previewTitle}</h3>
              </div>
              <span className="preview-board__pill">{activeCapability.label}</span>
            </div>
            <p className="muted preview-board__tone">{activeCapability.previewTone}</p>
            <PreviewPanel capability={activeCapability} />
          </div>
        </aside>
      </section>
    </section>
  );
}
