# Issue 追踪：本地 Markdown

本仓库的 Issue 和规格使用 `.scratch/` 中的 Markdown 文件管理。

## 约定

- 每个功能对应一个目录：`.scratch/<功能-slug>/`。
- 规格文件为：`.scratch/<功能-slug>/spec.md`。
- 实施 Issue 每个文件一项：`.scratch/<功能-slug>/issues/<NN>-<slug>.md`，从 `01` 开始编号；不要将多个工单合并到一个文件。
- Triage 状态写在 Issue 文件顶部附近的 `Status:` 行；角色字符串见 `triage-labels.md`。
- 评论与沟通记录追加在文件末尾的 `## Comments` 标题下。

## 当技能要求“发布到 Issue 追踪器”

在 `.scratch/<功能-slug>/` 中创建新文件；目录不存在时同时创建。

## 当技能要求“获取相关工单”

读取所引用路径的文件。用户通常会直接给出文件路径或 Issue 编号。

## Wayfinding 操作

供 `/wayfinder` 使用：一个 map 文件对应多个子工单文件。

- **Map**：`.scratch/<工作项>/map.md`，保存 Notes、Decisions-so-far 和 Fog 内容。
- **子工单**：`.scratch/<工作项>/issues/NN-<slug>.md`，从 `01` 编号；正文包含问题。顶部 `Type:` 行记录类型（`research`、`prototype`、`grilling`、`task`），`Status:` 行记录 `claimed` 或 `resolved`。
- **阻塞关系**：在顶部附近使用 `Blocked by: NN, NN`；列出的所有工单均为 `resolved` 后，该工单解除阻塞。
- **待处理队列**：扫描 `.scratch/<工作项>/issues/`，选择开放、未阻塞、未认领的工单，编号最小者优先。
- **认领**：开始工作前，将 `Status: claimed` 写入并保存。
- **解决**：在 `## Answer` 标题下追加答案，将 `Status: resolved`，再将上下文指针（gist 与链接）追加到 `map.md` 的 Decisions-so-far。
