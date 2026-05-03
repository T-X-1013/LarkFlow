/**
 * DOM 元素 → 稳定定位信息。
 * 优先取 Vite 插件注入的 data-lark-src（带文件:行:列），
 * 退化为 CSS selector + 可见文本，供 Agent 反查修改点。
 */

export interface Locator {
  /** 形如 "src/pages/Foo.tsx:42:10"；没有就是插件未启用（生产构建）。 */
  larkSrc?: string;
  /** 稳定的 CSS selector，最多 5 层。 */
  cssSelector: string;
  /** 标签名（lowercase）。 */
  tag: string;
  /** 可见文本（最多 120 字），截断防止需求描述过长。 */
  text: string;
  /** 当前页面 path，用于帮助 Agent 缩小组件范围。 */
  pagePath: string;
  /** 元素 id；有则优先展示。 */
  id: string;
  /** 去重后的 className，方便人读和 Agent 反查。 */
  className: string;
  /** 选中元素在当前视口中的位置，用于后续选区回显。 */
  rect: {
    top: number;
    left: number;
    width: number;
    height: number;
  };
  /** 邻近上下文，用于理解“前面那段 / 后面那段”这类相对描述。 */
  context: {
    previous: LocatorContextNode | null;
    next: LocatorContextNode | null;
    parent: LocatorContextNode | null;
  };
  /** 显式参照目标，用于“和‘主任务’一致”这类命名参照。 */
  reference: LocatorContextNode | null;
}

export interface LocatorStyleSnapshot {
  color: string;
  backgroundColor: string;
  fontSize: string;
  fontWeight: string;
}

export interface LocatorContextNode {
  relation: "previous" | "next" | "parent" | "reference";
  tag: string;
  text: string;
  cssSelector: string;
  id: string;
  className: string;
  style: LocatorStyleSnapshot;
}

function nthOfType(el: Element): number {
  const parent = el.parentElement;
  if (!parent) return 1;
  const same = Array.from(parent.children).filter((c) => c.tagName === el.tagName);
  return same.indexOf(el) + 1;
}

function buildSelector(el: Element): string {
  const path: string[] = [];
  let cur: Element | null = el;
  for (let depth = 0; cur && depth < 5; depth += 1) {
    const tag = cur.tagName.toLowerCase();
    if (cur.id) {
      path.unshift(`${tag}#${cur.id}`);
      break;
    }
    const idx = nthOfType(cur);
    path.unshift(`${tag}:nth-of-type(${idx})`);
    cur = cur.parentElement;
    if (cur && cur.tagName === "BODY") break;
  }
  return path.join(" > ");
}

function getStyleSnapshot(node: HTMLElement): LocatorStyleSnapshot {
  const style = window.getComputedStyle(node);
  return {
    color: style.color,
    backgroundColor: style.backgroundColor,
    fontSize: style.fontSize,
    fontWeight: style.fontWeight,
  };
}

function buildContextNode(el: Element, relation: LocatorContextNode["relation"]): LocatorContextNode | null {
  const node = el as HTMLElement;
  const text = (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 120);
  if (!text) return null;
  return {
    relation,
    tag: el.tagName.toLowerCase(),
    text,
    cssSelector: buildSelector(el),
    id: node.id ?? "",
    className: Array.from(node.classList).filter(Boolean).join(" "),
    style: getStyleSnapshot(node),
  };
}

function normalizeText(text: string): string {
  return text.trim().replace(/\s+/g, " ");
}

function extractQuotedReference(intent: string): string | null {
  const match = intent.match(/[“"]([^“”"]+)[”"]/);
  return match ? normalizeText(match[1]) : null;
}

export function findReferenceNode(intent: string, selectedEl: Element): LocatorContextNode | null {
  const refText = extractQuotedReference(intent);
  if (!refText) return null;

  const elements = Array.from(document.querySelectorAll("body *"));
  for (const el of elements) {
    if (el === selectedEl) continue;
    const node = el as HTMLElement;
    if (node.closest("[data-lark-picker-root]")) continue;
    const text = normalizeText(el.textContent ?? "");
    if (!text || text !== refText) continue;
    const refNode = buildContextNode(el, "reference");
    if (refNode) return refNode;
  }
  return null;
}

function findSiblingContext(
  el: Element,
  relation: "previous" | "next",
): LocatorContextNode | null {
  let sibling: Element | null =
    relation === "previous" ? el.previousElementSibling : el.nextElementSibling;
  while (sibling) {
    const candidate = buildContextNode(sibling, relation);
    if (candidate) return candidate;
    sibling = relation === "previous" ? sibling.previousElementSibling : sibling.nextElementSibling;
  }
  return null;
}

export function locate(el: Element): Locator {
  const node = el as HTMLElement;
  const src = node.dataset?.larkSrc;
  const text = (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 120);
  const rect = el.getBoundingClientRect();
  const classes = Array.from(node.classList).filter(Boolean).join(" ");
  const parentContext = node.parentElement ? buildContextNode(node.parentElement, "parent") : null;
  return {
    larkSrc: src,
    cssSelector: buildSelector(el),
    tag: el.tagName.toLowerCase(),
    text,
    pagePath: `${window.location.pathname}${window.location.search}${window.location.hash}`,
    id: node.id ?? "",
    className: classes,
    rect: {
      top: Math.round(rect.top),
      left: Math.round(rect.left),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    },
    context: {
      previous: findSiblingContext(el, "previous"),
      next: findSiblingContext(el, "next"),
      parent: parentContext,
    },
    reference: null,
  };
}
