/**
 * 圈选 overlay：鼠标悬停时高亮 DOM 元素，点击回调选中，Esc 退出。
 * 与 React 解耦，任意页面都能用。
 */

const OVERLAY_ID = "__lark-picker-outline__";
const PANEL_SELECTOR = "[data-lark-picker-root]";

let active = false;
let currentTarget: Element | null = null;
let onPick: ((el: Element) => void) | null = null;
let onCancel: (() => void) | null = null;

function ensureOutline(): HTMLDivElement {
  let el = document.getElementById(OVERLAY_ID) as HTMLDivElement | null;
  if (el) return el;
  el = document.createElement("div");
  el.id = OVERLAY_ID;
  Object.assign(el.style, {
    position: "fixed",
    pointerEvents: "none",
    border: "2px solid #ff4d4f",
    background: "rgba(255, 77, 79, 0.08)",
    zIndex: "2147483646",
    transition: "all 60ms linear",
    borderRadius: "4px",
    display: "none",
  });
  document.body.appendChild(el);
  return el;
}

function positionOutline(el: Element) {
  const outline = ensureOutline();
  const r = el.getBoundingClientRect();
  outline.style.display = "block";
  outline.style.left = `${r.left}px`;
  outline.style.top = `${r.top}px`;
  outline.style.width = `${r.width}px`;
  outline.style.height = `${r.height}px`;
}

function hideOutline() {
  const el = document.getElementById(OVERLAY_ID);
  if (el) (el as HTMLElement).style.display = "none";
}

function inPickerPanel(el: Element | null): boolean {
  if (!el) return false;
  return !!(el as HTMLElement).closest(PANEL_SELECTOR);
}

function handleMouseMove(ev: MouseEvent) {
  if (!active) return;
  const t = ev.target as Element;
  if (inPickerPanel(t)) {
    hideOutline();
    currentTarget = null;
    return;
  }
  currentTarget = t;
  positionOutline(t);
}

function handleClick(ev: MouseEvent) {
  if (!active) return;
  const t = ev.target as Element;
  if (inPickerPanel(t)) return; // 让 panel 自己处理点击
  ev.preventDefault();
  ev.stopPropagation();
  if (currentTarget && onPick) onPick(currentTarget);
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
  ensureOutline();
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
  document.body.style.cursor = "";
  hideOutline();
  document.removeEventListener("mousemove", handleMouseMove, true);
  document.removeEventListener("click", handleClick, true);
  document.removeEventListener("keydown", handleKey, true);
}
