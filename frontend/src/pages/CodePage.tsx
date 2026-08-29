/**
 * The code domain.
 *
 * Six capabilities over one upstream binary, and one honest constraint running through all of
 * them: the payload's shape is not ours. Every answer therefore goes through the same
 * defensive renderer, and every caveat the upstream attaches is shown rather than summarized.
 */

import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { CallDirection, CodeReply, SearchMode } from "../api/types";
import { Page } from "../app/Shell";
import { CallChainView } from "../components/CallChainView";
import { CodeAnswer } from "../components/CodeAnswer";
import { SourceTextView } from "../components/SourceTextView";
import { SymbolMatchesView } from "../components/SymbolMatchesView";
import { TextMatchesView } from "../components/TextMatchesView";
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

/**
 * Moving between the tabs by clicking a result rather than retyping a name.
 *
 * Every hand-off carries `canonical_qn`: the short name on screen is for reading, and handing
 * it back would break the very call the click was meant to make.
 */
interface Follow {
  read: (canonical: string) => void;
  trace: (canonical: string) => void;
}

export function CodePage() {
  // Arriving from the unified search with a symbol in hand means the question was already
  // asked; opening on the architecture tab would make it be asked again.
  const [params] = useSearchParams();
  const arrived = params.get("symbol") ?? "";

  const [tab, setTab] = useState<Tab>(arrived ? "symbol" : "architecture");
  const [repo, setRepo] = useState<string | null>(null);
  const [symbol, setSymbol] = useState(arrived);
  const [traced, setTraced] = useState("");

  const repos = useAsync(() => api.repos(), []);
  const reindex = useAction((name: string) => api.indexRepo(name));

  const follow: Follow = {
    read: (canonical) => {
      setSymbol(canonical);
      setTab("symbol");
    },
    trace: (canonical) => {
      setTraced(canonical);
      setTab("calls");
    },
  };

  return (
    <Page
      title="代码库"
      lead="“已索引”表示现在就能查得动，不只是上游记得建过。符号与调用链按本服务自己的模型呈现，其余结构未经确证，按形状渲染并始终留一份原始 JSON。"
    >
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
                    <span className={css.repoPath}>
                      {one.symbols === null
                        ? one.path
                        : `${one.symbols.toLocaleString()} 个符号` +
                          (one.partial_files ? `，${one.partial_files} 个文件未完整解析` : "")}
                    </span>
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
              <CodeSearch repo={repo} follow={follow} />
            ) : tab === "symbol" ? (
              <SymbolLookup repo={repo} name={symbol} onName={setSymbol} />
            ) : tab === "calls" ? (
              <CallTrace repo={repo} symbol={traced} onSymbol={setTraced} follow={follow} />
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

/** What each mode is looking for, said where the person typing can read it. */
const SEARCH_LABELS: Record<SearchMode, string> = {
  symbol: "符号名（按字面匹配，括号点号都不用转义）",
  keyword: "关键词（驼峰会拆开，记不清确切拼写时用这个）",
  text: "源码关键词",
  regex: "符号名正则（写坏了会直接告诉你坏在哪）",
};

function CodeSearch({ repo, follow }: { repo: string | null; follow: Follow }) {
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
          <Field label={SEARCH_LABELS[mode]}>
            <Input value={draft} onChange={(event) => setDraft(event.target.value)} />
          </Field>
        </div>
        <Field label="方式">
          <Segmented
            value={mode}
            options={[
              { value: "symbol", label: "符号" },
              { value: "keyword", label: "关键词" },
              { value: "text", label: "全文" },
              { value: "regex", label: "正则" },
            ]}
            onChange={setMode}
          />
        </Field>
        <Button tone="primary" type="submit" disabled={query.running}>
          搜索
        </Button>
      </form>
      <CodeAnswer answer={query.result} loading={query.running} error={query.error} idle="输入检索词">
        {(payload) =>
          mode === "text" ? (
            <TextMatchesView payload={payload} onRead={follow.read} onTrace={follow.trace} />
          ) : (
            <SymbolMatchesView payload={payload} onRead={follow.read} onTrace={follow.trace} />
          )
        }
      </CodeAnswer>
    </>
  );
}

function SymbolLookup({
  repo,
  name,
  onName,
}: {
  repo: string | null;
  name: string;
  onName: (one: string) => void;
}) {
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
          <Field label="canonical_qn（由符号搜索得到，不是页面上显示的短名）">
            <Input
              value={name}
              placeholder="knowledge_base.docs.notes.parse_learning"
              onChange={(event) => onName(event.target.value)}
            />
          </Field>
        </div>
        <Button tone="primary" type="submit" disabled={query.running}>
          读取
        </Button>
      </form>
      <CodeAnswer answer={query.result} loading={query.running} error={query.error} idle="输入限定名">
        {(payload) => <SourceTextView payload={payload} />}
      </CodeAnswer>
    </>
  );
}

function CallTrace({
  repo,
  symbol,
  onSymbol,
  follow,
}: {
  repo: string | null;
  symbol: string;
  onSymbol: (one: string) => void;
  follow: Follow;
}) {
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
          <Field label="起点符号的 canonical_qn">
            <Input value={symbol} onChange={(event) => onSymbol(event.target.value)} />
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
      <CodeAnswer
        answer={query.result}
        loading={query.running}
        error={query.error}
        idle="输入起点符号"
      >
        {(payload) => (
          <CallChainView payload={payload} onRead={follow.read} onTrace={follow.trace} />
        )}
      </CodeAnswer>
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
