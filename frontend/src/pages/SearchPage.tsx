/**
 * One query, two answers, never merged.
 *
 * Documents are ranked by BM25 over a jieba-tokenized index; code is ranked by whatever the
 * upstream binary does. Those two numbers mean different things, so the page puts them in
 * two columns and lets the reader compare -- rather than inventing a combined ranking that
 * neither index can justify. When the code side is down, the document side still answers.
 */

import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Hit, SearchMode, SearchReply } from "../api/types";
import { CodeAnswer } from "../components/CodeAnswer";
import { SymbolMatchesView } from "../components/SymbolMatchesView";
import { useAsync } from "../hooks/useAsync";
import { routes } from "../routes";
import { Button, Empty, ErrorNotice, Field, Input, Loading, Panel, Segmented, Select } from "../ui";
import { Page } from "../app/Shell";
import css from "./search.module.css";

const MODES: { value: SearchMode; label: string }[] = [
  { value: "symbol", label: "符号" },
  { value: "text", label: "全文" },
  { value: "regex", label: "正则" },
];

interface Group {
  path: string;
  title: string;
  summary: string;
  best: number;
  snippets: Hit[];
}

/** The same document can be hit as a whole and through several of its observations. */
function groupByPath(hits: Hit[]): Group[] {
  const groups = new Map<string, Group>();
  for (const hit of hits) {
    let group = groups.get(hit.path);
    if (!group) {
      group = { path: hit.path, title: hit.title, summary: hit.summary, best: hit.score, snippets: [] };
      groups.set(hit.path, group);
    }
    group.best = Math.min(group.best, hit.score);
    if (hit.kind === "observation") group.snippets.push(hit);
  }
  return [...groups.values()].sort((a, b) => a.best - b.best);
}

export function SearchPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";
  const mode = (params.get("mode") as SearchMode) ?? "symbol";
  const repo = params.get("repo") ?? "";

  const [draft, setDraft] = useState(query);
  useEffect(() => setDraft(query), [query]);

  const repos = useAsync(() => api.repos(), []);
  const results = useAsync<SearchReply | null>(
    query ? () => api.search(query, { mode, repo: repo || null }) : null,
    [query, mode, repo],
  );

  const groups = useMemo(() => groupByPath(results.data?.documents.hits ?? []), [results.data]);

  const submit = (next: Partial<{ q: string; mode: SearchMode; repo: string }>) => {
    const merged = { q: draft, mode, repo, ...next };
    const search = new URLSearchParams();
    if (merged.q) search.set("q", merged.q);
    if (merged.mode !== "symbol") search.set("mode", merged.mode);
    if (merged.repo) search.set("repo", merged.repo);
    setParams(search);
  };

  return (
    <Page title="统一搜索" lead="文档与代码分两栏，各自排序，互不混排。">
      <form
        className={css.bar}
        onSubmit={(event) => {
          event.preventDefault();
          submit({});
        }}
      >
        <div className={css.query}>
          <Field label="检索词（中文按 jieba 分词）">
            <Input
              large
              value={draft}
              autoFocus
              placeholder="例如：对齐、脏数据、DataCopy"
              onChange={(event) => setDraft(event.target.value)}
            />
          </Field>
        </div>
        <Field label="代码检索方式">
          <Segmented value={mode} options={MODES} onChange={(next) => submit({ mode: next })} />
        </Field>
        <Field label="代码库">
          <Select value={repo} onChange={(event) => submit({ repo: event.target.value })}>
            <option value="">全部</option>
            {(repos.data?.repos ?? []).map((one) => (
              <option key={one.name} value={one.name}>
                {one.name}
                {one.indexed ? "" : "（未索引）"}
              </option>
            ))}
          </Select>
        </Field>
        <Button tone="primary" type="submit">
          搜索
        </Button>
      </form>

      {!query ? (
        <Empty title="输入检索词开始" hint="文档侧查标题、摘要与单条观察；代码侧查符号名或源码全文。" />
      ) : (
        <div className={css.columns}>
          <div className={css.column}>
            <Panel
              title="文档"
              note={
                results.data
                  ? `${groups.length} 篇 · ${results.data.documents.hits.length} 处命中`
                  : undefined
              }
            >
              {results.loading ? (
                <Loading />
              ) : results.error ? (
                <ErrorNotice error={results.error} />
              ) : groups.length ? (
                <div className={css.results}>
                  {groups.map((group) => (
                    <DocumentGroup key={group.path} group={group} />
                  ))}
                </div>
              ) : (
                <Empty title="没有命中的文档" hint="换个说法试试，检索是精确匹配而非语义召回。" />
              )}
            </Panel>
            <div className={css.hint}>
              分数是 BM25，越小越相关；它不是百分比，也不能与代码侧比较。
            </div>
          </div>

          <div className={css.column}>
            <Panel title="代码" note={repo ? `限定 ${repo}` : "全部代码库"}>
              <CodeAnswer
                answer={results.data?.code ?? null}
                loading={results.loading}
                error={results.error}
                empty="代码侧没有命中"
              >
                {mode === "text"
                  ? undefined
                  : (payload) => (
                      <SymbolMatchesView
                        payload={payload}
                        onRead={(canonical) => navigate(routes.code(canonical))}
                      />
                    )}
              </CodeAnswer>
            </Panel>
          </div>
        </div>
      )}
    </Page>
  );
}

function DocumentGroup({ group }: { group: Group }) {
  return (
    <article className={css.group}>
      <header className={css.groupHead}>
        <Link className={css.title} to={routes.documents(group.path)}>
          {group.title || group.path}
        </Link>
        <span className={css.score}>{group.best.toFixed(2)}</span>
      </header>
      <div className={css.path}>{group.path}</div>
      {group.summary ? <div className={css.summary}>{group.summary}</div> : null}
      {group.snippets.length ? (
        <ul className={css.snippets}>
          {group.snippets.map((hit, index) => (
            <li key={index} className={css.snippet}>
              <span className={css.kind}>观察</span>
              <span>{hit.snippet}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}
