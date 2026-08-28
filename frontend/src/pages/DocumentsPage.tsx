/**
 * Browsing and editing documents.
 *
 * Reading and writing are two views of the same page rather than two pages, because they are
 * the same document -- and because the editor's whole contract is that what it hands back is
 * what it was given (ADR-0005), which is far easier to keep true when there is one place that
 * holds the text.
 */

import { Suspense, lazy, useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { DocumentDetail, Neighbourhood } from "../api/types";
import { Page } from "../app/Shell";
// CodeMirror is most of this route's weight and only two of its four views need it.
const SourceEditor = lazy(() =>
  import("../editor/SourceEditor").then((m) => ({ default: m.SourceEditor })),
);
import { useAction, useAsync } from "../hooks/useAsync";
import { useAuthor } from "../hooks/useAuthor";
import { routes } from "../routes";
import { DocumentBody, ObservationsByCategory } from "../semantic/DocumentBody";
import {
  Button,
  Empty,
  ErrorNotice,
  Field,
  Input,
  Loading,
  Segmented,
  Select,
  Tag,
  TagRow,
} from "../ui";
import { DocumentTree } from "./DocumentTree";
import css from "./documents.module.css";

type View = "render" | "grouped" | "source" | "edit";

const LEARNING_TEMPLATE = (title: string) =>
  `---\ntitle: ${title}\ntype: note\nsummary: \ntags: []\nauthor: \n---\n# ${title}\n\n## Observations\n\n- [verified] \n\n## Relations\n\n- relates_to [[]]\n`;

const KNOWLEDGE_TEMPLATE = (title: string) =>
  `---\ntitle: ${title}\nsummary: \ntags: []\n---\n\n# ${title}\n\n`;

function titleOf(path: string): string {
  return path.split("/").pop()?.replace(/\.md$/i, "") ?? path;
}

export function DocumentsPage() {
  // React Router already decoded each segment of the splat; decoding again would eat a
  // literal percent sign in a title.
  const path = useParams()["*"] ?? "";
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [author] = useAuthor();

  const creating = params.get("new") === "1";
  const requested = (params.get("mode") as View) ?? (creating ? "edit" : "render");

  const [creatorOpen, setCreatorOpen] = useState(false);
  const tree = useAsync(() => api.tree(), []);
  const detail = useAsync<DocumentDetail | null>(
    path && !creating ? () => api.document(path) : null,
    [path, creating],
  );
  const neighbourhood = useAsync(path && !creating ? () => api.links(path, 1) : null, [
    path,
    creating,
  ]);

  const seed = creating
    ? path.startsWith("learnings/")
      ? LEARNING_TEMPLATE(titleOf(path))
      : KNOWLEDGE_TEMPLATE(titleOf(path))
    : (detail.data?.text ?? "");

  const [draft, setDraft] = useState(seed);
  useEffect(() => setDraft(seed), [seed]);

  const save = useAction(async (text: string) => {
    const written = await api.writeDocument(path, text, author);
    tree.reload();
    detail.reload();
    neighbourhood.reload();
    setParams({});
    return written;
  });

  const remove = useAction(async () => {
    await api.deleteDocument(path, author);
    tree.reload();
    navigate(routes.documents());
  });

  const view: View = creating ? "edit" : requested;
  const dirty = draft !== seed;

  return (
    <Page width="full">
      <div className={css.layout}>
        <aside className={css.tree}>
          <header className={css.treeHead}>
            <span className={css.treeTitle}>目录</span>
            <Button small onClick={() => setCreatorOpen((was) => !was)}>
              新建
            </Button>
          </header>
          {creatorOpen ? (
            <div className={css.treeTools}>
              <NewDocument
                onCancel={() => setCreatorOpen(false)}
                onCreate={(next) => {
                  setCreatorOpen(false);
                  navigate(`${routes.documents(next)}?new=1`);
                }}
              />
            </div>
          ) : null}
          <div className={css.treeBody}>
            {tree.loading ? (
              <Loading label="读取目录…" />
            ) : tree.error ? (
              <ErrorNotice error={tree.error} title="目录树读取失败" />
            ) : (
              <DocumentTree roots={tree.data?.directories ?? []} selected={path || null} />
            )}
          </div>
        </aside>

        <section className={css.reader}>
          {!path ? (
            <Empty title="从左侧选一篇文档" hint="knowledge/ 是人工维护的知识，learnings/ 是 agent 沉淀的经验。" />
          ) : detail.loading ? (
            <Loading />
          ) : detail.error ? (
            <div className={css.readerBody}>
              <ErrorNotice error={detail.error} title="打开文档失败" />
            </div>
          ) : (
            <>
              <header className={css.readerHead}>
                <div className={css.headTop}>
                  <div>
                    <div className={css.docTitle}>{detail.data?.title || titleOf(path)}</div>
                    <div className={css.docPath}>{path}</div>
                  </div>
                  <div className={css.actions}>
                    <Segmented
                      value={view}
                      options={[
                        { value: "render", label: "渲染" },
                        { value: "grouped", label: "按类别" },
                        { value: "source", label: "原文" },
                        { value: "edit", label: "编辑" },
                      ]}
                      onChange={(next) => setParams(next === "render" ? {} : { mode: next })}
                    />
                    {view === "edit" ? (
                      <Button
                        tone="primary"
                        disabled={save.running || !author || (!dirty && !creating)}
                        onClick={() => save.run(draft)}
                      >
                        {save.running ? "保存中…" : creating ? "创建" : "保存"}
                      </Button>
                    ) : (
                      <Button onClick={() => navigate(routes.history(path))}>历史</Button>
                    )}
                    {!creating ? (
                      <Button
                        tone="danger"
                        disabled={remove.running || !author}
                        onClick={() => {
                          if (window.confirm(`删除 ${path}？此操作会产生一个新提交，可从历史恢复。`)) {
                            remove.run();
                          }
                        }}
                      >
                        删除
                      </Button>
                    ) : null}
                  </div>
                </div>
                {detail.data?.summary ? (
                  <div className={css.docSummary}>{detail.data.summary}</div>
                ) : null}
                <div className={css.headMeta}>
                  <Timestamps detail={detail.data} creating={creating} />
                  {detail.data?.observations.length ? (
                    <span>{detail.data.observations.length} 条观察</span>
                  ) : null}
                  {detail.data?.tags.length ? (
                    <TagRow>
                      {detail.data.tags.map((tag) => (
                        <Tag key={tag} to={routes.tags(tag)}>
                          #{tag}
                        </Tag>
                      ))}
                    </TagRow>
                  ) : null}
                </div>
              </header>

              {!author && view === "edit" ? (
                <div className={css.editorNotice}>
                  <ErrorNotice
                    title="还没有填写作者"
                    error={new Error("左下角填一个名字后才能保存；它会写进 git 历史。")}
                  />
                </div>
              ) : null}
              {save.error ? (
                <div className={css.editorNotice}>
                  <ErrorNotice error={save.error} title="保存被拒绝" />
                </div>
              ) : null}
              {remove.error ? (
                <div className={css.editorNotice}>
                  <ErrorNotice error={remove.error} title="删除被拒绝" />
                </div>
              ) : null}

              {view === "edit" ? (
                <div className={css.editor}>
                  <div className={css.editorPane}>
                    <Suspense fallback={<Loading label="加载编辑器…" />}>
                      <SourceEditor initialText={seed} onChange={setDraft} />
                    </Suspense>
                  </div>
                  <div className={css.previewPane}>
                    <div className={css.previewLabel}>实时预览</div>
                    <DocumentBody text={draft} neighbourhood={neighbourhood.data} />
                  </div>
                </div>
              ) : (
                <div className={css.readerBody}>
                  <div className={css.readerMain}>
                    {view === "source" ? (
                      <div className={css.sourceBox}>
                        <Suspense fallback={<Loading label="加载编辑器…" />}>
                          <SourceEditor
                            initialText={detail.data?.text ?? ""}
                            onChange={() => {}}
                            readOnly
                          />
                        </Suspense>
                      </div>
                    ) : view === "grouped" ? (
                      detail.data?.observations.length ? (
                        <ObservationsByCategory observations={detail.data.observations} />
                      ) : (
                        <Empty
                          title="这篇文档没有观察"
                          hint="观察写作 `- [类别] 内容 #标签`，是可被单条检索的事实。"
                        />
                      )
                    ) : (
                      <DocumentBody
                        text={detail.data?.text ?? ""}
                        neighbourhood={neighbourhood.data}
                      />
                    )}
                  </div>
                  <aside className={css.rail}>
                    <Relations
                      neighbourhood={neighbourhood.data}
                      loading={neighbourhood.loading}
                      error={neighbourhood.error}
                    />
                  </aside>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </Page>
  );
}

function Timestamps({ detail, creating }: { detail: DocumentDetail | null; creating: boolean }) {
  if (creating) return <span>尚未创建</span>;
  if (!detail) return null;
  // Both null means the write is still inside the quiet period before its commit -- normal.
  if (!detail.created_at && !detail.updated_at) {
    return <span>未提交（写入后静默 30 秒才合并成一个提交）</span>;
  }
  const format = (at: string | null) => (at ? at.slice(0, 19).replace("T", " ") : "—");
  return (
    <>
      <span>创建于 {format(detail.created_at)}</span>
      <span>更新于 {format(detail.updated_at)}</span>
    </>
  );
}

function Relations({
  neighbourhood,
  loading,
  error,
}: {
  neighbourhood: Neighbourhood | null;
  loading: boolean;
  error: unknown;
}) {
  if (loading) return <Loading label="读取关联…" />;
  if (error) {
    const notFound = error instanceof ApiError && error.status === 404;
    return notFound ? null : <ErrorNotice error={error} title="关联读取失败" />;
  }
  const links = neighbourhood?.links ?? [];
  return (
    <div>
      <div className={css.railTitle}>关联文档</div>
      {links.length ? (
        <ul className={css.railList}>
          {links.map((link, index) => (
            <li key={index} className={css.railRow}>
              <span className={css.railType}>{link.type}</span>
              {link.target ? (
                <a href={`#${routes.documents(link.target)}`}>{link.target_name}</a>
              ) : (
                <span className={css.railMissing} title="尚未创建">
                  {link.target_name}
                </span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <div className={css.railType}>没有关联</div>
      )}
    </div>
  );
}

function NewDocument({
  onCreate,
  onCancel,
}: {
  onCreate: (path: string) => void;
  onCancel: () => void;
}) {
  const [root, setRoot] = useState("learnings");
  const [relative, setRelative] = useState("");

  const target = () => {
    const cleaned = relative.trim().replace(/^\/+/, "");
    if (!cleaned) return null;
    return `${root}/${cleaned.endsWith(".md") ? cleaned : `${cleaned}.md`}`;
  };

  return (
    <form
      className={css.creator}
      onSubmit={(event) => {
        event.preventDefault();
        const path = target();
        if (!path) return;
        setRelative("");
        onCreate(path);
      }}
    >
      <Field label="位置">
        <Select value={root} onChange={(event) => setRoot(event.target.value)}>
          <option value="knowledge">knowledge/</option>
          <option value="learnings">learnings/</option>
        </Select>
      </Field>
      <Field label="路径">
        <Input
          autoFocus
          value={relative}
          placeholder="ascendc/对齐要求.md"
          onChange={(event) => setRelative(event.target.value)}
        />
      </Field>
      <div className={css.creatorRow}>
        <Button tone="primary" type="submit">
          创建
        </Button>
        <Button tone="ghost" onClick={onCancel}>
          取消
        </Button>
      </div>
    </form>
  );
}
