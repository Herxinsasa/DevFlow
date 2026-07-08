# Qt 前端实现设计参考

首版只关注能指导编码的必要差异，不建立完整 Qt UI 设计体系。

## 识别线索

- Qt Widgets：`QWidget`、`QDialog`、`QMainWindow`、`QTableView`、`.ui`、QSS、信号槽。
- Qt QML：`.qml`、Qt Quick、`property`、`Signal`、`Component`、`Loader`。
- 桌面客户端、工具软件、工控界面。

## 实现设计要点

| 项 | Qt Widgets | Qt QML |
|----|------------|--------|
| 页面载体 | QMainWindow、QDialog、QWidget、tab page | QML Page、Component、Dialog、Popup |
| 组件拆分 | 复用现有 QWidget/Dialog，明确是否改 `.ui` | 复用现有 QML Component，明确 property 和 signal |
| 状态管理 | model/view、成员变量、信号槽 | property、binding、model、signal handler |
| 数据映射 | UI 控件到配置项、DTO、业务对象 | QML property 到 C++/JS model 或接口字段 |
| 样式策略 | 复用 QSS、资源文件、控件样式 | 复用主题变量、qml 样式组件、资源 |
| 交互事件 | signal/slot、event filter、button clicked | onClicked、onChanged、signal handler |
| 线程约束 | UI 更新必须回到主线程 | UI property 更新注意线程边界 |
| 验证方式 | 手工桌面验收、Qt Test、截图对比 | 手工验收、QML Test、截图对比 |

## 边界

- 不为单个需求重构窗口框架或主导航。
- 不擅自改变现有 `.ui` 文件结构、对象名和信号槽连接方式。
- 不在 UI 线程执行耗时逻辑。
- UI 稿未覆盖桌面分辨率时，至少说明最小窗口尺寸、滚动和溢出策略。
