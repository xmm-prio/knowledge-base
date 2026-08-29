/**
 * A traced call chain, drawn as what it is.
 *
 * A generic JSON tree can show a call graph and still leave the one question unanswered: who
 * calls whom, and how far from the symbol you asked about. So the chain is laid out by depth,
 * with each symbol's callers or callees listed under it, and each row clickable onward.
 *
 * What the upstream could not pin down is shown as a count, not omitted. An empty chain that
 * silently dropped four ambiguous relations reads as proof that nothing calls the symbol, which
 * is exactly the wrong conclusion.
 */

import type { CallChain, CallNode } from "../api/types";
import { Button, CopyButton, Empty } from "../ui";
import { PayloadView } from "./PayloadView";
import css from "./calls.module.css";

function isChain(payload: unknown): payload is CallChain {
  return typeof payload === "object" && payload !== null && Array.isArray((payload as CallChain).edges);
}

const RELATION: Record<string, string> = {
  inbound: "被调用于",
  outbound: "调用",
  both: "关联",
};

function Dropped({ count }: { count: number }) {
  if (!count) return null;
  return (
    <div className={css.dropped}>
      另有 {count} 条调用关系无法唯一确定两端的符号，已略去。没有边不等于没有调用。
    </div>
  );
}

function Neighbours({ chain, node }: { chain: CallChain; node: CallNode }) {
  const canonical = node.symbol.canonical_qn;
  const outward = chain.edges
    .filter((edge) => (chain.direction === "outbound" ? edge.caller : edge.callee) === canonical)
    .map((edge) => (chain.direction === "outbound" ? edge.callee : edge.caller));
  if (!outward.length) return null;
  const shown = new Map(chain.nodes.map((one) => [one.symbol.canonical_qn, one.symbol.display_qn]));
  return (
    <ul className={css.neighbours}>
      {outward.map((name) => (
        <li key={name}>
          <span className={css.relation}>{RELATION[chain.direction] ?? RELATION.both}</span>
          <span className={css.name}>{shown.get(name) ?? name}</span>
        </li>
      ))}
    </ul>
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
      <Dropped count={payload.unresolved} />
      {payload.nodes.map((node) => (
        <div key={node.symbol.canonical_qn} className={css.node} style={{ marginInlineStart: `${node.depth * 20}px` }}>
          <div className={css.head}>
            <span className={css.depth}>{node.depth === 0 ? "起点" : `第 ${node.depth} 跳`}</span>
            <span className={css.name}>{node.symbol.display_qn}</span>
            {node.symbol.file ? (
              <span className={css.where}>
                {node.symbol.file}
                {node.symbol.line === null ? "" : `:${node.symbol.line}`}
              </span>
            ) : null}
          </div>
          <Neighbours chain={payload} node={node} />
          <div className={css.actions}>
            {onRead ? (
              <Button small onClick={() => onRead(node.symbol.canonical_qn)}>
                读源码
              </Button>
            ) : null}
            {onTrace && node.depth > 0 ? (
              <Button small onClick={() => onTrace(node.symbol.canonical_qn)}>
                从这里继续追
              </Button>
            ) : null}
            <CopyButton small text={node.symbol.canonical_qn} label="复制限定名" />
          </div>
        </div>
      ))}
    </div>
  );
}
