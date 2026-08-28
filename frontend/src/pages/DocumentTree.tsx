/** The folder tree. `knowledge/` and `learnings/` are always the two roots, even when empty. */

import { useState } from "react";
import { Link } from "react-router-dom";
import type { TreeNode } from "../api/types";
import { routes } from "../routes";
import css from "./documents.module.css";

function countDocuments(node: TreeNode): number {
  return node.documents.length + node.directories.reduce((sum, one) => sum + countDocuments(one), 0);
}

function Folder({
  node,
  selected,
  depth,
}: {
  node: TreeNode;
  selected: string | null;
  depth: number;
}) {
  const holdsSelection = selected?.startsWith(`${node.path}/`) ?? false;
  const [open, setOpen] = useState(depth === 0 || holdsSelection);
  const total = countDocuments(node);

  return (
    <div className={css.node}>
      <button type="button" className={css.folder} onClick={() => setOpen((was) => !was)}>
        <span className={css.caret}>{open ? "▾" : "▸"}</span>
        <span className={css.label}>{node.name}</span>
        <span className={css.count}>{total}</span>
      </button>
      {open ? (
        <div className={css.children}>
          {node.directories.map((child) => (
            <Folder key={child.path} node={child} selected={selected} depth={depth + 1} />
          ))}
          {node.documents.map((document) => (
            <Link
              key={document.path}
              to={routes.documents(document.path)}
              title={document.summary || document.path}
              className={`${css.leaf} ${document.path === selected ? css.leafOn : ""}`}
            >
              <span className={css.caret} />
              <span className={css.label}>{document.title || document.path.split("/").pop()}</span>
            </Link>
          ))}
          {!node.directories.length && !node.documents.length ? (
            <div className={`${css.leaf} ${css.leafFlat}`}>
              <span className={css.caret} />
              <span className={css.label}>（空）</span>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function DocumentTree({ roots, selected }: { roots: TreeNode[]; selected: string | null }) {
  return (
    <>
      {roots.map((root) => (
        <Folder key={root.path} node={root} selected={selected} depth={0} />
      ))}
    </>
  );
}
