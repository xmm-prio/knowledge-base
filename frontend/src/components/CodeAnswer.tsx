/**
 * One answer from the code domain.
 *
 * The envelope carries three separate things and each has to survive to the screen: whether
 * the upstream answered at all, what it said, and the caveat that says how far the answer can
 * be trusted. A failed code answer arrives inside a 200 -- it is a state of the page, not an
 * error of the request -- so it is drawn here rather than thrown.
 */

import type { CodeReply } from "../api/types";
import { Caveat, Empty, Loading, ErrorNotice } from "../ui";
import { PayloadView } from "./PayloadView";

export function CodeAnswer({
  answer,
  loading,
  error,
  idle,
  empty,
}: {
  answer: CodeReply | null;
  loading?: boolean;
  error?: unknown;
  idle?: string;
  empty?: string;
}) {
  if (loading) return <Loading />;
  if (error) return <ErrorNotice error={error} />;
  if (!answer) return <Empty title={idle ?? "还没有查询"} />;
  if (!answer.ok) {
    return (
      <ErrorNotice
        title="代码域上游没有应答"
        error={new Error(answer.error ?? "上游未说明原因")}
      />
    );
  }
  return (
    <>
      <Caveat text={answer.caveat} />
      <PayloadView payload={answer.payload} empty={empty ?? "上游返回了空结果"} />
    </>
  );
}
