/**
 * A document, rendered.
 *
 * Prose goes through remark; observation and relation lines are lifted out first and drawn
 * as their own rows, so the two syntaxes that make a document machine-readable are the two
 * things a reader can actually see and click.
 */

import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Link as RouterLink } from "react-router-dom";
import type { Neighbourhood, Observation } from "../api/types";
import { routes } from "../routes";
import type { PluggableList } from "unified";
import { remarkWikiLink, type WikiLinkOptions } from "./remarkWikiLink";
import { segment, stripFrontmatter, type ParsedRelation } from "./syntax";
import css from "./semantic.module.css";

/** Name-to-path for every WikiLink the backend managed to resolve for this document. */
export function resolvedTargets(neighbourhood: Neighbourhood | null): Map<string, string> {
  const resolved = new Map<string, string>();
  for (const link of neighbourhood?.links ?? []) {
    if (link.target) resolved.set(link.target_name, link.target);
  }
  for (const document of neighbourhood?.documents ?? []) {
    if (!resolved.has(document.title)) resolved.set(document.title, document.path);
  }
  return resolved;
}

const CATEGORY_TONES: Record<string, string> = {
  pitfall: css.categoryPitfall,
  gotcha: css.categoryPitfall,
  bug: css.categoryPitfall,
  verified: css.categoryVerified,
  fact: css.categoryVerified,
  decision: css.categoryDecision,
  idea: css.categoryDecision,
  question: css.categoryWarn,
  todo: css.categoryWarn,
};

export function CategoryMark({ category }: { category: string }) {
  const tone = CATEGORY_TONES[category.toLowerCase()] ?? "";
  return <span className={`${css.category} ${tone}`}>{category}</span>;
}

export function ObservationRow({ item }: { item: Observation }) {
  return (
    <li className={css.observation}>
      <CategoryMark category={item.category} />
      <span className={css.content}>
        {item.content}
        {item.tags.length ? (
          <span className={css.obsTags}>
            {item.tags.map((tag) => (
              <RouterLink key={tag} className={css.obsTag} to={routes.tags(tag)}>
                #{tag}
              </RouterLink>
            ))}
          </span>
        ) : null}
      </span>
    </li>
  );
}

function RelationRow({ item, resolved }: { item: ParsedRelation; resolved: Map<string, string> }) {
  const path = resolved.get(item.target) ?? null;
  return (
    <li className={css.relation}>
      <span className={css.relationType}>{item.type}</span>
      {path ? (
        <RouterLink to={routes.documents(path)}>{item.target}</RouterLink>
      ) : (
        <span className={css.missing} title="尚未创建">
          {item.target}
        </span>
      )}
    </li>
  );
}

/** Observations regrouped by category, for readers scanning for one kind of fact. */
export function ObservationsByCategory({ observations }: { observations: Observation[] }) {
  const groups = useMemo(() => {
    const byCategory = new Map<string, Observation[]>();
    for (const item of observations) {
      const bucket = byCategory.get(item.category);
      if (bucket) bucket.push(item);
      else byCategory.set(item.category, [item]);
    }
    return [...byCategory.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [observations]);

  return (
    <div className={css.groups}>
      {groups.map(([category, items]) => (
        <section key={category}>
          <header className={css.groupHead}>
            <CategoryMark category={category} />
            <span className={css.groupCount}>{items.length} 条</span>
          </header>
          <ul className={css.observations}>
            {items.map((item, index) => (
              <ObservationRow key={`${item.content}-${index}`} item={item} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

export function DocumentBody({
  text,
  neighbourhood,
}: {
  text: string;
  neighbourhood: Neighbourhood | null;
}) {
  const resolved = useMemo(() => resolvedTargets(neighbourhood), [neighbourhood]);
  const segments = useMemo(() => segment(stripFrontmatter(text)), [text]);
  const plugins: PluggableList = useMemo(
    () => [
      remarkGfm,
      [
        remarkWikiLink,
        {
          resolve: (name: string) => resolved.get(name) ?? null,
          href: (path: string) => `#${routes.documents(path)}`,
        } satisfies WikiLinkOptions,
      ],
    ],
    [resolved],
  );

  if (!segments.length) {
    return <div className={css.prose}>（这篇文档是空的）</div>;
  }

  return (
    <div className={css.prose}>
      {segments.map((part, index) => {
        if (part.kind === "markdown") {
          return (
            <ReactMarkdown key={index} remarkPlugins={plugins}>
              {part.text}
            </ReactMarkdown>
          );
        }
        if (part.kind === "observations") {
          return (
            <ul key={index} className={css.observations}>
              {part.items.map((item, at) => (
                <ObservationRow key={at} item={item} />
              ))}
            </ul>
          );
        }
        return (
          <ul key={index} className={css.relations}>
            {part.items.map((item, at) => (
              <RelationRow key={at} item={item} resolved={resolved} />
            ))}
          </ul>
        );
      })}
    </div>
  );
}
