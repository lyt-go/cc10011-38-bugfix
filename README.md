# 实时指标计算与监控大盘平台

面向实时指标计算引擎、多维度下钻分析、告警阈值管理、指标异常检测、数据服务开放与可视化看板配置的数据分析与应用工程平台。

这是一个前后端分离的管理平台：前端 React + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 React + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 实时指标 | `realtimemetric` | 指标定义 | 指标编号、指标名称、计算窗口秒 |
| 监控大盘 | `dashboard` | 大盘配置 | 大盘编号、大盘名称、包含指标组 |
| 多维下钻 | `drilldown` | 下钻路径 | 路径编号、起始维度、下钻层级序列 |
| 阈值管理 | `threshold` | 阈值规则 | 规则编号、关联指标、阈值下限 |
| 异常检测 | `anomalydetect` | 检测模型 | 模型编号、监控指标、检测算法 |
| 数据服务 | `dataservice` | 服务接口 | 服务编号、服务名称、接口路径 |
| 告警历史 | `alarmhistory` | 告警记录 | 记录编号、告警规则、触发时间 |
| 同比环比 | `comparison` | 对比配置 | 配置编号、目标指标、对比类型 |
| 聚合配置 | `aggregate` | 聚合规则 | 规则编号、源数据粒度、目标粒度 |
| 筛选预设 | `filterpreset` | 预设模板 | 预设编号、预设名称、维度条件组 |
| 用户洞察 | `userinsight` | 洞察报告 | 报告编号、分析主题、目标人群 |
| 事件分析 | `eventanalysis` | 分析模型 | 模型编号、事件名称、分组维度 |
| 分群画像 | `segmentprofile` | 画像定义 | 画像编号、分群名称、筛选规则 |
| 趋势预测 | `trendforecast` | 预测方案 | 方案编号、预测指标、算法模型 |
| 可视化模板 | `viztemplate` | 图表模板 | 模板编号、图表类型、数据绑定 |
| 订阅推送 | `subscription` | 订阅配置 | 订阅编号、订阅内容、接收人 |
| 维度映射 | `dimensionmap` | 映射规则 | 规则编号、原始维度名、标准维度名 |
| 数据质量分 | `qualityscore` | 评分规则/评分快照 | 规则编号、数据集名称、完整性/准确性/时效性/一致性权重、准入门槛、规则版本、维度得分、总分数 |

### 数据质量分链路（评分权重 → 加权总分 → 评分快照 → 服务发布门禁）

- **权重落库**：完整性、准确性、时效性、一致性四项权重全部保存，校验非负且四项之和为 1（或 100）；准入门槛限定 0~100。
- **评分快照**：`GET/POST /api/qualityscore/snapshots` 生成与查询快照，快照冻结规则版本、准入门槛、评分周期（具体周期 + 周期口径）、四项权重与维度得分。前置条件：规则「已启用」、上游聚合数据集已有「已生效」聚合规则、四项维度得分齐全；同一规则同一评分周期只接纳首个通过校验的提交（进程内加锁 + 锁内查重）。
- **版本冲突取舍**：规则的权重/门槛/数据集/周期变更时规则版本递增（v1→v2），历史快照标记「已作废」但保留明细；服务发布门禁只认与当前规则版本、准入门槛同时一致的有效快照。
- **聚合更新重算**：`POST /api/aggregate/{id}/refresh` 更新聚合数据集后，按当前权重重算关联启用规则的维度得分与总分数；历史快照保持冻结，数据更新后旧快照在门禁中判定为「快照已过期」。
- **服务发布门禁**：`POST /api/dataservice/{id}/actions`（上线服务）前强制校验——停用规则不参与、版本/门槛须一致、四项维度得分缺一不可（杜绝「总分合格、维度缺失」的矛盾状态）；通过后把快照编号、规则版本、总分等凭证落库到服务记录。`GET /api/dataservice/{id}` 与 `GET /api/qualityscore/gate/{数据集名称}` 提供两个入口共用的逐规则核对视图。


## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

领域：数据工程
子方向：数据分析与数据应用
