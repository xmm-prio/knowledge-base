# 知识库网页端

面向团队内部工程师的浏览与维护界面。后端是同仓库的 FastAPI（`/api`），本目录只负责浏览器这一侧。

## 开发

```bash
npm install
npm run dev          # http://localhost:5173，/api 代理到 127.0.0.1:8000
npm run build        # 产物落在 dist/
npm run typecheck    # 等价于 tsc --noEmit
```

后端以 StaticFiles 挂载 `dist/` 并做 SPA fallback，所以：

- `vite.config.ts` 里 `base: "./"`，资源一律相对路径；
- 路由用 HashRouter，无论挂在站点根还是子路径都不需要服务端配合；
- API 前缀由 `index.html` 实际被服务的目录推导，同样不写死。

## 目录

```text
src/
├── api/          REST 契约的类型与唯一的请求出口
├── app/          外壳：导航、页面框架、路由
├── components/   跨页面的展示件（代码域信封、未知结构 JSON）
├── editor/       CodeMirror 6 与语义 Markdown 的高亮装饰
├── hooks/        取数三态、作者身份
├── pages/        六个页面
├── semantic/     语义 Markdown 的识别与渲染
├── styles/       设计令牌与全局样式
└── ui/           设计原语（按钮、卡片、空/错/载状态……）
```

## 两条硬约束

**编辑器是源码编辑器，不是所见即所得**（见 `docs/adr/0005`）。观察写作 `- [类别] 内容`，
而 `[类别]` 在 CommonMark 里是合法的 shortcut reference link，任何「重新序列化整个文件」的
编辑器都会把它转义成 `- \[类别]`。这里编辑的是原始文本，语义高亮只是叠加在文本上的装饰层，
一个字节都不改；保存时把 `sliceDoc()` 的结果原样 PUT 回去。

**代码域的 payload 形状未经确证**。它是上游二进制的 JSON 原样透传，网关刻意不做整形。
`components/PayloadView.tsx` 因此按形状（对象、数组、表格状数组、标量、内嵌 JSON 字符串）
递归渲染，从不假设字段名，并始终留一个「查看原始 JSON」。
