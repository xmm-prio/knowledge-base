/**
 * The tag cloud, and the drill-down it exists for.
 *
 * Size maps to count on a square-root curve rather than a linear one: a tag used forty times
 * should read as bigger than one used four, not ten times bigger, or one popular tag swallows
 * the page.
 */

import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Tag as TagCount } from "../api/types";
import { Page } from "../app/Shell";
import { useAsync } from "../hooks/useAsync";
import { routes } from "../routes";
import { Button, Card, Empty, ErrorNotice, Loading, Panel, Tag, TagRow } from "../ui";
import css from "./tags.module.css";

const MIN_SIZE = 12;
const MAX_SIZE = 30;

function sizes(tags: TagCount[]): (count: number) => number {
  const most = Math.max(1, ...tags.map((one) => one.count));
  const least = Math.min(...tags.map((one) => one.count), 1);
  const span = Math.sqrt(most) - Math.sqrt(least) || 1;
  return (count) =>
    MIN_SIZE + ((Math.sqrt(count) - Math.sqrt(least)) / span) * (MAX_SIZE - MIN_SIZE);
}

export function TagsPage() {
  const [params, setParams] = useSearchParams();
  const selected = params.get("tag");

  const cloud = useAsync(() => api.tags(), []);
  const documents = useAsync(selected ? () => api.documents(selected) : null, [selected]);
  const size = useMemo(() => sizes(cloud.data?.tags ?? []), [cloud.data]);

  return (
    <Page title="标签云" lead="字号按使用次数映射；点一个标签看它下面的文档。">
      <div className={css.layout}>
        <Card>
          {cloud.loading ? (
            <Loading />
          ) : cloud.error ? (
            <ErrorNotice error={cloud.error} />
          ) : cloud.data?.tags.length ? (
            <div className={css.cloud}>
              {cloud.data.tags.map((one) => (
                <Link
                  key={one.tag}
                  to={routes.tags(one.tag)}
                  className={`${css.tag} ${one.tag === selected ? css.tagOn : ""}`}
                  style={{ fontSize: `${size(one.count).toFixed(1)}px` }}
                >
                  #{one.tag}
                  <span className={css.tagCount}>{one.count}</span>
                </Link>
              ))}
            </div>
          ) : (
            <Empty title="还没有任何标签" hint="标签写在 frontmatter 的 tags 里，或跟在观察末尾。" />
          )}
        </Card>

        <Panel
          title={selected ? `#${selected}` : "文档"}
          actions={
            selected ? (
              <Button small tone="ghost" onClick={() => setParams({})}>
                清除筛选
              </Button>
            ) : undefined
          }
        >
          {!selected ? (
            <Empty title="选一个标签" hint="左侧点击即可钻取。" />
          ) : documents.loading ? (
            <Loading />
          ) : documents.error ? (
            <ErrorNotice error={documents.error} />
          ) : documents.data?.documents.length ? (
            <div className={css.list}>
              {documents.data.documents.map((one) => (
                <article key={one.path} className={css.row}>
                  <Link className={css.rowTitle} to={routes.documents(one.path)}>
                    {one.title || one.path}
                  </Link>
                  <span className={css.rowPath}>{one.path}</span>
                  {one.summary ? <span className={css.rowSummary}>{one.summary}</span> : null}
                  {one.tags.length ? (
                    <TagRow>
                      {one.tags.map((tag) => (
                        <Tag key={tag} to={routes.tags(tag)} accent={tag === selected}>
                          #{tag}
                        </Tag>
                      ))}
                    </TagRow>
                  ) : null}
                </article>
              ))}
            </div>
          ) : (
            <Empty title="这个标签下没有文档" />
          )}
        </Panel>
      </div>
    </Page>
  );
}
