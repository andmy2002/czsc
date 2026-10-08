# CZSC 缠论量化平台 — 网站化与股票系统对接实施指南

> 适用版本：czsc ≥ 1.0（Rust + PyO3 混合架构）
> 编写日期：2026-10-08
> 基于：docs/examples/ 全部示例实跑验证 + 项目源码 + [docs/public_api.md](file:///workspace/docs/public_api.md)

本文档面向"用 czsc 搭建一个可对接真实股票行情的网站"的开发者，按"架构认知 → 环境搭建 → 数据对接 → 分析链路 → 网站化设计 → 部署运维 → 避坑"的顺序组织。

---

## 目录

1. [项目架构总览](#1-项目架构总览)
2. [开发环境搭建](#2-开发环境搭建)
3. [数据源对接（核心）](#3-数据源对接核心)
4. [缠论分析核心链路](#4-缠论分析核心链路)
5. [信号-事件-交易体系](#5-信号-事件-交易体系)
6. [策略与回测](#6-策略与回测)
7. [可视化与 HTML 产物](#7-可视化与-html-产物)
8. [网站化架构设计](#8-网站化架构设计)
9. [股票系统对接实施](#9-股票系统对接实施)
10. [部署与运维](#10-部署与运维)
11. [最佳实践与避坑指南](#11-最佳实践与避坑指南)
12. [快速启动 Checklist](#12-快速启动-checklist)

---

## 1. 项目架构总览

### 1.1 Rust + Python 混合架构

czsc 1.0 采用 **Rust 核心 + Python 门面** 的混合架构：

```
┌───────────────────────────────────────────────────────┐
│                    Python 层（门面/工具）                 │
│  czsc.traders · czsc.strategies · czsc.research        │
│  czsc.connectors · czsc.utils · czsc.fsa               │
└───────────────────────┬───────────────────────────────┘
                        │ PyO3 扩展（czsc._native）
┌───────────────────────▼───────────────────────────────┐
│                    Rust 层（核心算法）                    │
│  czsc-core（缠论对象与识别）                              │
│  czsc-signals（220+ 信号函数）                          │
│  czsc-trader（CzscTrader/Event/Position）               │
│  czsc-ta（TA 算子） · czsc-utils（BarGenerator）        │
└───────────────────────────────────────────────────────┘
```

- **Rust workspace**：9 个 crate（[Cargo.toml](file:///workspace/Cargo.toml)），缠论识别、信号、交易器全部在 Rust 实现
- **Python 扩展**：`czsc._native`，由 [crates/czsc-python](file:///workspace/crates/czsc-python) 通过 maturin 打包
- **Python 端**：只做透传 + 不可避免的 PyO3 边界胶水（DataFrame ↔ Arrow、Path ↔ String），**禁止写适配层**（[CLAUDE.md](file:///workspace/CLAUDE.md) 开发宪法第一条）

### 1.2 核心模块速查

| 模块 | 职责 | 关键 API |
|---|---|---|
| `czsc._native` | Rust 扩展，缠论核心 | `CZSC`, `FX`, `BI`, `ZS`, `BarGenerator`, `Freq` |
| `czsc.traders` | 交易器与信号管理 | `CzscTrader`, `CzscSignals`, `generate_czsc_signals`, `get_signals_config` |
| `czsc.strategies` | 策略门面 | `CzscStrategyBase`, `CzscJsonStrategy` |
| `czsc.research` | 回测/研究入口 | `run_research`, `run_replay`, `run_optimize_batch` |
| `czsc.connectors` | 数据源连接器 | `ts_connector`(Tushare), `tq_connector`(天勤), `ccxt_connector`(CCXT), `local_data` |
| `czsc.utils` | 工具集 | 缓存/IO/绘图/交易工具 |
| `czsc.mock` | 模拟数据 | `generate_symbol_kines`, `generate_klines_with_weights` |
| `czsc.envs` | 环境变量 | `get_min_bi_len`, `get_max_bi_num`, `get_verbose` |

### 1.3 核心数据结构

| 结构 | 说明 |
|---|---|
| `RawBar` | 原始 K 线（symbol/dt/open/close/high/low/vol/amount/freq） |
| `NewBar` | 去包含关系后的 K 线 |
| `FX` | 分型（顶/底），含 power_str、power_volume |
| `BI` | 笔，含 direction、power、slope、SNR、rsq、angle |
| `ZS` | 中枢，含 zd/zg（区间）、zz（中轴）、dd/gg（极值） |
| `Signal` | 信号，格式 `{freq}_{k2}_{k3}_{v1}_{v2}_{v3}_{score}` |
| `Event` | 信号逻辑组合（signals_all/any/not + operate） |
| `Position` | 持仓策略（opens/exits + 风控参数） |

---

## 2. 开发环境搭建

### 2.1 系统要求

- Python ≥ 3.10（pyo3 0.22 硬约束）
- Rust 工具链（从源码构建时需要）
- 推荐用 `uv` 管理依赖

### 2.2 安装

**方式一：PyPI 预编译（推荐生产）**

```bash
pip install czsc -U          # 或 uv pip install czsc
```

**方式二：源码构建（开发）**

```bash
git clone https://github.com/waditu/czsc.git
cd czsc
uv sync --extra dev
maturin develop --release
```

### 2.3 Rust 构建 OOM 问题（实测踩坑）

沙箱内存 5.8G / 无 swap 时，release 默认配置（`lto=true` + `codegen-units=1` + `opt-level=3`）会被 SIGKILL。临时降级即可（不修改源码）：

```bash
CARGO_PROFILE_RELEASE_LTO=false \
CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16 \
CARGO_PROFILE_RELEASE_OPT_LEVEL=1 \
uv sync --extra dev
```

生产构建建议在 16G+ 内存机器上跑默认 release 配置以获得最优性能。

### 2.4 验证安装

```python
import czsc
print(czsc.__version__)        # 1.0.1
from czsc import CZSC, Freq
from czsc.mock import generate_symbol_kines
```

### 2.5 常用开发命令

```bash
uv sync --extra dev                          # 同步依赖
maturin develop                              # 构建 Rust 扩展
uv run --no-sync pytest                      # 跑测试
uv run --no-sync pytest --run-slow           # 含慢测试
uv run --no-sync ruff format czsc/ tests/    # 格式化
uv run --no-sync ruff check czsc/ tests/     # lint
```

---

## 3. 数据源对接（核心）

这是网站化的第一步：**让 czsc 拿到真实股票数据**。czsc 提供多个现成连接器。

### 3.1 内置连接器一览

| 模块 | 数据源 | 市场 | 说明 |
|---|---|---|---|
| `czsc.connectors.ts_connector` | Tushare | A股/ETF | 需 `TUSHARE_TOKEN` |
| `czsc.connectors.tq_connector` | 天勤 TQSdk | 期货 | 需天勤账号 |
| `czsc.connectors.ccxt_connector` | CCXT | 数字货币 | 多交易所 |
| `czsc.connectors.local_data` | 本地缓存 | 任意 | CZSC 投研共享数据 |

### 3.2 Tushare 接入（A股，最常用）

**步骤 1：获取 Token**

访问 [tushare.pro](https://tushare.pro) 注册，获取 API token（积分决定可调用接口频率，分钟线需 2000+ 积分）。

**步骤 2：设置 Token**

```python
import czsc
# 方式一：通过 czsc 统一数据客户端
czsc.set_url_token(token='你的token', url='http://api.tushare.pro')

# 方式二：环境变量
# export TUSHARE_TOKEN=你的token
```

**步骤 3：拉取 K 线**

```python
from czsc.connectors import ts_connector

# symbol 格式："{ts_code}#{asset}"，asset: E=股票, I=指数, FT=基金
# 日线
bars_d = ts_connector.get_raw_bars(
    symbol="000001.SZ#E",
    freq="日线",
    sdt="20200101", edt="20240101",
    fq="后复权",   # 前复权 / 后复权
    raw_bar=True,
)

# 分钟线（需 Tushare 积分）
bars_30m = ts_connector.get_raw_bars(
    symbol="000001.SZ#E",
    freq="30分钟",
    sdt="20240101", edt="20240601",
    fq="后复权",
)
```

> `get_raw_bars` 返回 `list[RawBar]`，可直接喂给 `CZSC` 或 `BarGenerator`。

**步骤 4：缓存**

Tushare 连接器内置磁盘缓存（`~/.ts_data_cache`，可通过 `TS_CACHE_PATH` 环境变量覆盖），重复请求不重复扣费。

### 3.3 本地数据接入

如果你的股票系统已有自己的行情库，只需保证 K 线 DataFrame 列符合约定：

```python
import pandas as pd
from czsc import Freq, format_standard_kline

# 你的数据库 / API 返回的 DataFrame
df = pd.DataFrame({
    "dt": [...],        # datetime
    "symbol": "000001.SZ",
    "open": [...], "close": [...],
    "high": [...], "low": [...],
    "vol": [...],       # 成交量（股）
    "amount": [...],    # 成交额（元）
})

bars = format_standard_kline(df, freq=Freq.F30)  # 转 list[RawBar]
c = CZSC(bars)
```

### 3.4 自定义数据源

若需接入券商行情（如中泰 XTP、恒生 UFT），写一个适配函数输出 `list[RawBar]` 即可：

```python
from czsc import RawBar, Freq

def your_broker_to_bars(kline_list, symbol, freq) -> list[RawBar]:
    bars = []
    for i, row in enumerate(kline_list):
        bars.append(RawBar(
            symbol=symbol, dt=row['datetime'], id=i, freq=Freq(freq),
            open=row['open'], close=row['close'],
            high=row['high'], low=row['low'],
            vol=int(row['vol']), amount=int(row['amount']),
        ))
    return bars
```

### 3.5 实时行情推送

网站需要实时更新时，推荐架构：

- **行情网关**：用券商 SDK / WebSocket 订阅实时 tick，聚合成分钟 K 线
- **K线推送**：每完成一根 K 线（或 tick 驱动），调用 `czsc_obj.update(bar)` / `trader.update(bar)` 增量推进
- **WebSocket 推送**：把更新后的分析结果（分型/笔/信号/持仓）推送给前端

---

## 4. 缠论分析核心链路

### 4.1 最小分析单元

```python
from czsc import CZSC, Freq, format_standard_kline
from czsc.connectors import ts_connector

bars = ts_connector.get_raw_bars("000001.SZ#E", "30分钟", "20230101", "20240601")
c = CZSC(bars)
print(len(c.fx_list), len(c.bi_list), len(c.zs_list))
```

### 4.2 多周期联立（网站必用）

单看一个周期不够，网站通常需要日线/60分钟/30分钟/5分钟联立：

```python
from czsc import BarGenerator, CzscTrader

bg = BarGenerator(base_freq="5分钟", freqs=["5分钟", "30分钟", "日线"], max_count=5000)
for bar in bars_5m:
    bg.update(bar)

# 各周期 K 线
bars_d = bg.bars["日线"]
bars_30m = bg.bars["30分钟"]
```

### 4.3 增量更新（实盘场景）

```python
c = CZSC(bars[:1])
for bar in bars[1:]:
    c.update(bar)        # 逐根推进，适合实时行情
```

性能参考（20年5分钟 = 36.5万根）：
- CZSC 单周期：~10.4 万 bars/s
- CzscTrader 全链路：~4.7 万 bars/s

### 4.4 关键环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `CZSC_MIN_BI_LEN` | 6 | 最小笔长度 |
| `CZSC_MAX_BI_NUM` | 50 | 单实例保留最大笔数（**注意：会截断历史笔**） |
| `CZSC_VERBOSE` | False | 详细日志 |

> 网站若需展示完整历史笔，调大 `CZSC_MAX_BI_NUM`（如 500）或不设上限。

---

## 5. 信号-事件-交易体系

这是 czsc 策略表达的核心三层。

### 5.1 信号（Signal）

220+ 信号函数由 Rust 实现，通过 `signals_config` 调度：

```python
from czsc import generate_czsc_signals, get_signals_config, get_signals_freqs

SIGNALS_CONFIG = [
    {"name": "cxt_bi_status_V230101", "freq": "30分钟"},
    {"name": "bar_zdt_V230331", "freq": "30分钟", "di": 1},
    {"name": "tas_ma_base_V221101", "freq": "日线", "di": 1, "timeperiod": 5, "ma_type": "SMA"},
]

# 批量计算信号 DataFrame
df = generate_czsc_signals(bars, signals_config=SIGNALS_CONFIG, df=True)

# 流式计算（实盘）
from czsc import CzscSignals, BarGenerator
bg = BarGenerator(base_freq="30分钟", freqs=["30分钟", "日线"])
cs = CzscSignals(bg, signals_config=SIGNALS_CONFIG)
for bar in bars:
    cs.update_signals(bar)
print(cs.s)   # 当前信号字典
```

**可用信号查询**：

```python
from czsc._native.signals import bar
print(bar.list_signal_names())                    # 全部信号名
print(bar.get_signal_template("cxt_bi_status_V230101"))  # 信号模板
```

### 5.2 事件（Event）

信号的逻辑组合，三种集合：
- `signals_all`：AND（全部满足）
- `signals_any`：OR（任一满足）
- `signals_not`：NOT（全部不满足）

```python
from czsc import Event

open_event = Event.load({
    "name": "三买开多",
    "operate": "开多",
    "signals_all": ["30分钟_D1_三买辅助V230228_三买_任意_任意_0"],
    "signals_not": ["30分钟_D1_涨跌停V230331_涨停_任意_任意_0"],
})

# 测试是否触发
open_event.is_match({"30分钟_D1_表里关系V230101": "向上_任意_任意_0"})
```

### 5.3 持仓（Position）

完整的多/空策略，含风控：

```python
from czsc import Position

pos = Position(
    symbol="000001.SZ",
    name="30分钟笔趋势",
    opens=[open_event],
    exits=[exit_event],
    interval=14400,      # 两次开仓最小间隔（秒）
    timeout=480,         # 最长持仓 K 线根数
    stop_loss=300,       # 止损 BP（300 = 3%）
    t0=False,            # T+0 市场设 True
)
```

### 5.4 多级别联立交易器

```python
from czsc import CzscTrader

trader = CzscTrader(bg, positions=[pos], signals_config=get_signals_config(pos.unique_signals))
for bar in bars:
    trader.update(bar)

print(trader.positions[0].operates)   # 操作记录
print(trader.positions[0].pairs)      # 交易对
```

---

## 6. 策略与回测

### 6.1 策略类（CzscStrategyBase）

继承后只需实现 `positions` 属性：

```python
from czsc import CzscStrategyBase, Position

class MyStrategy(CzscStrategyBase):
    @property
    def positions(self) -> list[Position]:
        return [build_long_short_position(self.symbol, "30分钟")]

tactic = MyStrategy(symbol="000001.SZ")
print(tactic.signals_config)   # 自动派生
print(tactic.freqs)            # 自动派生
print(tactic.base_freq)
```

### 6.2 内存回测

```python
res = tactic.backtest(bars, sdt="2020-06-01")
pairs = res.pairs_df()        # 交易对
holds = res.holds_df()        # 持仓快照
signals = res.signals_df()    # 信号序列
```

### 6.3 回放落盘

```python
tactic.replay(bars, res_path="./output/", sdt="2020-06-01", refresh=True)
# 产出 signals.parquet / holds.parquet / pairs.parquet
```

### 6.4 权重回测（wbt）

把策略产出的权重序列做精细回测：

```python
from czsc import WeightBacktest, daily_performance, top_drawdowns

# holds.pos -> weight
dfw = holds[["dt", "symbol", "pos", "price"]].rename(columns={"pos": "weight"})
wb = WeightBacktest(data=dfw, fee_rate=0.0002, weight_type="ts", yearly_days=252)
print(wb.stats)   # 年化/夏普/回撤/胜率等
```

### 6.5 HTML 回测报告

```python
from wbt import generate_backtest_report
generate_backtest_report(df=dfw, output_path="report.html", title="策略回测", fee_rate=0.0002)
```

### 6.6 持仓序列化

```python
tactic.save_positions("./positions/")    # JSON + sha256 校验
# 用 CzscJsonStrategy 重新加载
from czsc import CzscJsonStrategy
```

---

## 7. 可视化与 HTML 产物

网站前端的核心是"把缠论结构和信号画出来"。czsc 提供两套方案。

### 7.1 lightweight-charts（推荐，自包含 HTML）

适合嵌入网站的离线图表，基于 TradingView lightweight-charts JS。

```python
from czsc.utils.plotting.lightweight import plot_czsc, plot_czsc_trader, plot_czsc_signals

# 单周期
plot_czsc(c, output="html", path="single.html", title="000001 缠论结构")

# 多周期联立
ct = CzscTrader(bg, positions=[], signals_config=[])
plot_czsc_trader(ct, output="html", path="multi.html", tail_bars=400)

# 信号叠加
plot_czsc_signals(bars, signals_config=SIGNALS_CONFIG, output="html", path="signals.html", tail_bars=600)
```

每个周期含三子图：主图（K线+SMA+分型+笔）/ 成交量 / MACD。文件 < 1MB，需联网加载 CDN。

### 7.2 plotly（单周期 K 线）

```python
from czsc.utils.plotting.kline import KlineChart
```

### 7.3 网站前端选型建议

| 方案 | 适用场景 | 说明 |
|---|---|---|
| **后端生成 HTML + iframe 嵌入** | 快速上线 | 直接用 `plot_czsc_trader` 生成 HTML，前端 iframe 嵌入 |
| **后端返回 JSON + 前端 ECharts 渲染** | 深度定制 | 把 K线/笔/分型序列化为 JSON，前端用 ECharts 渲染（参考经验 1258026） |
| **后端返回 JSON + 前端 lightweight-charts** | 接近原生看图体验 | 复用 czsc 已有的 lightweight-charts 数据模型 |

> 推荐：**后端返回结构化 JSON（K线/笔/分型/中枢/信号）+ 前端用 ECharts 或 lightweight-charts 渲染**。不要后端拼大段 HTML 字符串。

---

## 8. 网站化架构设计

### 8.1 推荐分层架构

```
┌─────────────────────────────────────────────┐
│  前端（Vue/React/原生JS + ECharts/lightweight）│
│  - 股票搜索/选择  - K线图  - 缠论结构叠加      │
│  - 信号展示       - 回测结果  - 持仓管理       │
└──────────────────┬──────────────────────────┘
                   │ HTTP / WebSocket
┌──────────────────▼──────────────────────────┐
│  Web 层（FastAPI/Flask）                       │
│  - REST API（查询/分析/回测）                   │
│  - WebSocket（实时行情推送）                    │
│  - 鉴权/限流/缓存                               │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│  分析服务层（czsc）                             │
│  - CZSC 结构分析  - 信号计算                    │
│  - CzscTrader 决策  - 回测                      │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│  数据层（Tushare / 券商行情 / 本地缓存）          │
└─────────────────────────────────────────────┘
```

### 8.2 后端 API 设计

建议拆分为两类接口（参考经验 1258026）：

**查询/列表类**：
```
GET  /api/symbols?q=...         股票搜索
GET  /api/symbols/{symbol}/info  股票基本信息
```

**核心计算类**：
```
POST /api/analyze                缠论分析（返回分型/笔/中枢 JSON）
POST /api/signals               信号计算
POST /api/backtest              策略回测
GET  /api/realtime/{symbol}     实时分析（WebSocket 更佳）
```

**响应结构约定**：
```json
{
  "success": true,
  "data": { ... },
  "error": null
}
```

### 8.3 关键 API 实现示例

```python
# FastAPI 示例
from fastapi import FastAPI, HTTPException
from czsc import CZSC, Freq, format_standard_kline
from czsc.connectors import ts_connector
from pydantic import BaseModel

app = FastAPI()

class AnalyzeRequest(BaseModel):
    symbol: str        # "000001.SZ"
    freq: str = "30分钟"
    sdt: str
    edt: str

@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    try:
        bars = ts_connector.get_raw_bars(f"{req.symbol}#E", req.freq, req.sdt, req.edt)
        c = CZSC(bars)
        return {
            "success": True,
            "data": {
                "symbol": req.symbol,
                "freq": req.freq,
                "bars_raw": [b.__dict__ for b in c.bars_raw[-200:]],   # 最近200根
                "fx_list": [{"dt": str(fx.dt), "mark": fx.mark.value, "fx": fx.fx} for fx in c.fx_list],
                "bi_list": [{"sdt": str(bi.sdt), "edt": str(bi.edt), "direction": bi.direction.value, "power": bi.power} for bi in c.bi_list],
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

> 注意序列化：`RawBar`/`FX`/`BI` 是 Rust 对象，转 dict 时需手动取字段或用 `.to_dict()`（如 `c.bars_raw_df`）。

### 8.4 数据缓存策略

- **K线缓存**：Tushare 连接器已内置磁盘缓存；自建数据源建议加 Redis/文件缓存（按 symbol+freq+sdt 键）
- **分析结果缓存**：相同 symbol+freq+sdt+edt 的分析结果可缓存，避免重复计算
- **信号缓存**：信号计算结果可按日缓存，只在新 K 线到来时增量更新

### 8.5 实时数据推送

```
行情源 → K线聚合 → czsc.update() → 结果序列化 → WebSocket → 前端
```

- 用 `asyncio` + `websockets` 或 FastAPI 的 WebSocket
- 每完成一根 K 线推送一次，不要每个 tick 都推（前端会卡顿）
- 推送内容：最新 K 线 + 新增分型/笔 + 信号变化

---

## 9. 股票系统对接实施

### 9.1 数据层对接

| 场景 | 方案 |
|---|---|
| A股历史/实时 | Tushare（历史）+ 券商行情网关（实时） |
| 期货 | 天勤 TQSdk |
| 数字货币 | CCXT |
| 自建行情库 | 写适配函数输出 `list[RawBar]` |

**关键**：统一数据格式为 `list[RawBar]`，后续分析链路完全复用。

### 9.2 分析服务层

- **离线分析**：用户选股票 + 周期 → 后端调用 `CZSC(bars)` → 返回结构化 JSON
- **实时分析**：行情驱动 `update()` → WebSocket 推送增量
- **批量分析**：用 `rayon`（Rust 并行）或 Python 多进程加速多标的

### 9.3 交易层对接（实盘交易，可选）

czsc 本身不直接下单，交易需对接券商柜台：

```
CzscTrader 决策 → Operate 信号 → 交易网关 → 券商柜台 → 成交回报 → 更新持仓
```

- A股：中泰 XTP / 恒生 UFT / 迅投 QMT
- 期货：CTP / 天勤
- 数字货币：交易所 API（CCXT 支持）

### 9.4 权限与安全

- API 鉴权：JWT / API Key
- 行情数据权限：Tushare token 等敏感信息存环境变量，不硬编码
- 接口限流：避免刷爆 Tushare 配额
- 下单风控：实盘前必须有模拟盘验证，加止损/仓位上限

---

## 10. 部署与运维

### 10.1 生产环境构建

```bash
# 构建 wheel
maturin build --release
pip install target/wheels/czsc-1.0.1-cp310-abi3-manylinux.whl

# 或 Docker
FROM python:3.12-slim
RUN pip install czsc
```

> 生产机器内存 ≥ 16G 才能顺利跑 release 默认配置的 LTO 构建。

### 10.2 进程管理

- **Web 服务**：uvicorn / gunicorn + FastAPI
- **行情订阅**：独立进程/容器，避免阻塞 Web
- **定时任务**：APScheduler / Celery（每日收盘后跑回测）

### 10.3 监控与告警

- 接口响应时间 / 错误率（Prometheus + Grafana）
- czsc 分析耗时（超过阈值告警）
- 数据源连通性（Tushare / 券商行情）
- 缓存命中率

### 10.4 性能优化

- 多用 `generate_czsc_signals` 批量计算，少用逐根 `update`
- `BarGenerator` 的 `max_count` 合理设置，避免内存无限增长
- 多标的分析用并行（Python `concurrent.futures` 或 Rust `rayon`）
- 信号配置精简，只算需要的信号

---

## 11. 最佳实践与避坑指南

### 11.1 Rust 构建 OOM

小内存机器用环境变量降级 release profile（见 §2.3）。

### 11.2 CZSC_MAX_BI_NUM 截断

默认 50 笔，长历史数据会被截断。网站展示完整历史需调大：

```bash
export CZSC_MAX_BI_NUM=500
```

### 11.3 DataFrame → RawBar 转换

```python
bars = format_standard_kline(df, freq=Freq.F30)   # 正确
# pd.DataFrame(c.bars_raw) 不能正确识别字段，用：
df = c.bars_raw_df                                 # CZSC 自带属性
```

### 11.4 Position.operates 时间字段

`Position.operates` 里的 `dt` 是 **unix 时间戳（秒）**，画图需转：

```python
pd.to_datetime(value, unit="s")
```

### 11.5 信号字符串结构

`{freq}_{k2}_{k3}_{v1}_{v2}_{v3}_{score}`，前 3 段是 key，后 4 段是 value。

### 11.6 缓存管理

- 默认 `~/.czsc`，`czsc.empty_cache_path()` 清空
- 超过 1GB 会有清理提示
- Tushare 缓存单独在 `~/.ts_data_cache`

### 11.7 环境变量大小写

`CZSC_VERBOSE` / `czsc_verbose` 都接受，大写优先；构造器显式参数优先级最高。

---

## 12. 快速启动 Checklist

- [ ] 安装 czsc（`pip install czsc` 或源码构建）
- [ ] 验证 `import czsc; print(czsc.__version__)` 正常
- [ ] 获取 Tushare Token 并 `czsc.set_url_token(...)`
- [ ] 跑通 `ts_connector.get_raw_bars` 拿到真实 A 股数据
- [ ] 跑通 `CZSC(bars)` 看分型/笔
- [ ] 设计 signals_config，跑通 `generate_czsc_signals`
- [ ] 定义 Event + Position，跑通 `CzscTrader`
- [ ] 跑通 `CzscStrategyBase.backtest` + `WeightBacktest`
- [ ] 选前端方案（lightweight-charts HTML 嵌入 / ECharts 自定义）
- [ ] 搭建 FastAPI 后端，暴露 analyze/signals/backtest 接口
- [ ] 接入实时行情 WebSocket 推送
- [ ] 部署（Docker + 进程管理 + 监控）

---

## 参考资料

- [README.md](file:///workspace/README.md) — 项目总览
- [CLAUDE.md](file:///workspace/CLAUDE.md) — 开发宪法与规范
- [docs/examples.md](file:///workspace/docs/examples.md) — 示例索引
- [docs/public_api.md](file:///workspace/docs/public_api.md) — 公开 API 手册
- [docs/examples/](file:///workspace/docs/examples) — 18 个端到端示例
- 飞书项目文档：https://s0cqcxuy3p.feishu.cn/wiki/wikcn3gB1MKl3ClpLnboHM1QgKf
