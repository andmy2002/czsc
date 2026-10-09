"""
A 股实盘交易对接示例 —— czsc 决策 → 券商柜台下单

适用场景：A 股股票（不含融资融券做空），T+1 交易
覆盖柜台：MiniQMT（迅投，最常用）、easytrader（开源通用）
本文件是骨架示例，实盘使用前务必先在模拟盘验证。

核心数据流：
    czsc.CzscTrader.update(bar)  →  Position.operates[-1]  →  本模块  →  券商柜台下单

OperateRecord 字段（来自 czsc._native）：
    symbol:  标的代码（czsc 内部格式，需转成券商格式）
    dt:      操作时间（DateTime<FixedOffset>，需转 unix 时间戳或 pd.Timestamp）
    bar_id:  K 线序号
    price:   触发价格
    op:      Operate 枚举（LO=开多 / LE=平多 / SO=开空 / SE=平空 / HL=持多 / HS=持空 / HO=持币）
    op_desc: 操作描述（可选）
    pos:     操作后仓位（+1 多 / -1 空 / 0 空仓）
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

import pandas as pd


# =============================================================================
# 第一层：A 股交易规则约束（必须遵守）
# =============================================================================

class AShareRules:
    """A 股交易规则约束，实盘下单前必须校验"""

    # T+1：当日买入不能卖
    # 普通股票账户不能做空（开空/平空直接拒绝）
    # 主板涨跌停 10%，科创板/创业板 20%，北交所 30%
    LOT_SIZE = 100          # 最小交易单位：100 股 = 1 手

    @staticmethod
    def is_short_op(op: str) -> bool:
        """判断是否为做空操作（A 股普通账户不支持）"""
        return op in ("开空", "平空")

    @staticmethod
    def symbol_to_qmt(symbol: str) -> str:
        """czsc symbol → QMT 代码
        czsc: '000001.SZ'  →  QMT: '000001.SZ'（多数券商 QMT 接受 .SZ/.SH）
        czsc: '600519.SH'  →  QMT: '600519.SH'
        """
        return symbol.upper()

    @staticmethod
    def calc_lots(cash: float, price: float, max_lots: int = 1000) -> int:
        """按可用资金计算可买手数，向下取整到 LOT_SIZE 倍数"""
        if price <= 0:
            return 0
        lots = int(cash / (price * AShareRules.LOT_SIZE))
        return min(lots, max_lots)

    @staticmethod
    def can_sell_today(position_date: pd.Timestamp, today: Optional[datetime] = None) -> bool:
        """T+1 校验：当日买入的不能卖"""
        today = today or datetime.now()
        # 持仓日期 < 今天，才能卖
        return position_date.date() < today.date()


# =============================================================================
# 第二层：MiniQMT（迅投）下单适配器
# =============================================================================

class QMTBrokerAdapter:
    """MiniQMT 券商适配器

    依赖：xtquant（迅投 QMT 客户端自带，需在 QMT 终端同机部署）
        pip install xtquant  # 通常直接从 QMT 安装目录拿

    使用前：
        1. 已开通 QMT 权限的券商账户
        2. 本机启动 MiniQMT 客户端并登录
        3. xtquant 通过本地端口与 QMT 通信
    """

    def __init__(self, account: str, path: Optional[str] = None):
        self.account = account
        self.path = path
        self._xt = None
        self._trader = None

    def connect(self):
        """连接 QMT 终端（必须先启动 MiniQMT 客户端）"""
        from xtquant import xttrader, xtdata  # noqa
        import os

        # path 通常为 QMT 客户端 userdata 路径，如 'C:\\国金QMT\\userdata_mini'
        path = self.path or os.getenv("QMT_PATH")
        if not path:
            raise RuntimeError("需设置 QMT_PATH 环境变量指向 QMT userdata 目录")

        session_id = int(time.time())
        self._xt = xttrader.XTTrader(path, session_id)
        self._xt.start()
        if not self._xt.connect():
            raise RuntimeError("连接 QMT 失败，请确认 MiniQMT 已启动并登录")

        acc = xttrader.StockAccount(self.account)
        self._trader = (self._xt, acc)
        print(f"[QMT] 已连接账户 {self.account}")

    def get_position(self, symbol: str) -> dict:
        """查询持仓，返回 {volume, can_use_volume, cost, market_value}"""
        xt, acc = self._trader
        qmt_code = AShareRules.symbol_to_qmt(symbol)
        # xt.query_stock_orders(acc, cancelable=False) 查委托
        # xt.query_stock_positions(acc) 查持仓
        positions = xt.query_stock_positions(acc)
        for p in positions:
            if p.stock_code == qmt_code:
                return {
                    "volume": p.volume,
                    "can_use_volume": p.can_use_volume,   # 可卖量（T+1 后才有）
                    "cost": p.open_price,
                    "market_value": p.market_value,
                }
        return {"volume": 0, "can_use_volume": 0, "cost": 0, "market_value": 0}

    def get_account_balance(self) -> float:
        """查可用资金"""
        xt, acc = self._trader
        for a in xt.query_stock_asset(acc):
            return a.cash  # 可用资金
        return 0.0

    def buy(self, symbol: str, price: float, lots: int) -> str:
        """买入下单，返回订单序号"""
        if lots <= 0:
            return ""
        xt, acc = self._trader
        qmt_code = AShareRules.symbol_to_qmt(symbol)
        # xt_limit: 最新价 / 五档 / 指定价；这里用限价单（price）
        order_id = xt.order_stock(
            acc, qmt_code, xt.STOCK_BUY,
            lots, xt.FIX_PRICE, price, -1, "czsc_自动买入",
        )
        print(f"[QMT] BUY  {qmt_code} {lots}股 @ {price}  ord={order_id}")
        return str(order_id)

    def sell(self, symbol: str, price: float, lots: int) -> str:
        """卖出下单，返回订单序号"""
        if lots <= 0:
            return ""
        # T+1 校验
        pos = self.get_position(symbol)
        if pos["can_use_volume"] < lots:
            print(f"[QMT] SELL 拒绝：{symbol} 可卖量 {pos['can_use_volume']} < {lots}（T+1 限制）")
            return ""
        xt, acc = self._trader
        qmt_code = AShareRules.symbol_to_qmt(symbol)
        order_id = xt.order_stock(
            acc, qmt_code, xt.STOCK_SELL,
            lots, xt.FIX_PRICE, price, -1, "czsc_自动卖出",
        )
        print(f"[QMT] SELL {qmt_code} {lots}股 @ {price}  ord={order_id}")
        return str(order_id)


# =============================================================================
# 第三层：czsc operates → 券商下单 的桥接器
# =============================================================================

class CzscTraderExecutor:
    """把 czsc 的 OperateRecord 翻译成券商下单指令

    使用方式：
        from czsc import CzscTrader
        ct = CzscTrader(bg, positions=[pos], signals_config=cfg)
        for bar in realtime_bars:
            ct.update(bar)
            executor.poll_and_execute(ct)   # 每根新 K 线后检查并下单
    """

    def __init__(self, broker: QMTBrokerAdapter, *, cash_per_trade: float = 100_000,
                 max_lots_per_trade: int = 1000, allow_short: bool = False):
        self.broker = broker
        self.cash_per_trade = cash_per_trade          # 每次开仓最大可用资金
        self.max_lots = max_lots_per_trade
        self.allow_short = allow_short                 # A 股普通账户必须 False
        self._executed_keys: set[str] = set()          # 已执行的 operate 去重

    @staticmethod
    def _get(op_record, field, default=None):
        """兼容 dict / 对象两种形态"""
        if isinstance(op_record, dict):
            return op_record.get(field, default)
        return getattr(op_record, field, default)

    def _op_key(self, op_record) -> str:
        """每个 operate 的唯一键，避免重复下单"""
        symbol = self._get(op_record, "symbol")
        dt = self._get(op_record, "dt")
        op = self._get(op_record, "op")
        bar_id = self._get(op_record, "bar_id")
        return f"{symbol}|{dt}|{op}|{bar_id}"

    def poll_and_execute(self, czsc_trader) -> list[str]:
        """检查 czsc_trader 的最新 operates，执行未处理的新操作"""
        order_ids: list[str] = []

        # 遍历所有 position 的 operates
        for pos in czsc_trader.positions:
            for op_rec in pos.operates:
                key = self._op_key(op_rec)
                if key in self._executed_keys:
                    continue
                # 跳过状态保持类（HL 持多 / HS 持空 / HO 持币），不触发下单
                if self._get(op_rec, "op") in ("HL", "HS", "HO"):
                    self._executed_keys.add(key)
                    continue

                # 翻译 op 到下单动作
                oid = self._dispatch(op_rec)
                if oid:
                    order_ids.append(oid)
                self._executed_keys.add(key)

        return order_ids

    def _dispatch(self, op_rec) -> str:
        """根据 czsc op 调用券商接口"""
        op = str(self._get(op_rec, "op"))   # 'LO'/'LE'/'SO'/'SE'
        symbol = self._get(op_rec, "symbol")
        price = float(self._get(op_rec, "price", 0) or 0)

        # 1) 做空过滤（A 股普通账户不支持）
        if AShareRules.is_short_op(op) and not self.allow_short:
            print(f"[SKIP] {op} 拒绝：A 股普通账户不支持做空 {symbol}")
            return ""

        # 2) 开多 → 买入
        if op == "LO":
            cash = min(self.broker.get_account_balance(), self.cash_per_trade)
            lots = AShareRules.calc_lots(cash, price, self.max_lots)
            lots = lots * AShareRules.LOT_SIZE   # 转成股数
            if lots <= 0:
                print(f"[SKIP] {symbol} 资金不足买入 1 手")
                return ""
            return self.broker.buy(symbol, price, lots)

        # 3) 平多 → 卖出全部持仓
        if op == "LE":
            pos = self.broker.get_position(symbol)
            can_sell = pos["can_use_volume"]
            if can_sell <= 0:
                print(f"[SKIP] {symbol} 无可卖持仓（T+1 或未持仓）")
                return ""
            return self.broker.sell(symbol, price, can_sell)

        # 4) 开空 / 平空（融资融券账户才支持，这里默认拒绝）
        if op in ("SO", "SE") and self.allow_short:
            print(f"[TODO] {op} 融资融券账户对接，本示例未实现")
            return ""

        return ""


# =============================================================================
# 第四层：实盘主循环（事件驱动）
# =============================================================================

def run_live(czsc_trader, executor: CzscTraderExecutor,
             bar_source, sleep_seconds: float = 1.0):
    """实盘主循环

    :param czsc_trader: czsc.CzscTrader 实例（已配置 positions + signals_config）
    :param executor:    本文件 CzscTraderExecutor
    :param bar_source:  可迭代对象，产出新 K 线 RawBar
    :param sleep_seconds: 每根 K 线后等待秒数（防止刷盘）
    """
    print(f"[LIVE] 启动实盘，已加载 {len(czsc_trader.positions)} 个策略")
    for bar in bar_source:
        try:
            czsc_trader.update(bar)
            order_ids = executor.poll_and_execute(czsc_trader)
            if order_ids:
                print(f"[LIVE] {bar.dt} 触发 {len(order_ids)} 笔委托")
            time.sleep(sleep_seconds)
        except KeyboardInterrupt:
            print("[LIVE] 用户中断，安全退出")
            break
        except Exception as e:
            print(f"[LIVE] 错误：{e}，继续监听")


# =============================================================================
# 第五层：备选方案 easytrader（开源，免 QMT 权限）
# =============================================================================

class EasyTraderAdapter:
    """easytrader 适配器（适用于没开通 QMT 权限的散户）

    依赖：
        pip install easytrader

    特点：
        - 通过模拟键鼠操作同花顺/华泰等客户端，不需券商特殊权限
        - 稳定性弱于 QMT，适合低频策略
        - 不支持精确价格下单（用客户端默认）
    """

    def __init__(self, client: str = "ths"):
        """
        :param client: 'ths'=同花顺, 'htzq'=华泰, 'yh'=银河等
        """
        self.client_name = client
        self._user = None

    def connect(self):
        import easytrader
        self._user = easytrader.use(self.client_name)
        # 需要客户端已启动并登录
        self._user.connect()
        print(f"[easytrader] 已连接 {self.client_name}")

    def buy(self, symbol: str, price: float, lots: int) -> str:
        # easytrader 用证券代码（不带后缀）+ 数量
        code = symbol.split(".")[0]
        result = self._user.buy(code, price=price, amount=lots)
        print(f"[easytrader] BUY {code} {lots}股 → {result}")
        return str(result.get("entrust_no", ""))

    def sell(self, symbol: str, price: float, lots: int) -> str:
        code = symbol.split(".")[0]
        result = self._user.sell(code, price=price, amount=lots)
        print(f"[easytrader] SELL {code} {lots}股 → {result}")
        return str(result.get("entrust_no", ""))


# =============================================================================
# 使用示例（最小可运行）
# =============================================================================

def demo():
    """最小可运行示例：模拟盘验证流程

    实盘前必须先在模拟环境跑通此流程，验证：
        1. czsc operates 正确产出
        2. 桥接器正确翻译 op → 下单
        3. T+1 / 资金 / 持仓 校验生效
    """
    import czsc
    from czsc import CzscTrader, BarGenerator, Position, Event, Freq

    # 1) 准备 czsc trader（详见 06_event_position.py / 07_strategy_backtest.py）
    open_ev = Event.load({
        "name": "开多_笔向上", "operate": "开多",
        "signals_all": ["30分钟_D1_表里关系V230101_向上_任意_任意_0"],
        "signals_not": ["30分钟_D1_涨跌停V230331_涨停_任意_任意_0"],
    })
    exit_ev = Event.load({
        "name": "平多_笔向下", "operate": "平多",
        "signals_all": ["30分钟_D1_表里关系V230101_向下_任意_任意_0"],
    })
    pos = Position(
        symbol="000001.SZ", name="笔非多即空",
        opens=[open_ev], exits=[exit_ev],
        interval=14400, timeout=480, stop_loss=500, t0=False,  # A 股 T+1
    )
    bg = BarGenerator(base_freq="30分钟", freqs=["30分钟"])
    ct = CzscTrader(bg, positions=[pos],
                    signals_config=czsc.get_signals_config(pos.unique_signals))

    # 2) 准备券商适配器（二选一）
    # broker = QMTBrokerAdapter(account="你的资金账号", path="C:\\QMT\\userdata_mini")
    # broker.connect()
    # executor = CzscTraderExecutor(broker, cash_per_trade=100_000, allow_short=False)

    # 模拟环境（不真正下单）
    broker = _MockBroker()
    executor = CzscTraderExecutor(broker, cash_per_trade=100_000, allow_short=False)

    # 3) 喂历史数据预热 + 模拟执行
    from czsc.mock import generate_symbol_kines
    from czsc import format_standard_kline
    df = generate_symbol_kines("000001", "30分钟", "20240101", "20240601", seed=42)
    bars = format_standard_kline(df, freq=Freq.F30)

    print("=== 模拟实盘执行 ===")
    for bar in bars[:500]:
        ct.update(bar)
        oids = executor.poll_and_execute(ct)
        if oids:
            print(f"  {bar.dt} 触发 {len(oids)} 笔委托")

    print(f"\n=== 完成，共 {len(ct.positions[0].operates)} 个 operate，"
          f"实际下单 {len(executor._executed_keys)} 次 ===")


class _MockBroker:
    """模拟券商，便于不开通真实账户时验证流程"""
    def __init__(self):
        self.cash = 1_000_000
        self.positions: dict[str, dict] = {}

    def get_account_balance(self) -> float:
        return self.cash

    def get_position(self, symbol: str) -> dict:
        return self.positions.get(symbol, {"volume": 0, "can_use_volume": 0, "cost": 0})

    def buy(self, symbol: str, price: float, lots: int) -> str:
        cost = price * lots
        if self.cash < cost:
            print(f"[MOCK] 资金不足 cash={self.cash} < cost={cost}")
            return ""
        self.cash -= cost
        pos = self.positions.setdefault(symbol, {"volume": 0, "can_use_volume": 0, "cost": 0})
        pos["volume"] += lots
        pos["cost"] = price
        print(f"[MOCK] BUY {symbol} {lots}股 @ {price}  剩余现金 {self.cash:.0f}")
        return "mock_buy"

    def sell(self, symbol: str, price: float, lots: int) -> str:
        pos = self.positions.get(symbol)
        if not pos or pos["can_use_volume"] < lots:
            print(f"[MOCK] 无可卖持仓 {symbol}")
            return ""
        pos["volume"] -= lots
        pos["can_use_volume"] -= lots
        self.cash += price * lots
        print(f"[MOCK] SELL {symbol} {lots}股 @ {price}  剩余现金 {self.cash:.0f}")
        return "mock_sell"


if __name__ == "__main__":
    demo()
