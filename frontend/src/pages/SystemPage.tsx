/**
 * What an operator needs to know, and the two buttons that fix most of it.
 *
 * The one thing this page refuses to smooth over is `code.ok === null`. Null means nothing is
 * supervising the upstream, so its health is unknown -- which is not the same as healthy, and
 * a green tick there would be a lie an operator acts on.
 */

import { api } from "../api/client";
import type { StatusReply } from "../api/types";
import { Page } from "../app/Shell";
import { PayloadView } from "../components/PayloadView";
import { useAction, useAsync } from "../hooks/useAsync";
import { Badge, Button, Card, CopyButton, Dot, ErrorNotice, Loading, Panel } from "../ui";
import css from "./system.module.css";

function Stat({ value, label }: { value: number | string; label: string }) {
  return (
    <div className={css.stat}>
      <span className={css.statValue}>{value}</span>
      <span className={css.statLabel}>{label}</span>
    </div>
  );
}

export function SystemPage() {
  const status = useAsync<StatusReply>(() => api.status(), []);
  const reindexDocuments = useAction(() => api.reindexDocuments());
  const reindexCode = useAction(() => api.reindexCode(null));

  if (status.loading) {
    return (
      <Page title="系统状态">
        <Loading />
      </Page>
    );
  }
  if (status.error || !status.data) {
    return (
      <Page title="系统状态">
        <ErrorNotice error={status.error ?? new Error("没有拿到状态")} />
      </Page>
    );
  }

  const { documents, code, mcp } = status.data;

  return (
    <Page
      title="系统状态"
      lead="两个域各自的规模与健康，以及同事把 agent 接过来所需的一切。"
      actions={
        <Button onClick={() => status.reload()} disabled={status.loading}>
          刷新
        </Button>
      }
    >
      <div className={css.cards}>
        <Card>
          <Panel
            title={
              <span className={css.headRow}>
                <Dot tone={documents.ok ? "ok" : "bad"} />
                文档域
              </span>
            }
            note={documents.ok ? "索引正常" : "索引异常"}
          >
            {documents.error ? <ErrorNotice error={new Error(documents.error)} /> : null}
            <div className={css.stats}>
              <Stat value={documents.documents} label="文档" />
              <Stat value={documents.observations} label="观察" />
              <Stat value={documents.tags} label="标签" />
            </div>
            <div className={css.actions}>
              <Button
                disabled={reindexDocuments.running}
                onClick={async () => {
                  await reindexDocuments.run();
                  status.reload();
                }}
              >
                {reindexDocuments.running ? "重建中…" : "重建文档索引"}
              </Button>
              {reindexDocuments.result ? (
                <Badge tone="ok">已重建 {reindexDocuments.result.indexed} 篇</Badge>
              ) : null}
            </div>
            {reindexDocuments.error ? <ErrorNotice error={reindexDocuments.error} /> : null}
          </Panel>
        </Card>

        <Card>
          <Panel
            title={
              <span className={css.headRow}>
                <Dot tone={code.ok === null ? "unknown" : code.ok ? "ok" : "bad"} />
                代码域
              </span>
            }
            note={
              code.ok === null ? "健康状况未知（没有监管进程）" : code.ok ? "上游健康" : "上游异常"
            }
          >
            {code.error ? <ErrorNotice error={new Error(code.error)} /> : null}
            <div className={css.stats}>
              <Stat value={code.repos} label="在盘代码库" />
              <Stat value={code.indexed} label="已索引" />
            </div>
            {code.ok === null ? (
              <div className={css.note}>
                没有进程在监管上游二进制，所以这里既不能说它健康，也不能说它挂了。
              </div>
            ) : null}
            <div className={css.actions}>
              <Button
                disabled={reindexCode.running}
                onClick={async () => {
                  await reindexCode.run();
                  status.reload();
                }}
              >
                {reindexCode.running ? "重建中…" : "重建全部代码索引"}
              </Button>
            </div>
            {reindexCode.error ? <ErrorNotice error={reindexCode.error} /> : null}
            {reindexCode.result ? (
              <div>
                {reindexCode.result.outcomes.map((one) => (
                  <div key={one.repo} className={css.outcome}>
                    <Dot tone={one.ok ? "ok" : "bad"} />
                    <span className={css.outcomeRepo}>{one.repo}</span>
                    <Badge tone={one.ok ? "ok" : "bad"}>{one.ok ? "完成" : "失败"}</Badge>
                  </div>
                ))}
                {reindexCode.result.outcomes.some((one) => !one.ok) ? (
                  <PayloadView
                    payload={reindexCode.result.outcomes.filter((one) => !one.ok)}
                    empty="上游没有说明失败原因"
                  />
                ) : null}
              </div>
            ) : null}
          </Panel>
        </Card>
      </div>

      <Card>
        <Panel title="MCP 接入" note="同事把这段贴进自己的 opencode.json 即可">
          {mcp.error ? (
            <ErrorNotice title="没有可对外提供的地址" error={new Error(mcp.error)} />
          ) : (
            <>
              <div className={css.mcpUrl}>
                <div className={css.url}>{mcp.url}</div>
                <CopyButton text={mcp.url} label="复制地址" />
              </div>
              <pre className={css.config}>{mcp.opencode_config}</pre>
              <div className={css.actions}>
                <CopyButton text={mcp.opencode_config} label="复制 opencode 配置" />
              </div>
              <div className={css.note}>
                地址取自本机默认路由所在网卡的 IPv4，与你用什么主机名打开这个页面无关，
                所以复制走的配置换台机器也仍然指向这里。
              </div>
            </>
          )}
        </Panel>
      </Card>
    </Page>
  );
}
