/**
 * Version history, and the one way back.
 *
 * A commit here aggregates whatever one author wrote during a quiet period, across unrelated
 * documents (ADR-0003), so the page never offers to undo a commit -- it offers to put *one
 * document* back to the text one commit held. That is what the backend implements, and the
 * diff shown before the button is exactly the change the button would make.
 */

import { useEffect, useMemo, useState } from "react";
import { diffLines } from "diff";
import { useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { Page } from "../app/Shell";
import { useAction, useAsync } from "../hooks/useAsync";
import { useAuthor } from "../hooks/useAuthor";
import { Button, Card, Empty, ErrorNotice, Field, Input, Loading, Panel, Segmented } from "../ui";
import css from "./history.module.css";

type Look = "diff" | "text";

/** A document deleted since the revision has no current text; that is a diff, not a failure. */
async function currentText(path: string): Promise<string> {
  try {
    return (await api.document(path)).text;
  } catch (failure) {
    if (failure instanceof ApiError && failure.status === 404) return "";
    throw failure;
  }
}

export function HistoryPage() {
  const [params, setParams] = useSearchParams();
  const path = params.get("path") ?? "";
  const [draft, setDraft] = useState(path);
  useEffect(() => setDraft(path), [path]);

  const [author] = useAuthor();
  const [revision, setRevision] = useState<string | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [look, setLook] = useState<Look>("diff");

  const history = useAsync(() => api.history(path || null, 50), [path]);
  useEffect(() => {
    setRevision(null);
    setChosen(null);
  }, [path]);

  const commit = useAsync(revision ? () => api.commit(revision) : null, [revision]);
  const target = path || chosen || commit.data?.paths[0] || null;

  const before = useAsync(
    revision && target ? () => api.revisionText(revision, target) : null,
    [revision, target],
  );
  const after = useAsync(target ? () => currentText(target) : null, [target, revision]);

  const restore = useAction(async () => {
    if (!revision || !target) return null;
    const done = await api.restore(revision, target, author);
    history.reload();
    after.reload();
    return done;
  });

  const hunks = useMemo(() => {
    if (before.data === null || after.data === null) return null;
    return diffLines(after.data ?? "", before.data.text);
  }, [before.data, after.data]);

  return (
    <Page title="历史与回滚" lead="git 是版本机制；回滚以单篇文档为粒度，产生新提交，从不改写历史。">
      <form
        className={css.toolbar}
        onSubmit={(event) => {
          event.preventDefault();
          setParams(draft ? { path: draft } : {});
        }}
      >
        <div className={css.pathField}>
          <Field label="收窄到某篇文档（留空看整库）">
            <Input
              value={draft}
              placeholder="learnings/ascendc/对齐要求.md"
              onChange={(event) => setDraft(event.target.value)}
            />
          </Field>
        </div>
        <Button type="submit">应用</Button>
        {path ? (
          <Button tone="ghost" onClick={() => setParams({})}>
            看整库
          </Button>
        ) : null}
      </form>

      <div className={css.layout}>
        <Card tight>
          <Panel title="版本" note={history.data ? `${history.data.revisions.length} 个提交` : undefined}>
            {history.loading ? (
              <Loading />
            ) : history.error ? (
              <ErrorNotice error={history.error} />
            ) : history.data?.revisions.length ? (
              <div className={css.revisions}>
                {history.data.revisions.map((one) => (
                  <button
                    key={one.revision}
                    type="button"
                    className={`${css.revision} ${one.revision === revision ? css.revisionOn : ""}`}
                    onClick={() => {
                      setRevision(one.revision);
                      setChosen(null);
                      restore.reset();
                    }}
                  >
                    <span className={css.message}>{one.message || "（无提交说明）"}</span>
                    <span className={css.meta}>
                      <span className={css.sha}>{one.revision.slice(0, 8)}</span>
                      <span>{one.author}</span>
                      <span>{one.at.slice(0, 19).replace("T", " ")}</span>
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <Empty title="还没有历史" hint="写入后静默 30 秒才会合并成一个提交。" />
            )}
          </Panel>
        </Card>

        <Card>
          {!revision ? (
            <Empty title="选一个版本" hint="左侧点击某个提交，这里显示它与当前内容的差异。" />
          ) : (
            <Panel
              title={target ?? "这个提交"}
              actions={
                <div className={css.panelActions}>
                  <Segmented
                    value={look}
                    options={[
                      { value: "diff", label: "差异" },
                      { value: "text", label: "该版本原文" },
                    ]}
                    onChange={setLook}
                  />
                  <Button
                    tone="primary"
                    disabled={!target || !author || restore.running}
                    onClick={() => {
                      if (!target) return;
                      if (window.confirm(`把 ${target} 回滚到 ${revision.slice(0, 8)}？`)) {
                        restore.run();
                      }
                    }}
                  >
                    {restore.running ? "回滚中…" : "回滚这篇"}
                  </Button>
                </div>
              }
            >
              {!path && commit.data?.paths.length ? (
                <div className={css.paths}>
                  {commit.data.paths.map((one) => (
                    <button
                      key={one}
                      type="button"
                      className={`${css.pathChip} ${one === target ? css.pathChipOn : ""}`}
                      onClick={() => {
                        setChosen(one);
                        restore.reset();
                      }}
                    >
                      {one}
                    </button>
                  ))}
                </div>
              ) : null}

              {restore.error ? <ErrorNotice error={restore.error} title="回滚被拒绝" /> : null}
              {restore.result ? (
                <div className={css.restored}>
                  {restore.result.revision
                    ? `已回滚，新提交 ${restore.result.revision.slice(0, 8)}`
                    : "内容与现状相同，没有产生提交"}
                </div>
              ) : null}
              {!author ? (
                <ErrorNotice
                  title="还没有填写作者"
                  error={new Error("左下角填一个名字后才能回滚；它会写进 git 历史。")}
                />
              ) : null}

              {commit.error ? <ErrorNotice error={commit.error} /> : null}
              {before.loading || after.loading ? (
                <Loading />
              ) : before.error ? (
                <ErrorNotice error={before.error} title="读取该版本内容失败" />
              ) : after.error ? (
                <ErrorNotice error={after.error} title="读取当前内容失败" />
              ) : look === "text" ? (
                <pre className={css.diff}>
                  <div className={css.line}>{before.data?.text ?? ""}</div>
                </pre>
              ) : hunks ? (
                <Diff hunks={hunks} />
              ) : (
                <Empty title="这个提交没有可对比的文档" />
              )}
            </Panel>
          )}
        </Card>
      </div>
    </Page>
  );
}

const CONTEXT_LINES = 3;

function Diff({ hunks }: { hunks: ReturnType<typeof diffLines> }) {
  const rows: { sign: string; text: string; tone: "added" | "removed" | "context" }[] = [];
  for (const hunk of hunks) {
    const tone = hunk.added ? "added" : hunk.removed ? "removed" : "context";
    const lines = hunk.value.split("\n");
    if (lines[lines.length - 1] === "") lines.pop();
    const sign = hunk.added ? "+" : hunk.removed ? "−" : " ";
    if (tone === "context" && lines.length > CONTEXT_LINES * 2 + 1) {
      for (const line of lines.slice(0, CONTEXT_LINES)) rows.push({ sign, text: line, tone });
      rows.push({ sign: "", text: `⋯ 省略 ${lines.length - CONTEXT_LINES * 2} 行 ⋯`, tone: "context" });
      for (const line of lines.slice(-CONTEXT_LINES)) rows.push({ sign, text: line, tone });
      continue;
    }
    for (const line of lines) rows.push({ sign, text: line, tone });
  }

  if (!rows.some((row) => row.tone !== "context")) {
    return <Empty title="与当前内容相同" hint="回滚这一篇不会产生任何改动。" />;
  }

  return (
    <div className={css.diff}>
      {rows.map((row, index) => (
        <div key={index} className={`${css.line} ${css[row.tone]}`}>
          <span className={css.sign}>{row.sign}</span>
          <span>{row.text || " "}</span>
        </div>
      ))}
    </div>
  );
}
