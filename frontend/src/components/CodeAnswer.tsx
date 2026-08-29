/**
 * One answer from the code domain.
 *
 * The envelope carries four separate things and each has to survive to the screen: whether the
 * upstream answered at all, whose fault it was when it did not, what it said, and the caveat
 * saying how far the answer can be trusted. A failed code answer arrives inside a 200 -- it is
 * a state of the page, not an error of the request -- so it is drawn here rather than thrown.
 *
 * Only the envelope is this component's business. What the payload *is* differs per question,
 * so the body is handed to the caller as a render function and falls back to the shape-driven
 * JSON view for the answers this service does not read into.
 */

import type { ReactNode } from "react";
import type { CodeReply, FailureKind } from "../api/types";
import { Caveat, Empty, Loading, ErrorNotice } from "../ui";
import { PayloadView } from "./PayloadView";

/**
 * What each failure means for the person reading it. The old page said "上游没有应答" to all
 * four, which sent someone off to find an operator over a bracket they had left open.
 */
const HEADINGS: Record<FailureKind, string> = {
  bad_request: "这次查询本身有问题",
  refused: "上游拒绝了这次查询",
  unavailable: "代码域上游暂时不可用",
  internal: "网关内部出错",
};

const UNCLASSIFIED = "代码域没能给出结果";

function Failed({ answer }: { answer: CodeReply }) {
  const heading = answer.kind ? HEADINGS[answer.kind] : UNCLASSIFIED;
  const detail = answer.error ?? "上游未说明原因";
  return (
    <ErrorNotice
      title={heading}
      error={new Error(answer.diagnostic ? `${detail}（诊断 ${answer.diagnostic}）` : detail)}
    />
  );
}

export function CodeAnswer({
  answer,
  loading,
  error,
  idle,
  empty,
  children,
}: {
  answer: CodeReply | null;
  loading?: boolean;
  error?: unknown;
  idle?: string;
  empty?: string;
  /** How to draw this particular answer. Omitted, the payload gets the generic JSON view. */
  children?: (payload: unknown) => ReactNode;
}) {
  if (loading) return <Loading />;
  if (error) return <ErrorNotice error={error} />;
  if (!answer) return <Empty title={idle ?? "还没有查询"} />;
  if (!answer.ok) return <Failed answer={answer} />;
  return (
    <>
      <Caveat text={answer.caveat} />
      {children ? (
        children(answer.payload)
      ) : (
        <PayloadView payload={answer.payload} empty={empty ?? "上游返回了空结果"} />
      )}
    </>
  );
}
