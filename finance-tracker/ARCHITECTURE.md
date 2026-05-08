# 个人财务记账系统 - 技术架构文档

## 1. 系统架构

### 1.1 架构模式
采用单页面应用（SPA）架构，使用原生JavaScript实现模块化开发。

### 1.2 目录结构
```
finance-tracker/
├── index.html          # 主页面
├── css/
│   └── style.css       # 样式文件
├── js/
│   ├── app.js          # 应用入口和初始化
│   ├── data.js         # 数据管理和存储
│   ├── ui.js           # UI组件渲染
│   ├── router.js       # 路由管理
│   ├── charts.js       # 图表渲染
│   └── utils.js        # 工具函数
├── assets/
│   └── icons/          # 图标资源
└── data/               # 预留数据目录
```

## 2. 模块设计

### 2.1 数据层 (data.js)
**职责**：
- LocalStorage 读写操作
- 数据模型定义和验证
- 数据增删改查接口
- 账户余额自动计算

**核心功能**：
```javascript
class DataStore {
  // 账户管理
  createAccount(data)      // 创建账户
  updateAccount(id, data)  // 更新账户
  deleteAccount(id)        // 删除账户
  getAccounts()            // 获取所有账户
  getAccountBalance(id)    // 计算账户余额

  // 流水管理
  createTransaction(data)     // 创建流水
  updateTransaction(id, data)  // 更新流水
  deleteTransaction(id)        // 删除流水
  getTransactions(filters)    // 获取流水（支持筛选）

  // 统计计算
  getStatistics(dateRange)    // 统计数据
  getCategoryStats(dateRange, type)  // 分类统计
}
```

### 2.2 UI层 (ui.js)
**职责**：
- 各功能模块的DOM渲染
- 表单验证和提交处理
- 事件绑定和交互响应
- 模态框和提示消息管理

**核心组件**：
- Header 组件
- Sidebar 账户列表组件
- AccountCard 账户卡片组件
- TransactionList 流水列表组件
- TransactionForm 流水表单组件
- StatisticsPanel 统计面板组件
- FilterPanel 筛选面板组件
- Modal 模态框组件

### 2.3 路由层 (router.js)
**职责**：
- 页面路由管理
- 页面状态切换
- 浏览器历史记录管理

**路由配置**：
- `#/accounts` - 账户管理页面
- `#/transactions` - 流水记录页面
- `#/statistics` - 统计分析页面

### 2.4 图表层 (charts.js)
**职责**：
- 使用 Chart.js 绑定统计数据
- 饼图、柱状图、折线图渲染
- 图表交互和数据更新

### 2.5 工具层 (utils.js)
**职责**：
- UUID生成
- 日期格式化
- 金额格式化
- 表单验证
- 字符串处理

## 3. 数据流

### 3.1 数据写入流程
用户操作 → UI事件 → 表单验证 → DataStore写入 → LocalStorage持久化 → UI更新

### 3.2 数据读取流程
页面加载 → DataStore初始化 → LocalStorage读取 → 内存缓存 → UI渲染

### 3.3 账户余额计算逻辑
```
账户余额 = 初始余额 + Σ(收入流水) - Σ(支出流水)
```

## 4. 存储策略

### 4.1 LocalStorage Key设计
- `finance_accounts` - 账户数据
- `finance_transactions` - 流水数据
- `finance_settings` - 用户设置

### 4.2 数据序列化
使用 JSON.stringify() 和 JSON.parse() 进行序列化和反序列化

### 4.3 数据迁移
预留版本字段，支持未来数据结构升级

## 5. 安全性考虑

### 5.1 输入验证
- 所有用户输入进行XSS过滤
- 金额格式严格校验
- 日期格式验证

### 5.2 数据隔离
- 数据存储在用户本地浏览器
- 不涉及网络传输
- 不存在跨用户数据泄露

## 6. 性能优化

### 6.1 渲染优化
- 使用 DocumentFragment 批量DOM操作
- 虚拟列表优化长流水列表
- 防抖处理搜索输入

### 6.2 存储优化
- 增量更新，避免全量重写
- 定期清理过期数据（可选）

### 6.3 缓存策略
- 内存缓存常用数据
- 页面切换保持状态

## 7. 兼容性

### 7.1 浏览器支持
- Chrome 80+
- Firefox 75+
- Safari 13+
- Edge 80+

### 7.2 响应式断点
- Desktop: > 1024px
- Tablet: 768px - 1024px
- Mobile: < 768px

## 8. 部署方式

### 8.1 静态部署
- 可直接部署到任意静态服务器
- 支持 file:// 协议本地打开
- 支持 GitHub Pages、Vercel、Netlify 等平台

### 8.2 无需构建
- 纯原生实现，无需打包工具
- CDN引入外部依赖
