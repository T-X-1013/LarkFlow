import { Link } from "react-router-dom";

export function HomePage() {
  return (
    <section className="page">
      <div className="hero">
        <p className="eyebrow">Sprint Console</p>
        <h2>把飞书需求、Pipeline 生命周期和人工审批放进一个界面里。</h2>
        <p className="muted">
          当前前端已经按冻结契约统一走 HTTP API；开发态可通过 `MSW` 开关回退到 mock
          数据源，真实联调和演示页共用同一套控制台结构。
        </p>
        <div className="hero__grid">
          <div className="stat-card">
            <p className="eyebrow">主任务</p>
            <div className="stat-card__value">Pipelines</div>
            <p className="muted">列表、详情、审批与运行态操作都从这里展开。</p>
          </div>
          <div className="stat-card">
            <p className="eyebrow">运行时</p>
            <div className="stat-card__value">Provider</div>
            <p className="muted">为后续 set_provider 接线预留页面入口与状态展示位。</p>
          </div>
          <div className="stat-card">
            <p className="eyebrow">观测</p>
            <div className="stat-card__value">Metrics</div>
            <p className="muted">承接 token、duration、重试等埋点，方便接后端聚合。</p>
          </div>
        </div>
        <div className="button-row">
          <Link className="button" to="/pipelines">
            进入 Pipeline 列表
          </Link>
          <Link className="button--ghost" to="/dashboard">
            查看仪表盘
          </Link>
        </div>
      </div>

      <div className="details-grid">
        <div className="panel">
          <p className="eyebrow">What is ready</p>
          <h3>当前已经具备的页面能力</h3>
          <div className="timeline">
            <div className="timeline__item">
              <strong>列表页</strong>
              <p className="muted">按状态、Provider 和关键词筛选 mock Pipeline，并从这里进入详情页。</p>
            </div>
            <div className="timeline__item">
              <strong>详情页</strong>
              <p className="muted">查看阶段产物、审批点、token、duration，并演示运行态操作与 Provider 切换。</p>
            </div>
            <div className="timeline__item">
              <strong>仪表盘</strong>
              <p className="muted">展示 duration、token 和状态 / Provider 分布，为真实指标聚合预留结构。</p>
            </div>
          </div>
        </div>
        <div className="panel">
          <p className="eyebrow">Next wiring</p>
          <h3>后续真实联调顺序</h3>
          <table>
            <tbody>
              <tr>
                <th>1</th>
                <td>
                  先读 <code>GET /metrics/pipelines</code>，再补 <code>GET /pipelines/:id</code>
                  明细
                </td>
              </tr>
              <tr>
                <th>2</th>
                <td>
                  接入 <code>PUT /pipelines/:id/provider</code>，把 Provider 切换从 mock
                  变成真实状态变更
                </td>
              </tr>
              <tr>
                <th>3</th>
                <td>对接 artifact 与 checkpoint approve/reject 页面动作</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
