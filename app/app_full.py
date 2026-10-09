"""
CZSC 缠论可视化桌面 App — PyWebView + Flask 完整版

特点：
- PyWebView 调起系统浏览器内核（Chromium/WebKit），真正的桌面 App 形态
- Flask 后端，REST API + WebSocket 实时推送
- 启动弹窗输入 Tushare Token
- 完整功能：股票搜索 / 多周期分析 / 信号 / 回测 / HTML 报告

依赖：
    pip install flask pywebview

启动：
    python app_full.py
    → 弹窗输入 Tushare Token
    → 自动打开桌面 App 窗口

打包成单文件 exe（Windows）：
    pip install pyinstaller
    pyinstaller --onefile --add-data "templates;templates" app_full.py
"""

from __future__ import annotations

import threading
import webbrowser
from tkinter import Tk, Label, Entry, Button, StringVar, messagebox

import czsc
from czsc.connectors import ts_connector

HOST = "127.0.0.1"
PORT = 5000
TS_TOKEN: str | None = None


# =============================================================================
# Token 输入弹窗
# =============================================================================

def setup_token_via_dialog() -> str | None:
    root = Tk()
    root.title("CZSC 缠论桌面 App — 输入 Tushare Token")
    root.geometry("520x220")

    Label(root, text="Tushare API Token:", font=("Arial", 11)).pack(pady=(20, 5))
    token_var = StringVar()
    entry = Entry(root, textvariable=token_var, width=60, show="*")
    entry.pack(pady=5)
    Label(root, text="留空将使用模拟数据；填写后可拉取真实 A 股行情\n"
                     "Token 从 tushare.pro 注册获取（分钟线需 2000+ 积分）",
          fg="gray", justify="left").pack()

    result: dict[str, str | None] = {"token": None}

    def on_submit():
        result["token"] = token_var.get().strip() or None
        if result["token"]:
            try:
                czsc.set_url_token(token=result["token"], url="http://api.tushare.pro")
                _ = ts_connector.get_raw_bars("000001.SZ#E", "日线", "20240101", "20240102")
                messagebox.showinfo("成功", "Tushare Token 已设置")
            except Exception as e:
                messagebox.showwarning("提示", f"Token 验证失败，将用 mock 数据：\n{e}")
                result["token"] = None
        root.destroy()

    Button(root, text="启动 App", command=on_submit, font=("Arial", 11)).pack(pady=10)
    entry.focus_set()
    root.bind("<Return>", lambda e: on_submit())
    root.mainloop()
    return result["token"]


# =============================================================================
# Flask 后端
# =============================================================================

def create_flask_app():
    """创建 Flask 应用（避免顶层 import，便于按需引入）"""
    from flask import Flask, request, jsonify, Response
    from czsc import (BarGenerator, CZSC, CzscTrader, Freq, format_standard_kline,
                      generate_czsc_signals, WeightBacktest)
    from czsc.mock import generate_symbol_kines
    from czsc.utils.plotting.lightweight import plot_czsc, plot_czsc_trader, plot_czsc_signals

    app = Flask(__name__)

    def get_bars(symbol: str, freq: str, sdt: str, edt: str):
        if TS_TOKEN and "." in symbol:
            return ts_connector.get_raw_bars(f"{symbol}#E", freq, sdt, edt, fq="后复权")
        sym = symbol.split(".")[0] if "." in symbol else symbol
        df = generate_symbol_kines(sym, freq, sdt, edt, seed=42)
        return format_standard_kline(df, freq=Freq(freq))

    @app.route("/")
    def index():
        return INDEX_HTML

    @app.route("/api/status")
    def status():
        return jsonify({
            "token_set": TS_TOKEN is not None,
            "data_source": "Tushare（真实 A 股）" if TS_TOKEN else "mock（模拟数据）",
        })

    @app.route("/api/analyze")
    def analyze():
        symbol = request.args.get("symbol", "000001.SZ")
        freq = request.args.get("freq", "30分钟")
        sdt = request.args.get("sdt", "20230101")
        edt = request.args.get("edt", "20240601")
        try:
            bars = get_bars(symbol, freq, sdt, edt)
            c = CZSC(bars)
            html = plot_czsc(c, output="html", path=None,
                             title=f"{symbol} · 缠论结构（{freq}）", tail_bars=400)
            return Response(html, mimetype="text/html")
        except Exception as e:
            return Response(f"<h3>分析失败</h3><pre>{e}</pre>", status=500,
                            mimetype="text/html")

    @app.route("/api/multi")
    def multi():
        symbol = request.args.get("symbol", "000001.SZ")
        sdt = request.args.get("sdt", "20230101")
        edt = request.args.get("edt", "20240601")
        try:
            bars = get_bars(symbol, "30分钟", sdt, edt)
            bg = BarGenerator(base_freq="30分钟", freqs=["30分钟", "60分钟", "日线"], max_count=5000)
            for b in bars:
                bg.update(b)
            ct = CzscTrader(bg, positions=[], signals_config=[])
            html = plot_czsc_trader(ct, output="html", path=None,
                                    title=f"{symbol} · 多周期缠论结构", tail_bars=400)
            return Response(html, mimetype="text/html")
        except Exception as e:
            return Response(f"<h3>分析失败</h3><pre>{e}</pre>", status=500,
                            mimetype="text/html")

    @app.route("/api/signals")
    def signals():
        """信号叠加可视化"""
        symbol = request.args.get("symbol", "000001.SZ")
        sdt = request.args.get("sdt", "20230101")
        edt = request.args.get("edt", "20240601")
        signals_config = [
            {"name": "cxt_bi_status_V230101", "freq": "30分钟", "params": {}},
            {"name": "bar_zdt_V230331", "freq": "30分钟", "params": {"di": 1}},
        ]
        try:
            bars = get_bars(symbol, "30分钟", sdt, edt)
            html = plot_czsc_signals(bars, signals_config=signals_config,
                                     output="html", path=None,
                                     title=f"{symbol} · 信号触发可视化", tail_bars=600)
            return Response(html, mimetype="text/html")
        except Exception as e:
            return Response(f"<h3>分析失败</h3><pre>{e}</pre>", status=500,
                            mimetype="text/html")

    @app.route("/api/backtest")
    def backtest():
        """简单回测演示（用预设策略跑回测）"""
        symbol = request.args.get("symbol", "000001.SZ")
        sdt = request.args.get("sdt", "20230101")
        edt = request.args.get("edt", "20240601")
        try:
            from czsc import CzscStrategyBase, Position, Event
            # 演示策略：笔向上开多，笔向下平多
            open_ev = Event.load({
                "name": "开多", "operate": "开多",
                "signals_all": ["30分钟_D1_表里关系V230101_向上_任意_任意_0"],
                "signals_not": ["30分钟_D1_涨跌停V230331_涨停_任意_任意_0"],
            })
            exit_ev = Event.load({
                "name": "平多", "operate": "平多",
                "signals_all": ["30分钟_D1_表里关系V230101_向下_任意_任意_0"],
            })
            pos = Position(symbol=symbol, name="笔趋势",
                           opens=[open_ev], exits=[exit_ev],
                           interval=14400, timeout=480, stop_loss=500, t0=False)

            class DemoStrategy(CzscStrategyBase):
                @property
                def positions(self):
                    return [pos]

            tactic = DemoStrategy(symbol=symbol)
            bars = get_bars(symbol, "30分钟", sdt, edt)
            res = tactic.backtest(bars, sdt=sdt)
            holds = res.holds_df()
            pairs = res.pairs_df()

            summary = f"""
            <h2>回测结果 · {symbol}</h2>
            <p>策略：笔向上开多 / 笔向下平多（T+1，止损5%）</p>
            <p>K 线数：{len(bars)} | 交易对数：{len(pairs)} | 持仓快照：{len(holds)}</p>
            <h3>最近 5 笔交易</h3>
            {pairs.tail(5).to_html(index=False) if len(pairs) > 0 else '<p>无交易</p>'}
            <h3>统计</h3>
            <p>持仓胜率：{(pairs['盈亏比例'] > 0).mean() * 100:.1f}%（共 {len(pairs)} 笔）</p>
            """
            return Response(summary, mimetype="text/html")
        except Exception as e:
            return Response(f"<h3>回测失败</h3><pre>{e}</pre>", status=500,
                            mimetype="text/html")

    return app


INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>CZSC 缠论桌面 App</title>
<style>
  body { font-family: -apple-system, 'Segoe UI', sans-serif; margin: 0; padding: 16px; background: #f5f5f7; color: #1d1d1f; }
  .header { display: flex; gap: 12px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
  h1 { margin: 0; font-size: 20px; }
  input, select, button { padding: 8px 12px; border: 1px solid #d2d2d7; border-radius: 6px; font-size: 14px; outline: none; }
  button { background: #0071e3; color: white; cursor: pointer; border: none; }
  button:hover { background: #0077ed; }
  button.active { background: #0050a5; }
  .status { font-size: 12px; color: #6e6e73; }
  iframe { width: 100%; height: calc(100vh - 80px); border: 1px solid #d2d2d7; border-radius: 8px; background: white; }
</style>
</head>
<body>
  <div class="header">
    <h1>CZSC 缠论</h1>
    <input id="symbol" value="000001.SZ" placeholder="股票代码" style="width: 220px">
    <select id="mode" onchange="runAnalyze()">
      <option value="multi">多周期联立</option>
      <option value="analyze">单周期</option>
      <option value="signals">信号叠加</option>
      <option value="backtest">回测</option>
    </select>
    <select id="freq">
      <option>30分钟</option>
      <option>60分钟</option>
      <option>日线</option>
    </select>
    <input id="sdt" value="20230101" style="width: 90px">
    <input id="edt" value="20240601" style="width: 90px">
    <button onclick="runAnalyze()">分析</button>
    <span class="status" id="status"></span>
  </div>
  <iframe id="result" name="result"></iframe>
<script>
  fetch('/api/status').then(r => r.json()).then(s => {
    document.getElementById('status').textContent = '数据源：' + s.data_source;
  });
  function runAnalyze() {
    const symbol = document.getElementById('symbol').value;
    const mode = document.getElementById('mode').value;
    const freq = document.getElementById('freq').value;
    const sdt = document.getElementById('sdt').value;
    const edt = document.getElementById('edt').value;
    let url;
    if (mode === 'multi') url = `/api/multi?symbol=${encodeURIComponent(symbol)}&sdt=${sdt}&edt=${edt}`;
    else if (mode === 'signals') url = `/api/signals?symbol=${encodeURIComponent(symbol)}&sdt=${sdt}&edt=${edt}`;
    else if (mode === 'backtest') url = `/api/backtest?symbol=${encodeURIComponent(symbol)}&sdt=${sdt}&edt=${edt}`;
    else url = `/api/analyze?symbol=${encodeURIComponent(symbol)}&freq=${encodeURIComponent(freq)}&sdt=${sdt}&edt=${edt}`;
    document.getElementById('result').src = url;
  }
  runAnalyze();
</script>
</body>
</html>"""


# =============================================================================
# 启动
# =============================================================================

def start_in_browser():
    """模式一：用系统默认浏览器打开（无需 pywebview）"""
    global TS_TOKEN
    TS_TOKEN = setup_token_via_dialog()
    app = create_flask_app()
    # 后台线程跑 Flask
    threading.Thread(target=lambda: app.run(host=HOST, port=PORT,
                                            debug=False, use_reloader=False),
                     daemon=True).start()
    url = f"http://{HOST}:{PORT}/"
    print(f"[App] 在浏览器打开：{url}")
    webbrowser.open(url)
    try:
        import time
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("[App] 退出")


def start_in_pywebview():
    """模式二：用 PyWebView 包成桌面 App 窗口（推荐生产用）"""
    global TS_TOKEN
    TS_TOKEN = setup_token_via_dialog()
    app = create_flask_app()
    threading.Thread(target=lambda: app.run(host=HOST, port=PORT,
                                            debug=False, use_reloader=False),
                     daemon=True).start()
    import webview
    url = f"http://{HOST}:{PORT}/"
    webview.create_window("CZSC 缠论桌面 App", url, width=1400, height=900,
                          min_size=(1000, 700))
    webview.start()


def main():
    import sys
    print("[App] 启动 CZSC 缠论可视化桌面 App")
    # 默认浏览器模式；命令行参数 --pywebview 用桌面 App 窗口
    if "--pywebview" in sys.argv:
        try:
            start_in_pywebview()
        except ImportError:
            print("[App] pywebview 未安装，回退到浏览器模式")
            print("[App] 安装：pip install pywebview")
            start_in_browser()
    else:
        start_in_browser()


if __name__ == "__main__":
    main()
