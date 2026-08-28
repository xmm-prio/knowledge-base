/** The frame every page sits in: navigation, and the one identity a write needs. */

import { Suspense, type ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuthor } from "../hooks/useAuthor";
import { routes } from "../routes";
import { Input, Loading } from "../ui";
import css from "./App.module.css";

const NAVIGATION = [
  { to: routes.search(), label: "搜索" },
  { to: routes.documents(), label: "文档" },
  { to: routes.tags(), label: "标签" },
  { to: routes.history(), label: "历史" },
  { to: routes.code(), label: "代码库" },
  { to: routes.system(), label: "系统状态" },
];

export function Shell() {
  const [author, setAuthor] = useAuthor();

  return (
    <div className={css.shell}>
      <nav className={css.nav}>
        <div className={css.brand}>
          <span className={css.brandMark}>知</span>
          <span className={css.brandName}>知识库</span>
        </div>
        {NAVIGATION.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => `${css.navLink} ${isActive ? css.navLinkOn : ""}`}
          >
            {item.label}
          </NavLink>
        ))}
        <div className={css.navSpacer} />
        <div className={css.identity}>
          <span className={css.identityLabel}>当前作者（写入与回滚署名）</span>
          <Input
            value={author}
            placeholder="填写你的名字"
            onChange={(event) => setAuthor(event.target.value)}
          />
        </div>
      </nav>
      <main className={css.main}>
        <div className={css.page}>
          <Suspense fallback={<Loading />}>
            <Outlet />
          </Suspense>
        </div>
      </main>
    </div>
  );
}

export function Page({
  title,
  lead,
  actions,
  children,
  width = "default",
}: {
  title?: ReactNode;
  lead?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  width?: "default" | "wide" | "full";
}) {
  const widthClass = width === "wide" ? css.pageWide : width === "full" ? css.pageFull : "";
  return (
    <div className={`${css.pageInner} ${widthClass}`}>
      {title ? (
        <header className={css.pageHead}>
          <div>
            <h1 className={css.pageTitle}>{title}</h1>
            {lead ? <div className={css.pageLead}>{lead}</div> : null}
          </div>
          {actions}
        </header>
      ) : null}
      {children}
    </div>
  );
}
