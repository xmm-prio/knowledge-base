/**
 * A traced call chain, drawn as what it is.
 *
 * A generic JSON tree can show a call graph and still leave the one question unanswered: who
 * calls whom, and how far from the symbol you asked about. So the chain is laid out by depth
 * from the symbol traced, and each row is clickable onward.
 *
 * Two things it deliberately does not draw. Beyond the first hop there are no lines between
 * symbols, because the upstream reports each hop's distance from the symbol asked about and
 * never which symbol it arrived through -- a line from the second hop to the third would be
 * this page's invention. And what the upstream could not pin down is shown as a count rather
 * than omitted: an empty chain that silently dropped four ambiguous relations reads as proof
 * that nothing calls the symbol, which is exactly the wrong conclusion.
 */

import type { CallChain, CallNode } from "../api/types";
import { Badge, Button, CopyButton, Empty } from "../ui";
import { PayloadView } from "./PayloadView";
import css from "./calls.module.css";

function isChain(payload: unknown): payload is CallChain {
  return typeof payload === "object" && payload !== null && Array.isArray((payload as CallChain).edges);
}

const RELATION: Record<string, string> = {
  inbound: "调用起点",
  outbound: "被起点调用",
  both: "与起点相关",
};

/** How the upstream resolved a hop, said in terms of how much to trust it. */
const STRATEGY: Record<string, string> = {
  lsp: "类型解析",
  language_rule: "语言规则",
  heuristic: "启发式推断",
};

function Evidence({ node }: { node: CallNode }) {
  if (!node.strategy) return null;
  const trusted = node.strategy === "lsp";
  return (
    <Badge tone={trusted ? "ok" : "neutral"}>
      {STRATEGY[node.strategy] ?? node.strategy}
      {node.confidence === null ? "" : ` ${Math.round(node.confidence * 100)}%`}
    </Badge>
  );
}

export function CallChainView({
  payload,
  onRead,
  onTrace,
}: {
  payload: unknown;
  /** Called with the canonical name, never the one on screen. */
  onRead?: (canonical: string) => void;
  onTrace?: (canonical: string) => void;
}) {
  if (!isChain(payload)) return <PayloadView payload={payload} empty="上游返回了空结果" />;
  if (!payload.nodes.length) {
    return (
      <>
        <Empty
          title="没有可确证的调用关系"
          hint={
            payload.unresolved
              ? `上游报告了 ${payload.unresolved} 条无法唯一确定的关系，已略去。`
              : "这个符号在已解析的语言里没有被调用，或者它所在的语言未被解析。"
          }
        />
        {payload.raw === null || payload.raw === undefined ? null : (
          <PayloadView payload={payload.raw} empty="上游返回了空结果" />
        )}
      </>
    );
  }

  return (
    <div className={css.chain}>
      {payload.unresolved ? (
        <div className={css.dropped}>
          另有 {payload.unresolved} 条调用关系无法唯一确定两端的符号，已略去。没有边不等于没有调用。
        </div>
      ) : null}
      {payload.truncated ? (
        <div className={css.dropped}>
          共 {payload.total ?? "更多"} 条，这里只是其中一页。
        </div>
      ) : null}
      <div className={css.node}>
        <div className={css.head}>
          <span className={css.depth}>起点</span>
          <span className={css.name}>{payload.root}</span>
        </div>
      </div>
      {payload.nodes.map((node) => (
        <div
          key={node.symbol.canonical_qn}
          className={css.node}
          style={{ marginInlineStart: `${node.depth * 20}px` }}
        >
          <div className={css.head}>
            <span className={css.depth}>第 {node.depth} 跳</span>
            <span className={css.name}>{node.symbol.display_qn}</span>
            {node.depth === 1 ? (
              <span className={css.relation}>{RELATION[payload.direction] ?? RELATION.both}</span>
            ) : null}
            <Evidence node={node} />
            {node.symbol.file ? (
              <span className={css.where}>
                {node.symbol.file}
                {node.symbol.line === null ? "" : `:${node.symbol.line}`}
              </span>
            ) : null}
          </div>
          <div className={css.actions}>
            {onRead ? (
              <Button small onClick={() => onRead(node.symbol.canonical_qn)}>
                读源码
              </Button>
            ) : null}
            {onTrace ? (
              <Button small onClick={() => onTrace(node.symbol.canonical_qn)}>
                从这里继续追
              </Button>
            ) : null}
            <CopyButton small text={node.symbol.canonical_qn} label="复制限定名" />
          </div>
        </div>
      ))}
      <div className={css.dropped}>
        第 2 跳起只知道距离起点多远，不知道经由谁抵达，因此不画符号之间的连线。要看中间那一段，从对应符号继续追。
      </div>
    </div>
  );
}
