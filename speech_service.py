import os
import time
import json
import logging
import threading
import asyncio
import websockets
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import http.server
import socketserver

logger = logging.getLogger("SpeechService")

# 配置
WS_HOST = "127.0.0.1"
WS_PORT = 8765
HTTP_PORT = 8001

# 嵌入的 HTML 模板 (静态部分，不需要 format)
HTML_TEMPLATE_BODY = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Speech Recognition Worker</title>
</head>
<body>
    <h1>Listening...</h1>
    <div id="output">Waiting for speech...</div>
    <div id="status">initializing</div>
    <script>
        const outputDiv = document.getElementById('output');
        const statusDiv = document.getElementById('status');
        
        // 配置参数 (由 Python 头部注入)
        // const WATCHDOG_SILENCE_MS = ...;
        // const WATCHDOG_MAX_MS = ...;
        // const WS_URL = ...;

        let ws = null;
        let recognition = null;

        function connectWebSocket() {
            ws = new WebSocket(WS_URL);
            ws.onopen = () => {
                console.log("WS: Connected");
                statusDiv.innerText = "ws_connected";
                // [新增] 发送连接状态
                ws.send(JSON.stringify({"type": "status", "state": "ws_connected"}));
                startRecognition();
            };
            ws.onerror = (e) => {
                console.error("WS: Error", e);
                // 这里不需要重连逻辑，因为 onerror 通常后跟 onclose，由 onclose 处理重连
            };
            ws.onclose = () => {
                statusDiv.innerText = "ws_disconnected";
                setTimeout(connectWebSocket, 2000);
            };
        }

        function startRecognition() {
            if (recognition) return;
            if (!('webkitSpeechRecognition' in window)) {
                outputDiv.innerText = "Error: webkitSpeechRecognition not supported.";
                if (ws && ws.readyState === WebSocket.OPEN) {
                     ws.send(JSON.stringify({"type": "error", "message": "Browser not supported"}));
                }
                return;
            }

            recognition = new webkitSpeechRecognition();
            recognition.continuous = true;
            recognition.interimResults = true;
            recognition.lang = RECOGNITION_LANG;

            let lastResultTime = Date.now();
            let startTime = Date.now();
            
            setInterval(() => {
                const now = Date.now();
                const isSilent = (now - lastResultTime > WATCHDOG_SILENCE_MS);
                const isTooLong = (now - startTime > WATCHDOG_MAX_MS);
                
                if (statusDiv.innerText.includes("listening") && (isSilent || isTooLong)) {
                    console.warn("JS: Watchdog triggered.");
                    statusDiv.innerText = "watchdog_restart";
                    recognition.stop(); 
                }
            }, 500);

            recognition.onstart = () => {
                statusDiv.innerText = "listening";
                lastResultTime = Date.now();
                startTime = Date.now();
                console.log("JS: Speech recognition started.");
                // [新增] 发送监听状态
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({"type": "status", "state": "listening"}));
                }
            };

            recognition.onerror = (e) => {
                console.error("JS: Error", e.error);
                // [新增] 发送错误状态
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({"type": "error", "message": e.error}));
                }
            };
            recognition.onend = () => {
                statusDiv.innerText = "stopped";
                recognition.start();
            };

            recognition.onresult = (event) => {
                lastResultTime = Date.now();
                let combinedInterim = "";
                for (let i = event.resultIndex; i < event.results.length; ++i) {
                    const transcript = event.results[i][0].transcript;
                    const isFinal = event.results[i].isFinal;
                    
                    if (isFinal) {
                        // 遇到 Final，立即发送，并清空之前的 Interim 暂存
                        if (ws && ws.readyState === WebSocket.OPEN) {
                            ws.send(JSON.stringify({"text": transcript, "is_final": true}));
                        }
                        combinedInterim = ""; 
                        outputDiv.innerText = "FINAL: " + transcript;
                    } else {
                        // 累加 Interim
                        combinedInterim += transcript;
                    }
                }

                // 处理循环结束后剩余的 Interim
                if (combinedInterim.length > 0) {
                    if (ws && ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify({"text": combinedInterim, "is_final": false}));
                    }
                    outputDiv.innerText = "INTERIM: " + combinedInterim;
                }
            };
            recognition.start();
        }
        connectWebSocket();
    </script>
</body>
</html>
"""

class SpeechService:
    def __init__(self, config: dict, callback, status_callback=None):
        self.config = config
        self.callback = callback
        self.status_callback = status_callback
        self.driver = None
        self.is_running = False
        self._threads = []

    def start(self):
        if self.is_running: return
        self.is_running = True
        
        # 启动三个服务：WS, HTTP, Chrome
        targets = [self._run_ws_server, self._run_http_server, self._run_driver]
        for target in targets:
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self):
        self.is_running = False
        if self.driver:
            try: self.driver.quit()
            except: pass

    def _run_http_server(self):
        """简单的 HTTP 服务器，让 Chrome 在安全上下文中运行"""
        handler = http.server.SimpleHTTPRequestHandler
        # 屏蔽 HTTP 服务器的控制台日志，避免干扰
        handler.log_message = lambda *args: None 
        with socketserver.TCPServer((WS_HOST, HTTP_PORT), handler) as httpd:
            logger.info(f"HTTP Server started on {WS_HOST}:{HTTP_PORT}")
            while self.is_running:
                httpd.handle_request()

    def _run_ws_server(self):
        async def handler(websocket):
            logger.info("WS: Client connected")
            try:
                async for message in websocket:
                    data = json.loads(message)
                    # [新增] 处理状态回传
                    if "type" in data:
                        msg_type = data["type"]
                        if msg_type == "status" and self.status_callback:
                            self.status_callback(data["state"])
                        elif msg_type == "error":
                            err_msg = data.get("message", "Unknown Error")
                            logger.error(f"Chrome Speech Error: {err_msg}")
                            if self.status_callback:
                                self.status_callback(f"Error: {err_msg}")
                    else:
                        # 兼容旧协议：纯文本识别结果
                        self.callback(data.get("text", ""), data.get("is_final", False))
            except: pass

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        async def main():
            try:
                async with websockets.serve(handler, WS_HOST, WS_PORT):
                    await asyncio.get_running_loop().create_future()
            except OSError as e:
                # [新增] 端口占用捕获
                logger.error(f"WS Port {WS_PORT} is busy: {e}")
                if self.status_callback:
                    self.status_callback(f"Port {WS_PORT} Busy!")

        try:
            loop.run_until_complete(main())
        except Exception as e:
            logger.error(f"WS Server error: {e}", exc_info=True)

    def _run_driver(self):
        chrome_cfg = self.config.get("chrome", {})
        sr_cfg = self.config.get("speech_recognition", {})
        
        # 1. 准备 HTML (使用注入方式，避免 format 报错)
        html_path = "speech_worker.html"
        
        # 构造配置脚本块
        # [新增] 注入语音识别语言配置
        sr_lang = sr_cfg.get("language", "en-US")
        config_script = f"""
        <script>
            const WATCHDOG_SILENCE_MS = {sr_cfg.get("watchdog_silence_ms", 8000)};
            const WATCHDOG_MAX_MS = {sr_cfg.get("watchdog_max_duration_ms", 60000)};
            const RECOGNITION_LANG = "{sr_lang}";
            const WS_URL = "ws://{WS_HOST}:{WS_PORT}";
        </script>
        """
        
        # 插入到 <body> 标签后
        final_html = HTML_TEMPLATE_BODY.replace("<body>", f"<body>{config_script}")
        
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(final_html)

        # 2. 配置 Chrome
        options = Options()
        options.add_argument("--use-fake-ui-for-media-stream")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        
        # [性能优化] 极致瘦身
        options.add_argument("--blink-settings=imagesEnabled=false") # 禁用图片加载
        options.add_argument("--disable-extensions") # 禁用所有扩展
        options.add_argument("--disable-plugins") # 禁用插件
        options.add_argument("--disable-logging") # 禁用 Chrome 内部日志
        options.add_argument("--disable-default-apps")
        options.add_argument("--no-first-run")
        
        # [隐蔽] 禁用自动化栏和扩展 (防止被检测)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        # [隐蔽] 关键：禁用 Blink 引擎的自动化控制特性
        options.add_argument("--disable-blink-features=AutomationControlled")
        
        # [优化] 禁用 Chrome 内置的音频处理服务，可能有助于提高对微弱人声的捕捉能力
        options.add_argument("--disable-features=AudioServiceOutOfProcess")

        # [隐蔽] 伪装 User-Agent (去除 HeadlessChrome 标识)
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        # [修复] 恢复代理设置
        proxy_cfg = self.config.get("proxy", {})
        if proxy_cfg.get("enabled"):
            # 逻辑：优先检查 HTTP 配置，如果为空则检查 SOCKS5
            http_addr = proxy_cfg.get("http", "").replace("http://", "").replace("https://", "")
            socks5_addr = proxy_cfg.get("socks5", "").replace("socks5://", "")
            
            if http_addr:
                # Chrome 默认将 IP:Port 视为 HTTP 代理
                options.add_argument(f'--proxy-server={http_addr}')
                logger.info(f"Using HTTP Proxy: {http_addr}")
            elif socks5_addr:
                # 对于 SOCKS5，Chrome 需要明确指定协议头
                # 格式: --proxy-server="socks5://127.0.0.1:10808"
                options.add_argument(f'--proxy-server=socks5://{socks5_addr}')
                logger.info(f"Using SOCKS5 Proxy: {socks5_addr}")

        # [修复] 解决 DevToolsActivePort 错误 & 权限问题
        options.add_argument("--remote-debugging-port=9222")
        options.add_argument(f'--user-data-dir={os.path.abspath("chrome_data")}')
        
        if chrome_cfg.get("use_headless", True):
            options.add_argument("--headless=new")

        binary_path = chrome_cfg.get("binary_path", "")
        if os.path.exists(binary_path): options.binary_location = binary_path

        try:
            self.driver = webdriver.Chrome(options=options)
            
            # [隐蔽] 终极绝招：通过 CDP 在页面加载前修改 navigator.webdriver
            # 这比简单的 JS 注入更有效，因为它发生在任何网页脚本运行之前
            self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    })
                """
            })
            
            logger.info(f"Chrome started. Opening http://{WS_HOST}:{HTTP_PORT}/{html_path}")
            self.driver.get(f"http://{WS_HOST}:{HTTP_PORT}/{html_path}")
            
            # [优化] 移除日志轮询，降低 CPU 占用
            # 仅做简单的存活检查
            while self.is_running:
                time.sleep(1)
                
        except Exception as e:
            logger.error(f"Driver error: {e}", exc_info=True)
        finally:
            self.stop()