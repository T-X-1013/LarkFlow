import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";
import { shouldUseMsw } from "./lib/api";
import "./styles.css";

async function bootstrap() {
  if (shouldUseMsw()) {
    const { worker } = await import("./mocks/browser");
    await worker.start({
      onUnhandledRequest: "bypass",
    });
  }

  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}

bootstrap();
