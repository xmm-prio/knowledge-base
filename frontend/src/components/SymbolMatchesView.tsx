/**
 * A symbol search result, as a list of things you can click.
 *
 * Two rules are load-bearing here. What is shown is `display_qn`, because a qualified name that
 * begins with a flattened absolute path is unreadable and the path is not even stable. What is
 * *handed on* -- to reading the source, to tracing calls, to the clipboard -- is always
 * `canonical_qn`, because that is the only name the upstream has heard of.
 *
 * What could not be read is stated rather than swallowed: a member who is shown "3 条结果" over
 * a payload of eleven entries will believe the three.
 */

import type { SymbolMatches } from "../api/types";
import { Button, CopyButton, Empty } from "../ui";
import { PayloadView } from "./PayloadView";
import css from "./symbols.module.css";

function isMatches(payload: unknown): payload is SymbolMatches {
  return typeof payload === "object" && payload !== null && Array.isArray((payload as SymbolMatches).matches);
}

function Where({ file, line }: { file: string | null; line: number | null }) {
  if (!file) return null;
  return (
    <span className={css.where}>
      {file}
      {line === null ? "" : `:${line}`}
    </span>
  );
}

export function SymbolMatchesView({
  payload,
  onRead,
  onTrace,
}: {
  payload: unknown;
  /** Called with the canonical name, never the one on screen. */
  onRead?: (canonical: string) => void;
  onTrace?: (canonical: string) => void;
}) {
  // The reader is tolerant, but an upstream that returned something else entirely still has to
  // reach the screen rather than a blank panel.
  if (!isMatches(payload)) return <PayloadView payload={payload} empty="上游返回了空结果" />;
  if (!payload.matches.length) {
    return (
      <>
        <Empty
          title="没有匹配的符号"
          hint={
            payload.unreadable
              ? `上游返回了 ${payload.unreadable} 条无法识别限定名的结果，已略去。`
              : "换个写法，或改用全文搜索。"
          }
        />
        {payload.raw === null || payload.raw === undefined ? null : (
          <PayloadView payload={payload.raw} empty="上游返回了空结果" />
        )}
      </>
    );
  }

  return (
    <div className={css.list}>
      {payload.truncated ? (
        <div className={css.dropped}>
          只显示了前 {payload.matches.length} 条
          {payload.total === null ? "" : `，共匹配 ${payload.total} 条`}。缩小检索词以看到其余的。
        </div>
      ) : null}
      {payload.unreadable ? (
        <div className={css.dropped}>
          上游另有 {payload.unreadable} 条结果没有可用的限定名，无法读取或追踪，已略去。
        </div>
      ) : null}
      {payload.matches.map((one) => (
        <div key={`${one.repo ?? ""}\u0000${one.canonical_qn}`} className={css.row}>
          <div className={css.head}>
            <span className={css.name}>{one.display_qn}</span>
            {one.kind ? <span className={css.kind}>{one.kind}</span> : null}
            {one.repo ? <span className={css.repo}>{one.repo}</span> : null}
          </div>
          <Where file={one.file} line={one.line} />
          <div className={css.actions}>
            {onRead ? (
              <Button small onClick={() => onRead(one.canonical_qn)}>
                读源码
              </Button>
            ) : null}
            {onTrace ? (
              <Button small onClick={() => onTrace(one.canonical_qn)}>
                追调用链
              </Button>
            ) : null}
            <CopyButton small text={one.canonical_qn} label="复制限定名" />
          </div>
        </div>
      ))}
    </div>
  );
}
