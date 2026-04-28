import type { ReactNode } from "react";
import { NavLink, RouterProvider, createBrowserRouter } from "react-router-dom";

import { DashboardPage } from "./pages/DashboardPage";
import { HomePage } from "./pages/HomePage";
import { PipelineDetailPage } from "./pages/PipelineDetailPage";
import { PipelinesPage } from "./pages/PipelinesPage";

function LayoutOutlet({ children }: { children: ReactNode }) {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand__mark">LF</div>
          <div>
            <p className="eyebrow">Control Plane</p>
            <h1>LarkFlow</h1>
          </div>
        </div>
        <nav className="nav">
          <NavLink to="/" end className="nav__item">
            首页
          </NavLink>
          <NavLink to="/pipelines" className="nav__item">
            Pipelines
          </NavLink>
          <NavLink to="/dashboard" className="nav__item">
            仪表盘
          </NavLink>
        </nav>
      </aside>
      <main className="content">{children}</main>
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
