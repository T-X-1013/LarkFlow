/**
 * Babel 插件：把 JSX 的源码位置注入为 DOM 属性 data-lark-src="<path>:<line>:<col>"。
 * 对原生标签和会向下透传 data-* 属性的 JSX 组件都注入，方便圈选模式定位到源码。
 * 由 @vitejs/plugin-react 的 babel.plugins 引用，仅在 dev mode 开启以免污染生产 bundle。
 */
import type { PluginObj, PluginPass } from "@babel/core";
import type * as BabelTypes from "@babel/types";
import path from "node:path";

export default function larkSrcPlugin({ types: t }: { types: typeof BabelTypes }): PluginObj<PluginPass> {
  const cwd = process.cwd();
  return {
    name: "lark-src",
    visitor: {
      JSXOpeningElement(nodePath, state) {
        const name = nodePath.node.name;
        if (name.type !== "JSXIdentifier") return;
        const loc = nodePath.node.loc;
        if (!loc) return;
        const already = nodePath.node.attributes.some(
          (a) => a.type === "JSXAttribute" && a.name.type === "JSXIdentifier" && a.name.name === "data-lark-src",
        );
        if (already) return;
        const file = state.filename ? path.relative(cwd, state.filename) : "?";
        const value = `${file}:${loc.start.line}:${loc.start.column}`;
        nodePath.node.attributes.push(
          t.jsxAttribute(t.jsxIdentifier("data-lark-src"), t.stringLiteral(value)),
        );
      },
    },
  };
}
