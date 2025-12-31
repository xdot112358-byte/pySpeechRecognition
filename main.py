import json
import os
import time
import logging
import threading
import queue
import sys
import traceback
# 仅导入轻量级 UI，延迟导入重型服务
from ui_overlay import OverlayWindow

# 配置日志
def load_config():
    if not os.path.exists("config.json"):
        return {}
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)

# 预加载配置以设置日志
_config = load_config()
_log_handlers = [logging.StreamHandler()]
if _config.get("logging", {}).get("file_logging", True):
    # 使用 mode='w' 确保每次启动时覆盖旧日志
    _log_handlers.append(logging.FileHandler("app.log", mode='w', encoding="utf-8"))

log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    handlers=_log_handlers
)
logger = logging.getLogger("Main")

# --- [新增] 全局异常捕获 & Stderr 重定向 ---
class StreamToLogger(object):
    """
    Fake file-like stream object that redirects writes to a logger instance.
    """
    def __init__(self, logger, level):
        self.logger = logger
        self.level = level
        self.linebuf = ''

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.level, line.rstrip())

    def flush(self):
        pass

# 重定向 stdout 和 stderr
sys.stdout = StreamToLogger(logger, logging.INFO)
sys.stderr = StreamToLogger(logger, logging.ERROR)

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

def handle_thread_exception(args):
    logger.critical(f"Uncaught exception in thread: {args.thread.name}", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

sys.excepthook = handle_exception
threading.excepthook = handle_thread_exception
# ---------------------------

class AppController:
    def __init__(self):
        self.config = _config
        self.msg_queue = queue.Queue() # 语音消息队列
        self.trans_queue = queue.Queue() # 翻译任务队列
        
        # 1. 极速启动 UI (显示加载状态)
        logger.info("Starting UI...")
        self.ui = OverlayWindow(self.config, on_close_callback=self.shutdown)
        self.ui.update_english("Initializing...")
        self.ui.update_chinese("正在加载组件...")

        # 2. 异步加载重型服务 (避免阻塞 UI 出现)
        self.translator = None
        self.speech_service = None
        
        # 状态追踪
        self.last_translate_time = 0
        self.last_english_text = ""
        self.interim_translate_trigger_threshold = self.config.get("translation", {}).get("interim_translate_trigger_threshold", 50)
        self.interim_translate_min_threshold = self.config.get("translation", {}).get("interim_translate_min_threshold", 20)
        self.interim_timeout = self.config.get("translation", {}).get("interim_translate_timeout", 2.0)
        self.interim_debounce_interval = self.config.get("translation", {}).get("interim_debounce_interval", 1.0) # [新增] 冷却时间

    def shutdown(self):
        """
        通过 taskkill /T 递归终结当前进程树，这是清理 Selenium 残留最彻底且简单的方法。
        """
        logger.info("Shutdown sequence initiated...")
        
        # 1. 尝试优雅关闭 (可选，为了保存某些状态)
        if self.speech_service:
            try: self.speech_service.stop()
            except: pass
            
        # 2. 终极自杀：连带所有子进程 (chromedriver, chrome) 一起带走
        logger.info("Killing process tree...")
        pid = os.getpid()
        # /F 强制, /T 包含子进程
        os.system(f"taskkill /F /T /PID {pid}")

    def _load_services(self):
        """
        后台加载服务，完成后启动它们
        """
        logger.info("Loading services in background...")
        try:
            # 延迟导入，减少冷启动时间
            from translator_service import DeepTranslatorService
            from speech_service import SpeechService
            
            # 初始化翻译服务
            self.translator = DeepTranslatorService(self.config)
            
            # 初始化语音服务
            self.speech_service = SpeechService(self.config, self.on_speech_result)
            self.speech_service.start() # 启动 Chrome
            
            # 启动翻译工作线程
            threading.Thread(target=self._translation_worker, daemon=True).start()
            
            # 更新 UI 状态
            self.ui.root.after(0, lambda: self.ui.update_english("Waiting for speech..."))
            self.ui.root.after(0, lambda: self.ui.update_translation("等待语音输入...", ""))
            
            logger.info("Services loaded and started.")
            
        except Exception as e:
            logger.error(f"Failed to load services: {e}", exc_info=True)
            err_msg = str(e)[:50] # 提前转为字符串，避免 lambda 闭包问题
            self.ui.root.after(0, lambda: self.ui.update_english("Error loading services"))
            self.ui.root.after(0, lambda: self.ui.update_chinese(err_msg))

    def _translation_worker(self):
        """
        常驻后台线程，负责处理翻译任务。
        策略：总是只处理队列中最新的任务，丢弃积压的旧任务。
        """
        logger.info("Translation worker started.")
        while True:
            try:
                # 1. 阻塞等待任务
                item = self.trans_queue.get()
                if isinstance(item, tuple):
                    text, reason = item
                else:
                    text = item
                    reason = ""
                
                # 2. 检查队列中是否有更新的任务 (Latest-Win 策略)
                skipped_count = 0
                while not self.trans_queue.empty():
                    try:
                        item = self.trans_queue.get_nowait()
                        if isinstance(item, tuple):
                            text, reason = item
                        else:
                            text = item
                            reason = ""
                        skipped_count += 1
                    except queue.Empty:
                        break
                
                if skipped_count > 0:
                    # 使用醒目的红色加粗显示丢弃任务
                    logger.info(f"\033[91;1mDropped {skipped_count} obsolete translation tasks from queue.\033[0m")

                # 3. 执行翻译
                if text and self.translator:
                    try:
                        start_time = time.time()
                        zh_text = self.translator.translate(text)
                        duration = time.time() - start_time
                        
                        # 附加耗时信息
                        display_text = f"{zh_text} {reason} (耗时{duration:.2f}s)"
                        
                        # 4. 调度 UI 更新
                        # 使用默认参数绑定变量，防止闭包延迟绑定导致的不一致
                        is_final = "[Final]" in reason
                        self.ui.root.after(0, lambda d=display_text, t=text, f=is_final: self.ui.update_translation(d, t, f))
                    except Exception as e:
                        logger.error(f"Translation logic error: {e}", exc_info=True)
            
            except Exception as e:
                logger.error(f"Worker crashed: {e}", exc_info=True)
                time.sleep(1) 

    def on_speech_result(self, text, is_final):
        self.msg_queue.put({"text": text, "is_final": is_final})

    def process_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                text = msg["text"]
                is_final = msg["is_final"]

                if is_final:
                    logger.info(f"Receive (Final): {text}")
                else:
                    logger.info(f"Receive (Interim): {text}")
                    
                # 1. 立即更新英文 UI
                self.ui.update_english(text)
                
                # 2. 判断是否需要翻译
                should_translate = False
                trigger_reason = ""
                current_time = time.time()
                
                # 只有当文本内容发生变化时才考虑翻译 (基本去重)
                if text != self.last_english_text:
                    if is_final:
                        # 场景 1: Final 结果 -> 立即翻译 (绿色)
                        should_translate = True
                        trigger_reason = "[Final]"
                        logger.info(f"\033[92mTrigger Translation (Final): {text}\033[0m")
                    else:
                        # 场景 2: Interim 结果 -> 混合策略 (青色)
                        is_long_enough = len(text) >= self.interim_translate_trigger_threshold
                        is_timeout = (current_time - self.last_translate_time) > self.interim_timeout
                        
                        # [Debounce] 计算距离上次翻译的时间
                        time_since_last = current_time - self.last_translate_time

                        if is_long_enough:
                             # 只有当冷却时间已过，才允许触发长句中间翻译
                             if time_since_last > self.interim_debounce_interval:
                                 should_translate = True
                                 trigger_reason = "[Len]"
                                 logger.info(f"\033[93mTrigger Translation (Interim Length): {text}\033[0m")
                        elif is_timeout and (len(text) >= self.interim_translate_min_threshold):
                             should_translate = True
                             trigger_reason = "[Time]"
                             logger.info(f"\033[93mTrigger Translation (Interim Timeout): {text}\033[0m")

                # 3. 提交翻译任务
                if should_translate:
                    self.trans_queue.put((text, trigger_reason))
                    self.last_translate_time = current_time
                    self.last_english_text = text

        except queue.Empty:
            pass
        
        self.ui.root.after(100, self.process_queue)

    def run(self):
        # 启动后台线程加载重型服务
        threading.Thread(target=self._load_services, daemon=True).start()
        
        # 启动队列轮询
        self.ui.root.after(100, self.process_queue)
        
        try:
            # 启动 UI 主循环
            self.ui.start()
        except KeyboardInterrupt:
            pass
        finally:
            logger.info("Shutting down...")
            if self.speech_service:
                self.speech_service.stop()
            logger.info("Cleanup complete. Force exiting.")
            os._exit(0)

if __name__ == "__main__":
    app = AppController()
    app.run()