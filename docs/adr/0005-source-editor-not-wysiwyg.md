# 前端编辑器用 CodeMirror 6 源码编辑，不用所见即所得

网页端的 Markdown 编辑用 CodeMirror 6 加 live-preview 装饰（源文本即真相），只读渲染另走一条 remark 管线。Milkdown、MDXEditor、BlockNote 这类所见即所得编辑器全部被否决。

原因很具体：观察写作 `- [类别] 内容`，而 `[类别]` 在 CommonMark 里是合法的 shortcut reference link 语法，`mdast-util-to-markdown`（所有 remark 系序列化器的底座）在输出时**会把它转义成 `\[类别]`**。语义等价，但文件字节变了——用户改一个错别字就会波及全文，git diff 全是噪音，basic-memory 的观察解析器也大概率不再认得。任何「重新序列化整个文件」的编辑器都逃不掉这一条。

## Consequences

- 网页端的编辑体验是源码级的，不是 Notion 级的。考虑到使用者都是开发者，这个取舍可以接受。
- 所见即所得的诉求如果将来变成硬需求，必须先解决观察行的转义问题（自定义 remark 插件 + 上线前对全部文档做一次批量规范化），代价不小。
