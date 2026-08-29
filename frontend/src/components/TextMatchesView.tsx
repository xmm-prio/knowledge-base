/**
 * A full-text search result: the lines that matched, and the declarations they sit inside.
 *
 * Both halves are shown because they answer different questions. The matching lines are the
 * only thing that finds a comment, a string literal or a language the upstream never parsed.
 * The declarations around them are what makes a hit worth clicking -- from there the source and
 * the call chain are one button away, exactly as they are from a symbol search.
 */

import type { CodeSymbol, TextMatches } from "../api/types";
import { Button, CopyButton, Empty } from "../ui";
import { PayloadView } from "./PayloadView";
import css from "./symbols.module.css";

function isTextMatches(payload: unknown): payload is TextMatches {
  return (
    typeof payload === "object" &&
    payload !== null &&
    Array.isArray((payload as TextMatches).lines) &&
    Array.isArray((payload as TextMatches).symbols)
  );
}

function Declaration({
  symbol,
  onRead,
  onTrace,
}: {
  symbol: CodeSymbol;
  onRead?: (canonical: string) => void;
  onTrace?: (canonical: string) => void;
}) {
  return (
    <div className={css.row}>
      <div className={css.head}>
        <span className={css.name}>{symbol.display_qn}</span>
        {symbol.kind ? <span className={css.kind}>{symbol.kind}</span> : null}
        {symbol.repo ? <span className={css.repo}>{symbol.repo}</span> : null}
      </div>
      {symbol.file ? (
        <span className={css.where}>
          {symbol.file}
          {symbol.line === null ? "" : `:${symbol.line}`}
        </span>
      ) : null}
      <div className={css.actions}>
        {onRead ? (
          <Button small onClick={() => onRead(symbol.canonical_qn)}>
            读源码
          </Button>
        ) : null}
        {onTrace ? (
          <Button small onClick={() => onTrace(symbol.canonical_qn)}>
            追调用链
          </Button>
        ) : null}
        <CopyButton small text={symbol.canonical_qn} label="复制限定名" />
      </div>
    </div>
  );
}

export function TextMatchesView({
  payload,
  onRead,
  onTrace,
}: {
  payload: unknown;
  onRead?: (canonical: string) => void;
  onTrace?: (canonical: string) => void;
}) {
  if (!isTextMatches(payload)) return <PayloadView payload={payload} empty="上游返回了空结果" />;
  if (!payload.symbols.length && !payload.lines.length) {
    return (
      <>
        <Empty title="没有匹配的内容" hint="换个写法，或改用符号搜索。" />
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
          共匹配 {payload.total ?? "更多"} 处，这里只是上游截取的前一段。缩小检索词或限定目录以看到其余的。
        </div>
      ) : null}
      {payload.lines.length ? (
        <div className={css.grep}>
          {payload.lines.map((one, index) => (
            <div key={`${one.file}:${one.line}:${index}`} className={css.grepLine}>
              <span className={css.where}>
                {one.file}
                {one.line === null ? "" : `:${one.line}`}
              </span>
              <code className={css.grepText}>{one.text}</code>
            </div>
          ))}
        </div>
      ) : null}
      {payload.symbols.length ? (
        <>
          <div className={css.section}>匹配所在的声明</div>
          {payload.symbols.map((one) => (
            <Declaration
              key={`${one.repo ?? ""}\u0000${one.canonical_qn}`}
              symbol={one}
              onRead={onRead}
              onTrace={onTrace}
            />
          ))}
        </>
      ) : null}
    </div>
  );
}
