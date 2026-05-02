/**
 * 圈选 overlay：鼠标悬停时高亮 DOM 元素，点击回调选中，Esc 退出。
 * 与 React 解耦，任意页面都能用。
 */

const HOVER_OUTLINE_ID = "__lark-picker-hover-outline__";
const SELECTED_OUTLINE_ID = "__lark-picker-selected-outline__";
const PANEL_SELECTOR = "[data-lark-picker-root]";

let active = false;
let currentTarget: Element | null = null;
let selectedTarget: Element | null = null;
let onPick: ((el: Element) => void) | null = null;
let onCancel: (() => void) | null = null;

function ensureOutline(id: string, style: Partial<CSSStyleDeclaration>): HTMLDivElement {
  let el = document.getElementById(id) as HTMLDivElement | null;
  if (el) return el;
  el = document.createElement("div");
  el.id = id;
  Object.assign(el.style, {
    position: "fixed",
    pointerEvents: "none",
    zIndex: "2147483646",
    transition: "all 60ms linear",
    borderRadius: "4px",
    display: "none",
    ...style,
  });
  document.body.appendChild(el);
  return el;
}

function ensureHoverOutline(): HTMLDivElement {
  return ensureOutline(HOVER_OUTLINE_ID, {
    border: "2px dashed #ff4d4f",
    background: "rgba(255, 77, 79, 0.06)",
  });
}

function ensureSelectedOutline(): HTMLDivElement {
  return ensureOutline(SELECTED_OUTLINE_ID, {
    border: "2px solid #ff4d4f",
    background: "rgba(255, 77, 79, 0.12)",
  });
}

function positionOutline(outline: HTMLDivElement, el: Element) {
  const r = el.getBoundingClientRect();
  outline.style.display = "block";
  outline.style.left = `${r.left}px`;
  outline.style.top = `${r.top}px`;
  outline.style.width = `${r.width}px`;
  outline.style.height = `${r.height}px`;
}

function hideOutline(id: string) {
  const el = document.getElementById(id);
  if (el) (el as HTMLElement).style.display = "none";
}

function syncSelectedOutline() {
  if (!selectedTarget) {
    hideOutline(SELECTED_OUTLINE_ID);
    return;
  }
  positionOutline(ensureSelectedOutline(), selectedTarget);
}

function inPickerPanel(el: Element | null): boolean {
  if (!el) return false;
  return !!(el as HTMLElement).closest(PANEL_SELECTOR);
}

function handleMouseMove(ev: MouseEvent) {
  if (!active) return;
  const t = ev.target as Element;
  if (inPickerPanel(t)) {
    hideOutline(HOVER_OUTLINE_ID);
    currentTarget = null;
    return;
  }
  currentTarget = t;
  positionOutline(ensureHoverOutline(), t);
}

function handleClick(ev: MouseEvent) {
  if (!active) return;
  const t = ev.target as Element;
  if (inPickerPanel(t)) return; // 让 panel 自己处理点击
  ev.preventDefault();
  ev.stopPropagation();
  if (currentTarget) {
    selectedTarget = currentTarget;
    syncSelectedOutline();
    if (onPick) onPick(currentTarget);
  }
}

function handleKey(ev: KeyboardEvent) {
  if (!active) return;
  if (ev.key === "Escape") {
    ev.preventDefault();
    if (onCancel) onCancel();
  }
}

export function enablePicker(handlers: {
  onPick: (el: Element) => void;
  onCancel: () => void;
}) {
  active = true;
  onPick = handlers.onPick;
  onCancel = handlers.onCancel;
  ensureHoverOutline();
  syncSelectedOutline();
  document.body.style.cursor = "crosshair";
  document.addEventListener("mousemove", handleMouseMove, true);
  document.addEventListener("click", handleClick, true);
  document.addEventListener("keydown", handleKey, true);
}

export function disablePicker() {
  active = false;
  onPick = null;
  onCancel = null;
  currentTarget = null;
  selectedTarget = null;
  document.body.style.cursor = "";
  hideOutline(HOVER_OUTLINE_ID);
  hideOutline(SELECTED_OUTLINE_ID);
  document.removeEventListener("mousemove", handleMouseMove, true);
  document.removeEventListener("click", handleClick, true);
  document.removeEventListener("keydown", handleKey, true);
}
