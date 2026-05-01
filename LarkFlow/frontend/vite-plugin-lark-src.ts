/**
 * Babel 插件：把 JSX 的源码位置注入为 DOM 属性 data-lark-src="<path>:<line>:<col>"。
 * 只处理 host 元素（lowercase tag），组件不处理。
 * 由 @vitejs/plugin-react 的 babel.plugins 引用，仅在 dev mode 开启以免污染生产 bundle。
 */
import type { PluginObj, PluginPass } from "@babel/core";
import type * as BabelTypes from "@babel/types";
import path from "node:path";

interface State extends PluginPass {
  filename?: string;
}

export default function larkSrcPlugin({ types: t }: { types: typeof BabelTypes }): PluginObj<State> {
  const cwd = process.cwd();
  return {
    name: "lark-src",
    visitor: {
      JSXOpeningElement(nodePath, state) {
        const name = nodePath.node.name;
        if (name.type !== "JSXIdentifier") return;
        if (/^[A-Z]/.test(name.name)) return; // skip React components
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
