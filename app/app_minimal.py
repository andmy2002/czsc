"""
CZSC 缠论可视化桌面 App — 标准库 PoC（零外部依赖）

特点：
- 仅用 Python 标准库（tkinter + http.server + webbrowser）
- 启动弹窗输入 Tushare Token（可跳过用 mock 数据）
- 后端起 http.server 托管 HTML
- 前端：股票搜索 + 多周期缠论分析（lightweight-charts 嵌入）

启动流程：
    python app_minimal.py
    → 弹窗输入 Tushare Token（留空 = 用 mock 数据）
    → 自动打开浏览器 http://localhost:8765/

打包（Windows/macOS/Linux）：
    pip install pyinstaller
    pyinstaller --onefile app_minimal.py
"""

from __future__ import annotations

import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from tkinter import Tk, Label, Entry, Button, StringVar, messagebox

import czsc
from czsc import BarGenerator, CZSC, CzscTrader, Freq, format_standard_kline
from czsc.mock import generate_symbol_kines
from czsc.utils.plotting.lightweight import plot_czsc, plot_czsc_trader

HOST = "127.0.0.1"
PORT = 8765
TS_TOKEN: str | None = None   # 全局 token，由启动弹窗写入


# =============================================================================
# Tushare Token 设置
# =============================================================================

def setup_token_via_dialog() -> str | None:
    """启动弹窗让用户输入 Tushare Token

    留空 = 使用 mock 数据；填入 = 用 Tushare 拉真实 A 股行情
    """
    root = Tk()
    root.title("CZSC 缠论可视化 — 输入 Tushare Token")
    root.geometry("520x180")

    Label(root, text="Tushare API Token:").pack(pady=(20, 5))
    token_var = StringVar()
    entry = Entry(root, textvariable=token_var, width=60, show="*")
    entry.pack(pady=5)
    Label(root, text="留空将使用模拟数据；填写后可拉取真实 A 股行情", fg="gray").pack()

    result: dict[str, str | None] = {"token": None}

    def on_submit():
        result["token"] = token_var.get().strip() or None
        if result["token"]:
            try:
                czsc.set_url_token(token=result["token"], url="http://api.tushare.pro")
                # 延迟 import，避免顶层触发 DataClient 交互式输入
                from czsc.connectors import ts_connector
                # 验证 token 有效性（试拉 1 行）
                _ = ts_connector.get_raw_bars("000001.SZ#E", "日线", "20240101", "20240102")
                messagebox.showinfo("成功", "Tushare Token 已设置，将拉取真实行情")
            except Exception as e:
                messagebox.showwarning("提示", f"Token 验证失败（将用 mock 数据）: {e}")
                result["token"] = None
        else:
            messagebox.showinfo("提示", "未填写 Token，将使用模拟数据")
        root.destroy()

    Button(root, text="启动", command=on_submit).pack(pady=10)
    entry.focus_set()
    root.bind("<Return>", lambda e: on_submit())
    root.mainloop()
    return result["token"]


# =============================================================================
# 数据源：mock 或 Tushare
# =============================================================================

def get_bars(symbol: str, freq: str, sdt: str, edt: str):
    """统一数据入口：有 token 走 Tushare，无 token 走 mock"""
    if TS_TOKEN and "." in symbol:
        # 延迟 import，避免顶层触发 DataClient 交互式输入
        from czsc.connectors import ts_connector
        # symbol 形如 '000001.SZ' → Tushare 的 '000001.SZ#E'
        ts_symbol = f"{symbol}#E"
        return ts_connector.get_raw_bars(ts_symbol, freq, sdt, edt, fq="后复权")
    # mock
    if "." in symbol:
        sym = symbol.split(".")[0]
    else:
        sym = symbol
    df = generate_symbol_kines(sym, freq, sdt, edt, seed=42)
    return format_standard_kline(df, freq=Freq(freq))


# =============================================================================
# HTTP Server
# =============================================================================

class AppHTTPRequestHandler(BaseHTTPRequestHandler):
    """简单的 HTTP 路由

    GET /                         主页（股票搜索 + 结果展示 iframe）
    GET /api/analyze?symbol=...   分析某股票，返回 lightweight HTML
    GET /api/multi?symbol=...     多周期联立，返回 lightweight HTML
    """

    def log_message(self, format, *args):
        # 静默日志
        return

    def _send_html(self, html: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _send_json(self, data: dict, code: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self._send_html(self._render_index())
            return

        if path == "/api/analyze":
            symbol = qs.get("symbol", ["000001.SZ"])[0]
            freq_alias = qs.get("freq", ["30m"])[0]
            freq_map = {"30m": "30分钟", "60m": "60分钟", "d": "日线"}
            freq = freq_map.get(freq_alias, "30分钟")
            sdt = qs.get("sdt", ["20230101"])[0]
            edt = qs.get("edt", ["20240601"])[0]
            try:
                bars = get_bars(symbol, freq, sdt, edt)
                c = CZSC(bars)
                title = f"{symbol} · 缠论结构（{freq}）"
                html = plot_czsc(c, output="html", path=None, title=title, tail_bars=400)
                self._send_html(html)
            except Exception as e:
                self._send_html(f"<h3>分析失败</h3><pre>{e}</pre>", code=500)
            return

        if path == "/api/multi":
            symbol = qs.get("symbol", ["000001.SZ"])[0]
            sdt = qs.get("sdt", ["20230101"])[0]
            edt = qs.get("edt", ["20240601"])[0]
            try:
                bars = get_bars(symbol, "30分钟", sdt, edt)
                bg = BarGenerator(base_freq="30分钟", freqs=["30分钟", "60分钟", "日线"], max_count=5000)
                for b in bars:
                    bg.update(b)
                ct = CzscTrader(bg, positions=[], signals_config=[])
                title = f"{symbol} · 多周期缠论结构（日线 / 60分钟 / 30分钟）"
                html = plot_czsc_trader(ct, output="html", path=None, title=title, tail_bars=400)
                self._send_html(html)
            except Exception as e:
                self._send_html(f"<h3>分析失败</h3><pre>{e}</pre>", code=500)
            return

        if path == "/api/status":
            self._send_json({
                "token_set": TS_TOKEN is not None,
                "data_source": "Tushare（真实 A 股）" if TS_TOKEN else "mock（模拟数据）",
            })
            return

        self._send_html("Not Found", code=404)

    def _render_index(self) -> str:
        """主页：股票搜索框 + iframe 展示分析结果"""
        return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>CZSC 缠论可视化</title>
<style>
  body { font-family: -apple-system, 'Segoe UI', sans-serif; margin: 0; padding: 16px; background: #f5f5f7; }
  .header { display: flex; gap: 12px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
  h1 { margin: 0; font-size: 20px; color: #1d1d1f; }
  input, select, button { padding: 8px 12px; border: 1px solid #d2d2d7; border-radius: 6px; font-size: 14px; }
  button { background: #0071e3; color: white; cursor: pointer; border: none; }
  button:hover { background: #0077ed; }
  .status { font-size: 12px; color: #6e6e73; }
  iframe { width: 100%; height: calc(100vh - 80px); border: 1px solid #d2d2d7; border-radius: 8px; background: white; }
</style>
</head>
<body>
  <div class="header">
    <h1>CZSC 缠论可视化</h1>
    <input id="symbol" value="000001.SZ" placeholder="股票代码（如 000001.SZ）" style="width: 220px">
    <select id="mode">
      <option value="multi">多周期联立</option>
      <option value="analyze">单周期</option>
    </select>
    <select id="freq">
      <option value="30m">30分钟</option>
      <option value="60m">60分钟</option>
      <option value="d">日线</option>
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
    const url = mode === 'multi'
      ? `/api/multi?symbol=${encodeURIComponent(symbol)}&sdt=${sdt}&edt=${edt}`
      : `/api/analyze?symbol=${encodeURIComponent(symbol)}&freq=${encodeURIComponent(freq)}&sdt=${sdt}&edt=${edt}`;
    document.getElementById('result').src = url;
  }
  runAnalyze();
</script>
</body>
</html>"""


# =============================================================================
# 启动
# =============================================================================

def start_server():
    """启动 HTTP server（在后台线程）"""
    server = ThreadingHTTPServer((HOST, PORT), AppHTTPRequestHandler)
    print(f"[App] 后端服务启动：http://{HOST}:{PORT}/")
    server.serve_forever()


def main():
    global TS_TOKEN
    import sys
    print("[App] 启动 CZSC 缠论可视化桌面 App")
    # 命令行参数 --token=xxx 跳过 GUI（CI/无 GUI 环境用）
    cli_token = None
    for arg in sys.argv[1:]:
        if arg.startswith("--token="):
            cli_token = arg.split("=", 1)[1] or None
    if cli_token is not None:
        TS_TOKEN = cli_token
        if TS_TOKEN:
            czsc.set_url_token(token=TS_TOKEN, url="http://api.tushare.pro")
            print(f"[App] 已通过命令行设置 Tushare Token")
        else:
            print("[App] 未设置 Token，使用 mock 数据")
    else:
        try:
            TS_TOKEN = setup_token_via_dialog()
        except Exception as e:
            print(f"[App] GUI 不可用：{e}，使用 mock 数据（可加 --token=xxx 指定）")
            TS_TOKEN = None
    # 启动后端
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    # 打开默认浏览器
    url = f"http://{HOST}:{PORT}/"
    print(f"[App] 在浏览器打开：{url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    # 主线程保持运行
    try:
        while True:
            import time
            time.sleep(60)
    except KeyboardInterrupt:
        print("[App] 退出")


if __name__ == "__main__":
    main()
