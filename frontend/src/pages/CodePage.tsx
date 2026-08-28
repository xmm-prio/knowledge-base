/**
 * The code domain.
 *
 * Six capabilities over one upstream binary, and one honest constraint running through all of
 * them: the payload's shape is not ours. Every answer therefore goes through the same
 * defensive renderer, and every caveat the upstream attaches is shown rather than summarized.
 */

import { useState } from "react";
import { api } from "../api/client";
import type { CallDirection, CodeReply, SearchMode } from "../api/types";
import { Page } from "../app/Shell";
import { CodeAnswer } from "../components/CodeAnswer";
import { useAction, useAsync } from "../hooks/useAsync";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorNotice,
  Field,
  Input,
  Loading,
  Panel,
  Segmented,
  Textarea,
} from "../ui";
import css from "./code.module.css";

type Tab = "architecture" | "search" | "symbol" | "calls" | "cypher";

const TABS: { value: Tab; label: string }[] = [
  { value: "architecture", label: "架构概览" },
  { value: "search", label: "符号搜索" },
  { value: "symbol", label: "符号详情" },
  { value: "calls", label: "调用链" },
  { value: "cypher", label: "Cypher" },
];

export function CodePage() {
  const [tab, setTab] = useState<Tab>("architecture");
  const [repo, setRepo] = useState<string | null>(null);

  const repos = useAsync(() => api.repos(), []);
  const reindex = useAction((name: string) => api.indexRepo(name));

  return (
    <Page title="代码库" lead="上游返回的结构未经确证，页面按形状而非字段名渲染，并始终留一份原始 JSON。">
      <div className={css.layout}>
        <Card tight>
          <Panel
            title="代码库"
            actions={
              <Button small onClick={() => repos.reload()} disabled={repos.loading}>
                刷新
              </Button>
            }
          >
            {repos.loading ? (
              <Loading />
            ) : repos.error ? (
              <ErrorNotice error={repos.error} />
            ) : repos.data?.repos.length ? (
              <div className={css.repos}>
                <button
                  type="button"
                  className={`${css.repo} ${repo === null ? css.repoOn : ""}`}
                  onClick={() => setRepo(null)}
                >
                  <span className={css.repoName}>全部代码库</span>
                  <span className={css.repoPath}>不限定仓库</span>
                </button>
                {repos.data.repos.map((one) => (
                  <button
                    key={one.name}
                    type="button"
                    className={`${css.repo} ${repo === one.name ? css.repoOn : ""}`}
                    onClick={() => setRepo(one.name)}
                  >
                    <span className={css.repoName}>
                      {one.name}
                      <Badge tone={one.indexed ? "ok" : "neutral"}>
                        {one.indexed ? "已索引" : "未索引"}
                      </Badge>
                    </span>
                    <span className={css.repoPath}>{one.path}</span>
                  </button>
                ))}
              </div>
            ) : (
              <Empty title="codebase/ 下没有代码库" hint="由运维手工放入后再重建索引。" />
            )}
            {repo ? (
              <div className={css.form}>
                <Button
                  small
                  disabled={reindex.running}
                  onClick={async () => {
                    await reindex.run(repo);
                    repos.reload();
                  }}
                >
                  {reindex.running ? "重建中…" : `重建 ${repo} 的索引`}
                </Button>
              </div>
            ) : null}
            {reindex.error ? <ErrorNotice error={reindex.error} /> : null}
            {reindex.result ? (
              <Badge tone={reindex.result.ok ? "ok" : "bad"}>
                {reindex.result.ok ? "索引重建完成" : "索引重建失败"}
              </Badge>
            ) : null}
          </Panel>
        </Card>

        <Card>
          <div className={css.tabs}>
            {TABS.map((one) => (
              <button
                key={one.value}
                type="button"
                className={`${css.tab} ${tab === one.value ? css.tabOn : ""}`}
                onClick={() => setTab(one.value)}
              >
                {one.label}
              </button>
            ))}
          </div>
          <div className={css.scopeNote}>
            当前范围：{repo ?? "全部代码库"}
          </div>
          <div className={css.answer}>
            {tab === "architecture" ? (
              <Architecture repo={repo} />
            ) : tab === "search" ? (
              <CodeSearch repo={repo} />
            ) : tab === "symbol" ? (
              <SymbolLookup repo={repo} />
            ) : tab === "calls" ? (
              <CallTrace repo={repo} />
            ) : (
              <CypherConsole repo={repo} />
            )}
          </div>
        </Card>
      </div>
    </Page>
  );
}

function Architecture({ repo }: { repo: string | null }) {
  const answer = useAsync<CodeReply | null>(repo ? () => api.architecture(repo) : null, [repo]);
  if (!repo) {
    return <Empty title="先在左侧选一个代码库" hint="架构概览只对单个代码库有意义。" />;
  }
  return <CodeAnswer answer={answer.data} loading={answer.loading} error={answer.error} />;
}

function CodeSearch({ repo }: { repo: string | null }) {
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState<SearchMode>("symbol");
  const query = useAction((q: string, m: SearchMode) => api.searchCode(q, m, repo));

  return (
    <>
      <form
        className={css.form}
        onSubmit={(event) => {
          event.preventDefault();
          if (draft.trim()) query.run(draft.trim(), mode);
        }}
      >
        <div className={css.grow}>
          <Field label={mode === "symbol" ? "符号名（正则）" : "源码关键词"}>
            <Input value={draft} onChange={(event) => setDraft(event.target.value)} />
          </Field>
        </div>
        <Field label="方式">
          <Segmented
            value={mode}
            options={[
              { value: "symbol", label: "符号" },
              { value: "text", label: "全文" },
            ]}
            onChange={setMode}
          />
        </Field>
        <Button tone="primary" type="submit" disabled={query.running}>
          搜索
        </Button>
      </form>
      <CodeAnswer answer={query.result} loading={query.running} error={query.error} idle="输入检索词" />
    </>
  );
}

function SymbolLookup({ repo }: { repo: string | null }) {
  const [name, setName] = useState("");
  const query = useAction((one: string) => api.symbol(one, repo));

  return (
    <>
      <form
        className={css.form}
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim()) query.run(name.trim());
        }}
      >
        <div className={css.grow}>
          <Field label="限定名（由符号搜索得到）">
            <Input
              value={name}
              placeholder="knowledge_base.docs.notes.parse_learning"
              onChange={(event) => setName(event.target.value)}
            />
          </Field>
        </div>
        <Button tone="primary" type="submit" disabled={query.running}>
          读取
        </Button>
      </form>
      <CodeAnswer answer={query.result} loading={query.running} error={query.error} idle="输入限定名" />
    </>
  );
}

function CallTrace({ repo }: { repo: string | null }) {
  const [symbol, setSymbol] = useState("");
  const [direction, setDirection] = useState<CallDirection>("inbound");
  const [depth, setDepth] = useState(3);
  const query = useAction((one: string, way: CallDirection, deep: number) =>
    api.calls(one, way, deep, repo),
  );

  return (
    <>
      <form
        className={css.form}
        onSubmit={(event) => {
          event.preventDefault();
          if (symbol.trim()) query.run(symbol.trim(), direction, depth);
        }}
      >
        <div className={css.grow}>
          <Field label="起点符号">
            <Input value={symbol} onChange={(event) => setSymbol(event.target.value)} />
          </Field>
        </div>
        <Field label="方向">
          <Segmented
            value={direction}
            options={[
              { value: "inbound", label: "谁调用它" },
              { value: "outbound", label: "它调用谁" },
              { value: "both", label: "双向" },
            ]}
            onChange={setDirection}
          />
        </Field>
        <Field label="深度">
          <Input
            type="number"
            min={1}
            max={5}
            value={depth}
            onChange={(event) => setDepth(Number(event.target.value))}
          />
        </Field>
        <Button tone="primary" type="submit" disabled={query.running}>
          追踪
        </Button>
      </form>
      <CodeAnswer answer={query.result} loading={query.running} error={query.error} idle="输入起点符号" />
    </>
  );
}

function CypherConsole({ repo }: { repo: string | null }) {
  const [cypher, setCypher] = useState("MATCH (n) RETURN n LIMIT 10");
  const query = useAction((text: string) => api.cypher(text, repo));

  return (
    <>
      <form
        className={css.form}
        onSubmit={(event) => {
          event.preventDefault();
          if (cypher.trim()) query.run(cypher.trim());
        }}
      >
        <div className={css.grow}>
          <Field label="只读 Cypher">
            <Textarea value={cypher} onChange={(event) => setCypher(event.target.value)} />
          </Field>
        </div>
        <Button tone="primary" type="submit" disabled={query.running}>
          执行
        </Button>
      </form>
      <CodeAnswer answer={query.result} loading={query.running} error={query.error} idle="写一条查询" />
    </>
  );
}
