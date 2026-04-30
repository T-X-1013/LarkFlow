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

export function locate(el: Element): Locator {
  const src = (el as HTMLElement).dataset?.larkSrc;
  const text = (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 120);
  return {
    larkSrc: src,
    cssSelector: buildSelector(el),
    tag: el.tagName.toLowerCase(),
    text,
  };
}
