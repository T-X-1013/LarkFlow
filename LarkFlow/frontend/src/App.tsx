import type { ReactNode } from "react";
import {
  NavLink,
  RouterProvider,
  createBrowserRouter,
  useLocation,
} from "react-router-dom";

import { DashboardPage } from "./pages/DashboardPage";
import { HomePage } from "./pages/HomePage";
import { PipelineDetailPage } from "./pages/PipelineDetailPage";
import { PipelinesPage } from "./pages/PipelinesPage";
import { PickerPanel } from "./picker/PickerPanel";

function LayoutOutlet({ children }: { children: ReactNode }) {
  const location = useLocation();
  const isHome = location.pathname === "/";
  const routeMeta =
    isHome
      ? {
          title: "Platform Overview",
          description: "用产品首页的方式呈现 LarkFlow 的能力结构与平台定位。",
          spotlight: "首页承担产品认知与入口分发",
        }
      : location.pathname === "/pipelines"
        ? {
            title: "Pipeline Operations",
            description: "统一完成需求筛选、创建、状态追踪与详情跳转。",
            spotlight: "列表页承担执行入口与状态定位",
          }
        : location.pathname === "/dashboard"
          ? {
              title: "Observability",
              description: "集中查看运行时指标、Provider 分布与 role 级 token 消耗。",
              spotlight: "观测页承接运行时数据解释",
            }
          : {
              title: "Pipeline Runtime",
              description: "查看单条需求的阶段状态、审批节点、产物预览与运行控制。",
              spotlight: "详情页承担控制动作与交付检查",
            };

  return (
    <div className="shell">
      <div className="shell__main">
        <header className="topbar">
          <div className="topbar__row">
            <div className="topbar__brandwrap">
              <div className="brand">
                <div className="brand__mark">LF</div>
                <div>
                  <p className="eyebrow">企业级 Agent 交付平台前端</p>
                  <h1>LarkFlow</h1>
                </div>
              </div>
            </div>
            <nav className="topnav" aria-label="Global sections">
              <NavLink to="/" end className="topnav__item">
                首页
              </NavLink>
              <NavLink to="/pipelines" className="topnav__item">
                执行控制
              </NavLink>
              <NavLink to="/dashboard" className="topnav__item">
                运行观测
              </NavLink>
              <NavLink to="/pipelines" className="topnav__cta">
                立即体验
              </NavLink>
            </nav>
          </div>
        </header>
        <main className="content">{children}</main>
      </div>
      <PickerPanel />
    </div>
  );
}

const router = createBrowserRouter([
  {
    path: "/",
    element: (
      <LayoutOutlet>
        <HomePage />
      </LayoutOutlet>
    ),
  },
  {
    path: "/pipelines",
    element: (
      <LayoutOutlet>
        <PipelinesPage />
      </LayoutOutlet>
    ),
  },
  {
    path: "/pipelines/:pipelineId",
    element: (
      <LayoutOutlet>
        <PipelineDetailPage />
      </LayoutOutlet>
    ),
  },
  {
    path: "/dashboard",
    element: (
      <LayoutOutlet>
        <DashboardPage />
      </LayoutOutlet>
    ),
  },
]);

export function App() {
  return <RouterProvider router={router} />;
}
