/**
 * Rendering JSON whose shape nobody has confirmed.
 *
 * Everything the code domain returns is the upstream binary's own JSON, passed through
 * verbatim. The gateway deliberately does not reshape it, which means this component may not
 * assume a single field name: the moment it did, an upstream release would turn a working
 * page into a blank one.
 *
 * So it renders by *shape* rather than by schema -- object, array, table-shaped array,
 * scalar, embedded JSON string -- and always keeps the raw JSON one click away, because a
 * structured view of an unknown structure is a convenience, never the source of truth.
 */

import { useMemo, useState, type ReactNode } from "react";
import { Button, CopyButton, Empty } from "../ui";
import css from "./payload.module.css";

type Json = unknown;

const AUTO_EXPAND_DEPTH = 2;
const MAX_AUTO_CHILDREN = 40;
const LONG_STRING = 160;
/** Below this an object array is easier to read as rows than as a table. */
const MIN_TABLE_ROWS = 2;

function isRecord(value: Json): value is Record<string, Json> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isScalar(value: Json): boolean {
  return value === null || (typeof value !== "object" && typeof value !== "function");
}

/**
 * Upstreams that shell out to another process often hand back JSON as a string. Parsing it
 * opportunistically costs nothing and turns an unreadable blob into a tree.
 */
function reparse(value: Json): Json {
  if (typeof value !== "string") return value;
  const text = value.trim();
  if (!(text.startsWith("{") && text.endsWith("}")) && !(text.startsWith("[") && text.endsWith("]"))) {
    return value;
  }
  try {
    return JSON.parse(text) as Json;
  } catch {
    return value;
  }
}

/** An array of flat objects reads far better as a table than as N collapsed nodes. */
function tableColumns(value: Json): string[] | null {
  if (!Array.isArray(value) || value.length < MIN_TABLE_ROWS) return null;
  const columns: string[] = [];
  for (const row of value) {
    if (!isRecord(row)) return null;
    for (const [key, cell] of Object.entries(row)) {
      if (!isScalar(cell)) return null;
      if (!columns.includes(key)) columns.push(key);
    }
  }
  return columns.length && columns.length <= 8 ? columns : null;
}

function describe(value: Json): string {
  if (Array.isArray(value)) return `数组 · ${value.length} 项`;
  if (isRecord(value)) return `对象 · ${Object.keys(value).length} 个字段`;
  if (value === null) return "null";
  return typeof value;
}

function Scalar({ value }: { value: Json }) {
  if (value === null) return <span className={css.nullish}>null</span>;
  if (value === undefined) return <span className={css.nullish}>—</span>;
  if (typeof value === "boolean") return <span className={css.boolean}>{String(value)}</span>;
  if (typeof value === "number") return <span className={css.number}>{value}</span>;
  const text = String(value);
  if (text.includes("\n") || text.length > LONG_STRING) {
    return <div className={`${css.block} ${css.string}`}>{text}</div>;
  }
  return <span className={css.string}>{text}</span>;
}

function Table({ rows, columns }: { rows: Record<string, Json>[]; columns: string[] }) {
  return (
    <table className={css.table}>
      <thead>
        <tr>
          {columns.map((column) => (
            <th key={column}>{column}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index}>
            {columns.map((column) => (
              <td key={column}>
                <Scalar value={row[column]} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Node({ label, value, depth }: { label: ReactNode; value: Json; depth: number }) {
  const resolved = useMemo(() => reparse(value), [value]);
  const entries: [ReactNode, Json][] | null = Array.isArray(resolved)
    ? resolved.map((item, index) => [<span className={css.index}>[{index}]</span>, item])
    : isRecord(resolved)
      ? Object.entries(resolved).map(([key, item]) => [<span className={css.key}>{key}</span>, item])
      : null;

  const columns = useMemo(() => tableColumns(resolved), [resolved]);
  const [open, setOpen] = useState(
    depth < AUTO_EXPAND_DEPTH && (entries?.length ?? 0) <= MAX_AUTO_CHILDREN,
  );

  if (!entries) {
    return (
      <div className={css.row}>
        <span className={css.toggle} />
        {label}
        <Scalar value={resolved} />
      </div>
    );
  }

  if (!entries.length) {
    return (
      <div className={css.row}>
        <span className={css.toggle} />
        {label}
        <span className={css.meta}>{Array.isArray(resolved) ? "（空数组）" : "（空对象）"}</span>
      </div>
    );
  }

  return (
    <div>
      <div className={css.row}>
        <button
          type="button"
          className={css.toggle}
          onClick={() => setOpen((was) => !was)}
          aria-label={open ? "折叠" : "展开"}
        >
          {open ? "▾" : "▸"}
        </button>
        {label}
        <span className={css.meta}>{describe(resolved)}</span>
      </div>
      {open ? (
        <div className={css.children}>
          {columns ? (
            <Table rows={resolved as Record<string, Json>[]} columns={columns} />
          ) : (
            entries.map(([key, item], index) => (
              <Node key={index} label={key} value={item} depth={depth + 1} />
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}

export function PayloadView({ payload, empty = "上游没有返回内容" }: { payload: Json; empty?: string }) {
  const [raw, setRaw] = useState(false);
  const text = useMemo(() => {
    try {
      return JSON.stringify(payload, null, 2) ?? String(payload);
    } catch {
      return String(payload);
    }
  }, [payload]);

  if (payload === null || payload === undefined || text === "{}" || text === "[]") {
    return <Empty title={empty} />;
  }

  return (
    <div className={css.wrap}>
      <div className={css.bar}>
        <span className={css.shape}>{describe(reparse(payload))}</span>
        <span className={css.barActions}>
          <Button small onClick={() => setRaw((was) => !was)}>
            {raw ? "结构化视图" : "查看原始 JSON"}
          </Button>
          <CopyButton small text={text} label="复制 JSON" />
        </span>
      </div>
      {raw ? (
        <pre className={css.raw}>{text}</pre>
      ) : (
        <div className={css.tree}>
          <Node label={null} value={payload} depth={0} />
        </div>
      )}
    </div>
  );
}
