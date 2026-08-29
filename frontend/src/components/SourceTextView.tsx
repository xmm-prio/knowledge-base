/**
 * One symbol's source, shown as source.
 *
 * The clip notice is the point of this component. The upstream cuts long bodies off at a fixed
 * number of lines and says so in a field nobody reads inside a JSON dump; read as the whole
 * thing, a clipped body is how somebody concludes a function does not handle a case it handles
 * two hundred lines further down.
 */

import type { SourceText } from "../api/types";
import { CopyButton } from "../ui";
import { PayloadView } from "./PayloadView";
import css from "./source.module.css";

function isSource(payload: unknown): payload is SourceText {
  return (
    typeof payload === "object" &&
    payload !== null &&
    typeof (payload as SourceText).text === "string" &&
    typeof (payload as SourceText).canonical_qn === "string"
  );
}

export function SourceTextView({ payload }: { payload: unknown }) {
  if (!isSource(payload)) return <PayloadView payload={payload} empty="上游返回了空结果" />;

  return (
    <div className={css.source}>
      <div className={css.head}>
        <span className={css.name}>{payload.display_qn}</span>
        {payload.file ? (
          <span className={css.where}>
            {payload.file}
            {payload.start_line === null ? "" : `:${payload.start_line}`}
            {payload.end_line === null ? "" : `-${payload.end_line}`}
          </span>
        ) : null}
        <CopyButton small text={payload.canonical_qn} label="复制限定名" />
        <CopyButton small text={payload.text} label="复制源码" />
      </div>
      {payload.clipped_at === null ? null : (
        <div className={css.clipped}>
          上游只返回了前 {payload.clipped_at} 行，后面还有。要看完整实现请直接打开文件。
        </div>
      )}
      <pre className={css.body}>
        <code>{payload.text}</code>
      </pre>
    </div>
  );
}
