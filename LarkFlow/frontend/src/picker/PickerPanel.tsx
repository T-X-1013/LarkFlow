import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";

import {
  cancelVisualEdit,
  commitVisualEdit,
  confirmVisualEdit,
  createVisualEditPreview,
  getVisualEditSession,
  getVisualEditDeliveryCheck,
  prepareVisualEditCommit,
} from "../lib/api";
import type {
  VisualEditCommitPlan,
  VisualEditCommitResult,
  VisualEditDeliveryCheck,
  VisualEditPreviewRequest,
  VisualEditSession,
} from "../types/api";
import { disablePicker, enablePicker } from "./overlay";
import { findReferenceNode, locate, type Locator } from "./locator";

type Phase =
  | "idle"
  | "picking"
  | "selected"
  | "preview_generating"
  | "preview_ready"
  | "confirming"
  | "cancelling"
  | "confirmed"
  | "cancelled"
  | "error";
type PanelPosition = { left: number; top: number };

const PANEL_MARGIN = 24;
const PANEL_MAX_WIDTH = 420;
const PANEL_MIN_VIEWPORT_GAP = 32;
const ACTIVE_SESSION_STORAGE_KEY = "larkflow.visual-edit.active-session";

function describeLocator(locator: Locator): string {
  if (locator.text) {
    return `已选中：${locator.text}`;
  }
  if (locator.className) {
    return `已选中：.${locator.className.split(" ")[0]}`;
  }
  if (locator.id) {
    return `已选中：#${locator.id}`;
  }
  return `已选中一个 <${locator.tag}> 元素`;
}

function buildVisualEditRequest(locator: Locator, intent: string): string {
  const rect = locator.rect ?? { left: 0, top: 0, width: 0, height: 0 };
  const previous = locator.context.previous;
  const next = locator.context.next;
  const reference = locator.reference;
  const lines = [
    "【Visual Edit Request】",
    `page_url: ${window.location.href}`,
    `page_path: ${locator.pagePath || window.location.pathname}`,
    "target:",
    `  lark_src: ${locator.larkSrc ?? ""}`,
    `  css_selector: ${locator.cssSelector}`,
    `  tag: ${locator.tag}`,
    `  id: ${locator.id ?? ""}`,
    `  class_name: ${locator.className ?? ""}`,
    `  text: ${locator.text ?? ""}`,
    "  rect:",
    `    left: ${rect.left}`,
    `    top: ${rect.top}`,
    `    width: ${rect.width}`,
    `    height: ${rect.height}`,
    "context:",
    `  previous_text: ${previous?.text ?? ""}`,
    `  previous_color: ${previous?.style.color ?? ""}`,
    `  next_text: ${next?.text ?? ""}`,
    `  next_color: ${next?.style.color ?? ""}`,
    `  reference_text: ${reference?.text ?? ""}`,
    `  reference_color: ${reference?.style.color ?? ""}`,
    `intent: ${intent.trim()}`,
    "constraints:",
    "  - only edit files under frontend/src",
    "  - keep current layout structure unless the intent explicitly requires layout changes",
    "acceptance:",
    "  - the updated result should be visible in the current page preview",
    "  - do not break existing navigation or unrelated modules",
  ];
  return lines.join("\n");
}

function buildPreviewRequest(locator: Locator, intent: string): VisualEditPreviewRequest {
  return {
    requirement: buildVisualEditRequest(locator, intent),
    page_url: window.location.href,
    page_path: locator.pagePath || window.location.pathname,
    intent: intent.trim(),
    target: {
      lark_src: locator.larkSrc ?? null,
      css_selector: locator.cssSelector,
      tag: locator.tag,
      id: locator.id ?? "",
      class_name: locator.className ?? "",
      text: locator.text ?? "",
      rect: locator.rect ?? null,
      context: {
        previous: locator.context.previous
          ? {
              relation: locator.context.previous.relation,
              tag: locator.context.previous.tag,
              text: locator.context.previous.text,
              css_selector: locator.context.previous.cssSelector,
              id: locator.context.previous.id,
              class_name: locator.context.previous.className,
              style: locator.context.previous.style,
            }
          : null,
        next: locator.context.next
          ? {
              relation: locator.context.next.relation,
              tag: locator.context.next.tag,
              text: locator.context.next.text,
              css_selector: locator.context.next.cssSelector,
              id: locator.context.next.id,
              class_name: locator.context.next.className,
              style: locator.context.next.style,
            }
          : null,
        parent: locator.context.parent
          ? {
              relation: locator.context.parent.relation,
              tag: locator.context.parent.tag,
              text: locator.context.parent.text,
              css_selector: locator.context.parent.cssSelector,
              id: locator.context.parent.id,
              class_name: locator.context.parent.className,
              style: locator.context.parent.style,
            }
          : null,
      },
      reference: locator.reference
        ? {
            relation: locator.reference.relation,
            tag: locator.reference.tag,
            text: locator.reference.text,
            css_selector: locator.reference.cssSelector,
            id: locator.reference.id,
            class_name: locator.reference.className,
            style: locator.reference.style,
          }
        : null,
    },
  };
}

function locatorFromSession(session: VisualEditSession): Locator {
  // 预览会话是后端契约结构，这里把它重新投影成前端 PickerPanel 直接可消费的 Locator。
  return {
    larkSrc: session.target.lark_src ?? undefined,
    cssSelector: session.target.css_selector,
    tag: session.target.tag,
    text: session.target.text,
    pagePath: session.page_path,
    id: session.target.id,
    className: session.target.class_name,
    rect: session.target.rect
      ? {
          top: session.target.rect.top,
          left: session.target.rect.left,
          width: session.target.rect.width,
          height: session.target.rect.height,
        }
      : { top: 0, left: 0, width: 0, height: 0 },
    context: {
      previous: session.target.context?.previous
        ? {
            relation: session.target.context.previous.relation,
            tag: session.target.context.previous.tag,
            text: session.target.context.previous.text,
            cssSelector: session.target.context.previous.css_selector,
            id: session.target.context.previous.id,
            className: session.target.context.previous.class_name,
            style: session.target.context.previous.style,
          }
        : null,
      next: session.target.context?.next
        ? {
            relation: session.target.context.next.relation,
            tag: session.target.context.next.tag,
            text: session.target.context.next.text,
            cssSelector: session.target.context.next.css_selector,
            id: session.target.context.next.id,
            className: session.target.context.next.class_name,
            style: session.target.context.next.style,
          }
        : null,
      parent: session.target.context?.parent
        ? {
            relation: session.target.context.parent.relation,
            tag: session.target.context.parent.tag,
            text: session.target.context.parent.text,
            cssSelector: session.target.context.parent.css_selector,
            id: session.target.context.parent.id,
            className: session.target.context.parent.class_name,
            style: session.target.context.parent.style,
          }
        : null,
    },
    reference: session.target.reference
      ? {
          relation: session.target.reference.relation,
          tag: session.target.reference.tag,
          text: session.target.reference.text,
          cssSelector: session.target.reference.css_selector,
          id: session.target.reference.id,
          className: session.target.reference.class_name,
          style: session.target.reference.style,
        }
      : null,
  };
}

export function PickerPanel() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [locator, setLocator] = useState<Locator | null>(null);
  const [intent, setIntent] = useState("");
  const [session, setSession] = useState<VisualEditSession | null>(null);
  const [deliveryCheck, setDeliveryCheck] = useState<VisualEditDeliveryCheck | null>(null);
  const [commitPlan, setCommitPlan] = useState<VisualEditCommitPlan | null>(null);
  const [commitResult, setCommitResult] = useState<VisualEditCommitResult | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const [panelPosition, setPanelPosition] = useState<PanelPosition | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ pointerId: number; offsetX: number; offsetY: number } | null>(null);
  const selectedElementRef = useRef<Element | null>(null);
  const phaseRef = useRef<Phase>("idle");
  const sessionRef = useRef<VisualEditSession | null>(null);

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  useEffect(() => {
    if (typeof window === "undefined") return;

    async function restoreSession() {
      const savedSessionId = window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
      if (!savedSessionId) return;
      try {
        const restored = await getVisualEditSession(savedSessionId);
        if (restored.page_path !== `${window.location.pathname}${window.location.search}${window.location.hash}`) {
          window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
          return;
        }
        // 已取消/失败的会话不再恢复，避免页面重进时重新展示过期面板状态。
        if (restored.status === "cancelled" || restored.status === "failed") {
          window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
          return;
        }
        setSession(restored);
        setLocator(locatorFromSession(restored));
        setIntent(restored.intent);
        setErrMsg(null);
        if (restored.status === "confirmed") {
          setPhase("confirmed");
          const [check, plan] = await Promise.all([
            getVisualEditDeliveryCheck(restored.id).catch(() => null),
            prepareVisualEditCommit(restored.id).catch(() => null),
          ]);
          setDeliveryCheck(check);
          setCommitPlan(plan);
        } else {
          setPhase("preview_ready");
        }
      } catch {
        window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
      }
    }

    void restoreSession();
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;

    if (session && (phase === "preview_ready" || phase === "confirmed")) {
      // 只有用户还能继续操作的会话才需要写入本地，供刷新后恢复面板状态。
      window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, session.id);
      return;
    }
    if (phase === "cancelled" || phase === "idle" || phase === "error" || !session) {
      window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
    }
  }, [phase, session]);

  useEffect(() => {
    if (typeof window === "undefined") return;

    function abandonPendingPreview() {
      const activeSession = sessionRef.current;
      if (!activeSession) return;
      if (phaseRef.current !== "preview_ready") return;
      window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
      // 未确认预览本质上已经改了源码；页面离开时主动回滚，避免“刷新后临时改动还留着”。
      fetch(`/visual-edits/${activeSession.id}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        keepalive: true,
      }).catch(() => undefined);
    }

    window.addEventListener("pagehide", abandonPendingPreview);
    window.addEventListener("beforeunload", abandonPendingPreview);
    return () => {
      window.removeEventListener("pagehide", abandonPendingPreview);
      window.removeEventListener("beforeunload", abandonPendingPreview);
    };
  }, []);

  function applyPickedElement(el: Element) {
    if (
      phaseRef.current === "preview_generating" ||
      phaseRef.current === "preview_ready" ||
      phaseRef.current === "confirming" ||
      phaseRef.current === "cancelling"
    ) {
      return;
    }
    selectedElementRef.current = el;
    setLocator(locate(el));
    setSession(null);
    setDeliveryCheck(null);
    setCommitPlan(null);
    setCommitResult(null);
    setErrMsg(null);
    setPhase("selected");
  }

  function clampPanelPosition(left: number, top: number): PanelPosition {
    if (typeof window === "undefined") return { left, top };
    const width =
      panelRef.current?.getBoundingClientRect().width ??
      Math.min(PANEL_MAX_WIDTH, window.innerWidth - PANEL_MIN_VIEWPORT_GAP);
    const height = panelRef.current?.getBoundingClientRect().height ?? 480;
    const maxLeft = Math.max(PANEL_MARGIN, window.innerWidth - width - PANEL_MARGIN);
    const maxTop = Math.max(PANEL_MARGIN, window.innerHeight - height - PANEL_MARGIN);
    return {
      left: Math.min(Math.max(PANEL_MARGIN, left), maxLeft),
      top: Math.min(Math.max(PANEL_MARGIN, top), maxTop),
    };
  }

  function start() {
    setPhase("picking");
    setLocator(null);
    setIntent("");
    setSession(null);
    setDeliveryCheck(null);
    setCommitPlan(null);
    setCommitResult(null);
    setErrMsg(null);
    setPanelPosition(null);
    enablePicker({
      onPick: applyPickedElement,
      onCancel: () => {
        disablePicker();
        setPhase("idle");
      },
    });
  }

  function cancel() {
    disablePicker();
    setPhase("idle");
    setPanelPosition(null);
  }

  async function submitPreview() {
    if (!locator || !intent.trim()) return;
    setPhase("preview_generating");
    setErrMsg(null);
    try {
      const enrichedLocator = {
        ...locator,
        reference: selectedElementRef.current
          ? findReferenceNode(intent, selectedElementRef.current)
          : null,
      };
      setLocator(enrichedLocator);
      const nextSession = await createVisualEditPreview(buildPreviewRequest(enrichedLocator, intent));
      setSession(nextSession);
      setPhase("preview_ready");
    } catch (err) {
      setErrMsg((err as Error).message);
      setPhase("error");
    }
  }

  async function confirmPreview() {
    if (!session) return;
    setPhase("confirming");
    setErrMsg(null);
    try {
      const confirmed = await confirmVisualEdit(session.id);
      setSession(confirmed);
      const check = await getVisualEditDeliveryCheck(confirmed.id);
      setDeliveryCheck(check);
      const plan = await prepareVisualEditCommit(confirmed.id);
      setCommitPlan(plan);
      setPhase("confirmed");
    } catch (err) {
      setErrMsg((err as Error).message);
      setPhase("error");
    }
  }

  async function rollbackPreview() {
    if (!session) return;
    setPhase("cancelling");
    setErrMsg(null);
    try {
      const cancelled = await cancelVisualEdit(session.id);
      setSession(cancelled);
      setDeliveryCheck(null);
      setCommitPlan(null);
      setCommitResult(null);
      setPhase("cancelled");
    } catch (err) {
      setErrMsg((err as Error).message);
      setPhase("error");
    }
  }

  async function createCommit() {
    if (!session) return;
    setErrMsg(null);
    try {
      const result = await commitVisualEdit(session.id);
      setCommitResult(result);
    } catch (err) {
      setErrMsg((err as Error).message);
      setPhase("error");
    }
  }

  const isPanelOpen = phase !== "idle";
  const showTriggerBubble =
    phase === "idle" ||
    phase === "picking" ||
    phase === "selected" ||
    phase === "confirmed" ||
    phase === "cancelled" ||
    phase === "error";

  useEffect(() => {
    if (!isPanelOpen || phase === "picking" || panelPosition !== null) return;
    if (!panelRef.current) return;
    const rect = panelRef.current.getBoundingClientRect();
    setPanelPosition(clampPanelPosition(rect.left, rect.top));
  }, [isPanelOpen, phase, panelPosition]);

  useEffect(() => {
    if (!isPanelOpen || typeof window === "undefined") return;

    function handleResize() {
      setPanelPosition((current) => {
        if (!current) return current;
        return clampPanelPosition(current.left, current.top);
      });
    }

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [isPanelOpen]);

  useEffect(() => {
    function handlePointerMove(ev: PointerEvent) {
      const drag = dragRef.current;
      if (!drag) return;
      setPanelPosition(clampPanelPosition(ev.clientX - drag.offsetX, ev.clientY - drag.offsetY));
    }

    function handlePointerUp(ev: PointerEvent) {
      const drag = dragRef.current;
      if (!drag || drag.pointerId !== ev.pointerId) return;
      dragRef.current = null;
      document.body.style.userSelect = "";
    }

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);
    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
      document.body.style.userSelect = "";
    };
  }, []);

  function handleDragStart(ev: ReactPointerEvent<HTMLDivElement>) {
    if (!panelRef.current) return;
    const rect = panelRef.current.getBoundingClientRect();
    dragRef.current = {
      pointerId: ev.pointerId,
      offsetX: ev.clientX - rect.left,
      offsetY: ev.clientY - rect.top,
    };
    setPanelPosition(clampPanelPosition(rect.left, rect.top));
    document.body.style.userSelect = "none";
  }

  const isBusy =
    phase === "preview_generating" || phase === "confirming" || phase === "cancelling";
  const detailRect = locator?.rect ?? { left: 0, top: 0, width: 0, height: 0 };

  const floatingPanel =
    isPanelOpen && phase !== "picking" ? (
      <div
        ref={panelRef}
        data-lark-picker-root
        className="panel"
        style={{
          position: "fixed",
          left: panelPosition?.left,
          top: panelPosition?.top,
          right: panelPosition ? "auto" : PANEL_MARGIN,
          bottom: panelPosition ? "auto" : PANEL_MARGIN,
          width: "min(420px, calc(100vw - 32px))",
          maxHeight: "min(70vh, 760px)",
          overflowY: "auto",
          zIndex: 2147483647,
          background: "linear-gradient(180deg, rgba(244, 250, 255, 0.38) 0%, rgba(228, 240, 248, 0.28) 100%)",
          border: "1px solid rgba(101, 150, 184, 0.08)",
          boxShadow: "0 18px 44px rgba(36, 28, 18, 0.08)",
        }}
      >
        <div
          onPointerDown={handleDragStart}
          style={{
            cursor: "grab",
            userSelect: "none",
            marginBottom: 8,
            paddingBottom: 8,
            borderBottom: "1px solid rgba(28, 43, 47, 0.08)",
          }}
        >
          <p className="eyebrow">Picker Intent</p>
          <h3>告诉 Agent 要改什么</h3>
        </div>

        {locator ? (
          <div
            style={{
              marginBottom: 10,
              padding: 14,
              borderRadius: 16,
              background: "rgba(255,255,255,0.22)",
              border: "1px solid rgba(101, 150, 184, 0.08)",
            }}
          >
            <p style={{ margin: 0, fontWeight: 700 }}>{describeLocator(locator)}</p>
          </div>
        ) : null}

        <textarea
          className="input"
          rows={3}
          placeholder="例如：把这里改成蓝色 / 文字改成哈哈哈 / 让这句更像官网文案"
          value={intent}
          onChange={(ev) => setIntent(ev.target.value)}
          style={{ width: "100%", marginTop: 8 }}
          disabled={isBusy || phase === "preview_ready" || phase === "confirmed"}
        />
        <p className="muted" style={{ fontSize: 11, marginTop: 6, marginBottom: 0 }}>
          可以直接描述你想要的文案或颜色效果，Agent 会先理解意图再生成预览。
        </p>

        {phase === "preview_generating" ? (
          <div className="flash-note">
            正在生成预览，页面会在修改写入后立即刷新。
          </div>
        ) : null}
        {phase === "preview_ready" && session ? (
          <div className="flash-note">
            预览已生成 <code>{session.id}</code>，请确认当前页面效果是否符合预期。
          </div>
        ) : null}
        {(phase === "preview_ready" || phase === "confirmed") && session?.resolved_action ? (
          <div
            style={{
              marginTop: 8,
              padding: 12,
              borderRadius: 14,
              background: "rgba(255,255,255,0.18)",
              border: "1px solid rgba(101, 150, 184, 0.08)",
            }}
          >
            <p style={{ margin: "0 0 6px", fontSize: 12, fontWeight: 700 }}>意图解析</p>
            <p className="muted" style={{ margin: "0 0 4px", fontSize: 11 }}>
              来源：{session.resolved_action.source}，动作：{session.resolved_action.kind}
            </p>
            {session.resolved_action.property_name ? (
              <p className="muted" style={{ margin: "0 0 4px", fontSize: 11 }}>
                属性：<code>{session.resolved_action.property_name}</code>
              </p>
            ) : null}
            <p className="muted" style={{ margin: "0 0 4px", fontSize: 11 }}>
              结果：<code>{session.resolved_action.value}</code>
            </p>
            <p className="muted" style={{ margin: 0, fontSize: 11 }}>
              置信度：{session.resolved_action.confidence.toFixed(2)}
            </p>
          </div>
        ) : null}
        {phase === "preview_ready" && session?.diff_summary.length ? (
          <div
            style={{
              marginTop: 8,
              padding: 12,
              borderRadius: 14,
              background: "rgba(255,255,255,0.18)",
              border: "1px solid rgba(101, 150, 184, 0.08)",
            }}
          >
            <p style={{ margin: "0 0 6px", fontSize: 12, fontWeight: 700 }}>本次改动</p>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
              {session.diff_summary.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {phase === "confirmed" && session ? (
          <div className="flash-note">
            已确认本次修改 <code>{session.id}</code>，当前变更会保留在前端源码中。
          </div>
        ) : null}
        {phase === "confirmed" && session?.delivery_summary ? (
          <details
            style={{
              marginTop: 8,
              padding: 12,
              borderRadius: 14,
              background: "rgba(255,255,255,0.18)",
              border: "1px solid rgba(101, 150, 184, 0.08)",
            }}
            open
          >
            <summary style={{ cursor: "pointer", fontSize: 12, fontWeight: 700 }}>
              交付摘要
            </summary>
            <pre
              style={{
                margin: "8px 0 0",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                fontSize: 11,
                lineHeight: 1.5,
              }}
            >
              {session.delivery_summary}
            </pre>
          </details>
        ) : null}
        {phase === "confirmed" && deliveryCheck ? (
          <div
            style={{
              marginTop: 8,
              padding: 12,
              borderRadius: 14,
              background: deliveryCheck.safe_to_commit
                ? "rgba(236, 253, 245, 0.28)"
                : "rgba(255, 247, 237, 0.32)",
              border: deliveryCheck.safe_to_commit
                ? "1px solid rgba(34, 197, 94, 0.14)"
                : "1px solid rgba(249, 115, 22, 0.14)",
            }}
          >
            <p style={{ margin: "0 0 6px", fontSize: 12, fontWeight: 700 }}>
              提交前检查：{deliveryCheck.safe_to_commit ? "可安全提交" : "需要人工确认范围"}
            </p>
            {deliveryCheck.deliverable_files.length ? (
              <p className="muted" style={{ margin: "0 0 4px", fontSize: 11 }}>
                可提交：{deliveryCheck.deliverable_files.join(", ")}
              </p>
            ) : null}
            {deliveryCheck.unrelated_dirty_count > 0 ? (
              <p className="muted" style={{ margin: 0, fontSize: 11 }}>
                当前工作区还有 {deliveryCheck.unrelated_dirty_count} 个其他未提交改动，自动提交前需要人工确认范围。
              </p>
            ) : null}
          </div>
        ) : null}
        {phase === "confirmed" && commitPlan ? (
          <details
            style={{
              marginTop: 8,
              padding: 12,
              borderRadius: 14,
              background: "rgba(255,255,255,0.18)",
              border: "1px solid rgba(101, 150, 184, 0.08)",
            }}
            open
          >
            <summary style={{ cursor: "pointer", fontSize: 12, fontWeight: 700 }}>
              准备提交
            </summary>
            <p className="muted" style={{ margin: "8px 0 4px", fontSize: 11 }}>
              文件范围：{commitPlan.files.length ? commitPlan.files.join(", ") : "暂无可提交文件"}
            </p>
            <p className="muted" style={{ margin: "0 0 4px", fontSize: 11 }}>
              Commit message：<code>{commitPlan.commit_message}</code>
            </p>
            {commitPlan.warnings.length ? (
              <ul style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 11 }}>
                {commitPlan.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : null}
            {commitPlan.safe_to_commit && !commitResult ? (
              <button
                type="button"
                className="button"
                onClick={createCommit}
                style={{ marginTop: 8 }}
              >
                创建提交
              </button>
            ) : null}
          </details>
        ) : null}
        {phase === "confirmed" && commitResult ? (
          <div className="flash-note">
            已创建提交 <code>{commitResult.commit_hash}</code>
          </div>
        ) : null}
        {phase === "cancelled" && session ? (
          <div className="flash-note">
            已取消本次修改 <code>{session.id}</code>，页面已回退到修改前状态。
          </div>
        ) : null}
        {phase === "error" ? (
          <p className="flash-note" style={{ color: "crimson", borderColor: "crimson" }}>
            操作失败：{errMsg}
          </p>
        ) : null}

        <div className="button-row" style={{ marginTop: 8 }}>
          {phase === "preview_ready" ? (
            <>
              <button type="button" className="button" onClick={confirmPreview}>
                确认修改
              </button>
              <button type="button" className="button--ghost" onClick={rollbackPreview}>
                取消修改
              </button>
            </>
          ) : phase === "confirmed" || phase === "cancelled" || phase === "error" ? (
            <button type="button" className="button--ghost" onClick={cancel}>
              关闭
            </button>
          ) : (
            <>
              <button
                type="button"
                className="button"
                onClick={submitPreview}
                disabled={!intent.trim() || isBusy}
              >
                {phase === "preview_generating" ? "生成预览中…" : "修改"}
              </button>
              <button type="button" className="button--ghost" onClick={cancel}>
                关闭
              </button>
            </>
          )}
        </div>
        {locator ? (
          <details
            style={{
              marginTop: 10,
              padding: 12,
              borderRadius: 14,
              background: "rgba(255,255,255,0.14)",
              border: "1px solid rgba(101, 150, 184, 0.08)",
            }}
          >
            <summary style={{ cursor: "pointer", fontWeight: 600 }}>
              定位详情
            </summary>
            <table style={{ fontSize: 12, marginTop: 8 }}>
              <tbody>
                <tr>
                  <th>Tag</th>
                  <td>{locator.tag}</td>
                </tr>
                {locator.pagePath ? (
                  <tr>
                    <th>Page</th>
                    <td style={{ fontFamily: "monospace", wordBreak: "break-all" }}>
                      {locator.pagePath}
                    </td>
                  </tr>
                ) : null}
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
                {locator.id ? (
                  <tr>
                    <th>ID</th>
                    <td style={{ fontFamily: "monospace", wordBreak: "break-all" }}>{locator.id}</td>
                  </tr>
                ) : null}
                {locator.className ? (
                  <tr>
                    <th>Class</th>
                    <td style={{ fontFamily: "monospace", wordBreak: "break-all" }}>
                      {locator.className}
                    </td>
                  </tr>
                ) : null}
                {locator.text ? (
                  <tr>
                    <th>文本</th>
                    <td>{locator.text}</td>
                  </tr>
                ) : null}
                <tr>
                  <th>Rect</th>
                  <td style={{ fontFamily: "monospace" }}>
                    {detailRect.left},{detailRect.top} {detailRect.width}x{detailRect.height}
                  </td>
                </tr>
              </tbody>
            </table>
          </details>
        ) : null}
        {!locator?.larkSrc ? (
          <p className="muted" style={{ fontSize: 11, marginTop: 6 }}>
            提示：当前预览 MVP 依赖 data-lark-src；如果这里为空，请确认 Vite dev 模式已启用。
          </p>
        ) : null}
      </div>
    ) : null;

  const triggerBubble = showTriggerBubble ? (
    <button
      data-lark-picker-root
      type="button"
      aria-label={phase === "idle" || phase === "confirmed" || phase === "cancelled" || phase === "error" ? "开启圈选" : "取消圈选"}
      title={phase === "idle" || phase === "confirmed" || phase === "cancelled" || phase === "error" ? "开启圈选" : "取消圈选（Esc）"}
      onClick={phase === "idle" || phase === "confirmed" || phase === "cancelled" || phase === "error" ? start : cancel}
      style={{
        position: "fixed",
        left: 24,
        bottom: 24,
        zIndex: 2147483647,
        width: phase === "idle" ? 92 : 92,
        height: 58,
        border: "none",
        borderRadius: 999,
        cursor: "pointer",
        color: "white",
        fontWeight: 700,
        letterSpacing: "0.04em",
        background:
          phase === "idle" || phase === "confirmed" || phase === "cancelled" || phase === "error"
            ? "linear-gradient(135deg, rgba(203, 81, 35, 0.5) 0%, rgba(239, 157, 101, 0.5) 100%)"
            : "linear-gradient(135deg, rgba(54, 109, 139, 0.5) 0%, rgba(93, 166, 201, 0.5) 100%)",
        boxShadow:
          phase === "idle" || phase === "confirmed" || phase === "cancelled" || phase === "error"
            ? "0 16px 36px rgba(203, 81, 35, 0.13)"
            : "0 16px 36px rgba(54, 109, 139, 0.14)",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "0 18px",
        transition: "transform 160ms ease, box-shadow 160ms ease, width 160ms ease",
      }}
    >
      {phase === "idle" || phase === "confirmed" || phase === "cancelled" || phase === "error" ? "圈选" : "取消"}
    </button>
  ) : null;

  if (typeof document === "undefined") return null;

  return (
    <>
      {triggerBubble ? createPortal(triggerBubble, document.body) : null}
      {floatingPanel ? createPortal(floatingPanel, document.body) : null}
    </>
  );
}
