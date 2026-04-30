import { useState } from "react";

import { createPipeline } from "../lib/api";
import { disablePicker, enablePicker } from "./overlay";
import { locate, type Locator } from "./locator";

type Phase = "idle" | "picking" | "selected" | "sending" | "done" | "error";

export function PickerPanel() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [locator, setLocator] = useState<Locator | null>(null);
  const [intent, setIntent] = useState("");
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  function start() {
    setPhase("picking");
    setLocator(null);
    setIntent("");
    setCreatedId(null);
    setErrMsg(null);
    enablePicker({
      onPick: (el) => {
        setLocator(locate(el));
        setPhase("selected");
        disablePicker();
      },
      onCancel: () => {
        disablePicker();
        setPhase("idle");
      },
    });
  }

  function cancel() {
    disablePicker();
    setPhase("idle");
  }

  async function submit() {
    if (!locator || !intent.trim()) return;
    setPhase("sending");
    setErrMsg(null);
    const requirement = [
      "【前端圈选改动请求】",
      `目标元素：<${locator.tag}>${locator.text ? ` "${locator.text}"` : ""}`,
      locator.larkSrc ? `源码位置：${locator.larkSrc}` : `CSS 定位：${locator.cssSelector}`,
      `期望修改：${intent.trim()}`,
    ].join("\n");
    try {
      const created = await createPipeline(requirement, "feature");
      setCreatedId(created.id);
      setPhase("done");
    } catch (err) {
      setErrMsg((err as Error).message);
      setPhase("error");
    }
  }

  const isPanelOpen = phase !== "idle";

  return (
    <div data-lark-picker-root>
      <button
        type="button"
        className={phase === "picking" ? "button" : "button--ghost"}
        onClick={phase === "picking" ? cancel : start}
        style={{ width: "100%", marginTop: 12 }}
      >
        {phase === "picking" ? "取消圈选（Esc）" : "🎯 圈选改页面"}
      </button>

      {isPanelOpen && phase !== "picking" ? (
        <div
          className="panel"
          style={{
            position: "fixed",
            right: 24,
            bottom: 24,
            width: 360,
            zIndex: 2147483647,
            boxShadow: "0 12px 32px rgba(0,0,0,0.18)",
          }}
        >
          <p className="eyebrow">Picker Intent</p>
          <h3>告诉 Agent 要改什么</h3>

          {locator ? (
            <table style={{ fontSize: 12 }}>
              <tbody>
                <tr>
                  <th>Tag</th>
                  <td>{locator.tag}</td>
                </tr>
                {locator.larkSrc ? (
                  <tr>
                    <th>源码</th>
                    <td style={{ fontFamily: "monospace" }}>{locator.larkSrc}</td>
                  </tr>
                ) : (
                  <tr>
                    <th>CSS</th>
                    <td style={{ fontFamily: "monospace", wordBreak: "break-all" }}>
                      {locator.cssSelector}
                    </td>
                  </tr>
                )}
                {locator.text ? (
                  <tr>
                    <th>文本</th>
                    <td>{locator.text}</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          ) : null}

          <textarea
            className="input"
            rows={3}
            placeholder="例如：这个按钮改成蓝色 / 文案改成 XXX"
            value={intent}
            onChange={(ev) => setIntent(ev.target.value)}
            style={{ width: "100%", marginTop: 8 }}
            disabled={phase === "sending"}
          />

          {phase === "done" && createdId ? (
            <p className="flash-note">
              已创建 pipeline <code>{createdId}</code>，到 Pipelines 列表完成 Design HITL。
            </p>
          ) : null}
          {phase === "error" ? (
            <p className="flash-note" style={{ color: "crimson", borderColor: "crimson" }}>
              创建失败：{errMsg}
            </p>
          ) : null}

          <div className="button-row" style={{ marginTop: 8 }}>
            <button
              type="button"
              className="button"
              onClick={submit}
              disabled={!intent.trim() || phase === "sending"}
            >
              {phase === "sending" ? "发送中…" : "发起 pipeline"}
            </button>
            <button type="button" className="button--ghost" onClick={cancel}>
              关闭
            </button>
          </div>
          {!locator?.larkSrc ? (
            <p className="muted" style={{ fontSize: 11, marginTop: 6 }}>
              提示：没有拿到 data-lark-src，说明 Vite dev 模式未启用；Agent 将按 CSS selector 定位。
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
