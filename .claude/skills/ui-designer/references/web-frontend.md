# Web 前端实现设计参考

首版只关注能指导编码的必要差异，不建立完整 Web 设计体系。

## 识别线索

- React、Vue、Angular、Svelte。
- HTML、CSS、路由、浏览器、H5、管理后台。
- `pages/`、`routes/`、`components/`、`views/`、`store/`、`api/`、`styles/`。

## 实现设计要点

| 项 | 需要说明 |
|----|---------|
| 页面载体 | route、page、view、layout、modal、drawer |
| 组件拆分 | 新增组件、复用组件、组件 props、事件回调 |
| 状态管理 | local state、form state、global store、query cache |
| 数据映射 | UI 字段到 API DTO、表单字段、枚举值、默认值 |
| 样式策略 | 复用现有 CSS class、design token、组件库主题 |
| 响应式 | 最小宽度、滚动区域、折行、移动端是否适配 |
| 交互事件 | click、change、submit、cancel、route navigation |
| 验证方式 | component test、E2E、Storybook、手工浏览器验收 |

## 边界

- 不为单个需求引入新的组件库或视觉体系。
- 不擅自调整全局主题、路由结构或布局框架。
- UI 稿未覆盖状态时，优先复用现有加载、空态、错误态模式。
