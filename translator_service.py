import os
import logging
import random
import requests
from requests.adapters import HTTPAdapter
from abc import ABC, abstractmethod
from deep_translator import GoogleTranslator
from functools import lru_cache

# 获取日志记录器
logger = logging.getLogger("Translator")

# --- [智能网络层] SmartSession 实现 ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0"
]

class SmartSession:
    def __init__(self):
        self.session = None
        self._refresh_session()

    def _refresh_session(self):
        """备案逻辑：重置会话，清理连接池，切换身份"""
        if self.session:
            try:
                self.session.close()
            except:
                pass
        
        self.session = requests.Session()
        
        # 基础适配器 (减少底层自动重试，交由上层逻辑控制)
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # 随机切换 User-Agent
        ua = random.choice(USER_AGENTS)
        self.session.headers.update({
            "User-Agent": ua,
            "Accept-Language": "en-US,en;q=0.9"
        })
        logger.info(f"SmartSession refreshed. UA: {ua[:30]}...")

    def request(self, method, url, **kwargs):
        """
        带重试和自动修复的网络请求包装器。
        规则：连续3次失败后，启用备案（重置会话）。
        """
        max_retries = 3
        last_error = None

        # 尝试前 3 次
        for attempt in range(1, max_retries + 1):
            try:
                # 显式设置超时，防止挂死
                if 'timeout' not in kwargs:
                    kwargs['timeout'] = 5
                
                return self.session.request(method, url, **kwargs)
            except Exception as e:
                last_error = e
                logger.warning(f"Connection error (Attempt {attempt}/{max_retries}): {e}")
        
        # 如果代码走到这里，说明连续 3 次都失败了
        # 触发备案：重置环境
        logger.warning("3 consecutive errors detected. Activating Backup Plan: Resetting Session...")
        self._refresh_session()
        
        # 备案后的“背水一战” (第 4 次尝试)
        try:
            return self.session.request(method, url, **kwargs)
        except Exception as e:
            # 如果还不行，那通过上层抛出异常
            raise e

# 实例化全局智能会话
_smart_session = SmartSession()

# Monkey Patch: 动态替换 requests 的核心方法
requests.get = lambda url, **kwargs: _smart_session.request('GET', url, **kwargs)
requests.post = lambda url, **kwargs: _smart_session.request('POST', url, **kwargs)
# ----------------------------------------------

class ITranslator(ABC):
    """
    翻译服务的抽象基类，方便未来替换其他翻译引擎。
    """
    @abstractmethod
    def translate(self, text: str) -> str:
        pass

class DeepTranslatorService(ITranslator):
    def __init__(self, config: dict):
        """
        初始化翻译服务
        :param config: 包含代理设置的配置字典
        """
        self.config = config
        self._setup_proxy()
        
        # [修改] 从配置读取源语言和目标语言
        trans_cfg = self.config.get("translation", {})
        source_lang = trans_cfg.get("source_lang", "en")
        target_lang = trans_cfg.get("target_lang", "zh-CN")
        
        logger.info(f"Initializing Translator: {source_lang} -> {target_lang}")
        self.translator = GoogleTranslator(source=source_lang, target=target_lang)

    def _setup_proxy(self):
        """
        如果配置了代理，将其注入到环境变量中，
        deep_translator 底层使用的 requests 库会自动读取这些环境变量。
        """
        proxy_cfg = self.config.get("proxy", {})
        if proxy_cfg.get("enabled"):
            http_proxy = proxy_cfg.get("http")
            https_proxy = proxy_cfg.get("https")
            socks5_proxy = proxy_cfg.get("socks5")
            
            # 优先使用显式配置的 HTTP/HTTPS 代理
            if http_proxy:
                os.environ["HTTP_PROXY"] = http_proxy
                logger.info(f"Set HTTP_PROXY to {http_proxy}")
            elif socks5_proxy:
                # 如果没配置 HTTP 代理但有 SOCKS5，则将 SOCKS5 应用于 HTTP 协议
                # requests 库支持 socks5:// 协议头 (需要 PySocks)
                socks_url = f"socks5://{socks5_proxy}"
                os.environ["HTTP_PROXY"] = socks_url
                logger.info(f"Set HTTP_PROXY to {socks_url}")

            if https_proxy:
                os.environ["HTTPS_PROXY"] = https_proxy
                logger.info(f"Set HTTPS_PROXY to {https_proxy}")
            elif socks5_proxy:
                # 同上，应用于 HTTPS
                socks_url = f"socks5://{socks5_proxy}"
                os.environ["HTTPS_PROXY"] = socks_url
                logger.info(f"Set HTTPS_PROXY to {socks_url}")

    @lru_cache(maxsize=1000)
    def translate(self, text: str) -> str:
        if not text or not text.strip():
            return ""
        
        try:
            # 执行翻译
            result = self.translator.translate(text)
            return result
        except Exception as e:
            logger.error(f"Translation failed: {e}", exc_info=True)
            # 提取错误信息，去除换行，并截断以适应 UI
            err_msg = str(e).replace("\n", " ").replace("\r", "")
            if len(err_msg) > 40:
                err_msg = err_msg[:37] + "..."
            return f"[Err: {err_msg}]"
