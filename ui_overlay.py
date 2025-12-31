import tkinter as tk
from tkinter import font
import logging
import json
import os
import sys
import re
from datetime import datetime

logger = logging.getLogger("OverlayWindow")

class OverlayWindow:
    def __init__(self, config: dict, on_close_callback=None):
        self.config = config
        self.on_close_callback = on_close_callback
        self.root = tk.Tk()
        
        # [状态管理]
        self.is_expanded = False
        self.history = []
        self.last_zh = "" 
        self.last_is_final = False
        self._is_closing = False 
        self._has_ever_had_history = False # [新增] 用于实现“首次产生数据自动打开”逻辑
        
        # [动画状态]
        self.target_height = 0
        self.current_height = 0
        self._animating = False
        self._shrink_job = None 
        self._pending_shrink_height = None # [新增] 记录正在等待收缩的目标高度
        
        # [性能优化] 预编译正则表达式
        self._zh_pattern = re.compile(r'([\u4e00-\u9fa5])')

        self._setup_window()
        self._setup_ui_structure() 
        self._setup_drag_events()
        
        self.update_height()

    def _setup_window(self):
        ui_cfg = self.config.get("ui", {})
        self.root.title("Speech Overlay")
        
        w = ui_cfg.get('width', 800)
        h = 10 
        x = ui_cfg.get('x', 100)
        y = ui_cfg.get('y', 100)
        
        # 初始化当前高度状态
        self.current_height = h
        
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        
        bg_color = ui_cfg.get("bg_color", "#000000")
        self.root.configure(bg=bg_color)
        alpha = ui_cfg.get("bg_alpha", 0.6)
        self.root.attributes("-alpha", alpha)

    def _setup_ui_structure(self):
        ui_cfg = self.config.get("ui", {})
        bg_color = ui_cfg.get("bg_color", "#000000")
        font_family = ui_cfg.get("font_family", "Arial")

        # --- 1. 历史记录面板 (Layer: Bottom 1) ---
        hi_cfg = ui_cfg.get("history", {"font_size": 16, "color": "#BBBBBB", "count": 2})
        self.frm_history = tk.Frame(self.root, bg=bg_color)
        
        # [重构] 使用 Frame 容器包裹每行历史记录
        self.history_rows = [] 
        self.history_bullets = [] 
        self.history_times = [] 
        self.history_row_frames = [] # [新增] 管理行容器的显隐
        
        for i in range(hi_cfg.get("count", 2)):
            # 行容器 Frame
            row_frame = tk.Frame(self.frm_history, bg=bg_color, bd=0, highlightthickness=0)
            # 初始不 pack，由 _update_history_view 动态控制
            self.history_row_frames.append(row_frame)
            
            # 1. 左侧 Bullet Label
            lbl_bullet = tk.Label(
                row_frame,
                text="", 
                font=(font_family, hi_cfg.get("font_size", 16)),
                fg=hi_cfg.get("color", "#BBBBBB"),
                bg=bg_color,
                anchor="n", 
                bd=0, highlightthickness=0
            )
            lbl_bullet.pack(side=tk.LEFT, anchor="nw")
            self.history_bullets.append(lbl_bullet)
            
            # 2. 右侧时间 Label
            lbl_time = tk.Label(
                row_frame,
                text="",
                font=(font_family, hi_cfg.get("time_font_size", 12)),
                fg=hi_cfg.get("time_color", "#888888"),
                bg=bg_color,
                anchor="n",
                bd=0, highlightthickness=0
            )
            lbl_time.pack(side=tk.RIGHT, anchor="ne", padx=(5, 0))
            self.history_times.append(lbl_time)

            # 3. 中间 Text Label
            lbl_text = tk.Label(
                row_frame,
                text="",
                font=(font_family, hi_cfg.get("font_size", 16)),
                fg=hi_cfg.get("color", "#BBBBBB"),
                bg=bg_color,
                wraplength=ui_cfg.get("width", 800) - 120, 
                justify=tk.LEFT,
                anchor="w", 
                bd=0, highlightthickness=0
            )
            lbl_text.pack(side=tk.LEFT, fill=tk.X, expand=True, anchor="w")
            
            self.history_rows.append(lbl_text)

        # --- 2. 控制栏 (Layer: Bottom 2) ---
        self.frm_control = tk.Frame(self.root, bg=bg_color)
        self.frm_control.pack(side=tk.BOTTOM, fill=tk.X, expand=False)
        
        self.separator = tk.Frame(self.frm_control, bg="#555555", height=1) 
        self.separator.pack(fill=tk.X, padx=10, pady=0)
        
        # 按钮
        self.btn_toggle = tk.Label(
            self.frm_control,
            text="▼", 
            font=("Arial", 10),
            fg="#333333", # [初始] 暗灰色，表示不可点击
            bg=bg_color,
            cursor="arrow" # [初始] 普通箭头
        )
        self.btn_toggle.pack(pady=2)
        self.btn_toggle.bind("<Button-1>", self.toggle_history)

        # --- 3. 上部内容容器 (Layer: Top, fill rest) ---
        self.frm_content = tk.Frame(self.root, bg=bg_color)
        self.frm_content.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        en_cfg = ui_cfg.get("english", {})
        self.en_font = font.Font(family=font_family, size=en_cfg.get("font_size", 16))
        self.lbl_english = tk.Label(
            self.frm_content, 
            text="Waiting for speech...", 
            font=self.en_font,
            fg=en_cfg.get("color", "#FF0000"),
            bg=bg_color,
            wraplength=ui_cfg.get("width", 800) - 20
        )
        self.lbl_english.pack(side=tk.TOP, fill=tk.X, expand=False, padx=10, pady=(10, 5))

        zh_cfg = ui_cfg.get("chinese", {})
        self.zh_font = font.Font(family=font_family, size=zh_cfg.get("font_size", 24), weight="bold")
        self.lbl_chinese = tk.Label(
            self.frm_content, 
            text="等待语音输入...", 
            font=self.zh_font,
            fg=zh_cfg.get("color", "#FFFFFF"),
            bg=bg_color,
            wraplength=ui_cfg.get("width", 800) - 20
        )
        self.lbl_chinese.pack(side=tk.TOP, fill=tk.X, expand=False, padx=10, pady=(0, 5))

        # 3.3 原文对照 (配对原文)
        src_cfg = ui_cfg.get("source", {"font_size": 14, "color": "#00FF00"})
        self.src_font = font.Font(family=font_family, size=src_cfg.get("font_size", 14)) 
        self.lbl_source = tk.Label(
            self.frm_content, 
            text="", 
            font=self.src_font,
            fg=src_cfg.get("color", "#00FF00"),
            bg=bg_color,
            wraplength=ui_cfg.get("width", 800) - 20
        )
        self.lbl_source.pack(side=tk.TOP, fill=tk.X, expand=False, padx=10, pady=(0, 10))

        # --- 4. 关闭按钮 ---
        self.btn_close = tk.Label(
            self.root,
            text="×",
            font=("Arial", 28, "bold"), 
            fg="#FF5555",
            bg=bg_color,
            cursor="hand2",
            padx=10, pady=0 
        )
        self.btn_close.place(relx=1.0, x=0, y=0, anchor="ne")
        self.btn_close.bind("<Button-1>", lambda e: self.quit())
        self.btn_close.lift()

    def _setup_drag_events(self):
        def on_start_move(event):
            if self._is_closing: return 
            # [修复] 记录按下时的屏幕绝对坐标和窗口当前位置
            self._drag_start_x = event.x_root
            self._drag_start_y = event.y_root
            self._win_start_x = self.root.winfo_x()
            self._win_start_y = self.root.winfo_y()

        def on_do_move(event):
            if self._is_closing: return 
            try:
                # [修复] 计算屏幕坐标的偏移量
                delta_x = event.x_root - self._drag_start_x
                delta_y = event.y_root - self._drag_start_y
                
                # 应用偏移量到窗口原始位置
                new_x = self._win_start_x + delta_x
                new_y = self._win_start_y + delta_y
                
                self.root.geometry(f"+{new_x}+{new_y}")
            except Exception:
                pass 

        def bind_recursive(widget):
            if widget in [self.btn_close, self.btn_toggle]:
                return
            try:
                widget.bind("<Button-1>", on_start_move, add="+ ")
                widget.bind("<B1-Motion>", on_do_move, add="+ ")
            except: pass
            for child in widget.winfo_children():
                bind_recursive(child)

        bind_recursive(self.root)
            
    def update_english(self, text):
        if self._is_closing: return
        try:
            self.lbl_english.config(text=text)
            self.update_height()
        except: pass

    def update_chinese(self, text):
        if self._is_closing: return
        try:
            self.lbl_chinese.config(text=text)
            self.update_height()
        except: pass

    def update_translation(self, zh_text, en_text, is_final=False):
        if self._is_closing: return
        try:
            # [恢复] 原有的“基于文本突变”逻辑
            # 原理：当收到新句子且新句子不再是旧句子的延续时，归档旧句子
            if self.last_zh and not zh_text.startswith("[Err"):
                is_new_record = self.last_is_final or \
                            (not zh_text.startswith(self.last_zh[:3]) and len(zh_text) < len(self.last_zh))
                
                if is_new_record:
                    clean_text = self.last_zh.split(" (耗时")[0].split(" [Final]")[0].split(" [Len]")[0].split(" [Time]")[0].strip()
                    if clean_text:
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        self.history.append({"text": clean_text, "time": timestamp})
                        
                        max_count = self.config.get("ui", {}).get("history", {}).get("count", 2)
                        if len(self.history) > max_count:
                            self.history.pop(0)
                        self._update_history_view()

            # 更新 UI 显示
            self.lbl_chinese.config(text=zh_text)
            self.lbl_source.config(text=en_text)
            
            self.last_zh = zh_text
            self.last_is_final = is_final
            
            self.update_height()
        except: pass

    def _update_history_view(self):
        if self._is_closing: return
        has_history = len(self.history) > 0
        
        # [优化] 更新按钮状态：没历史时变暗且不可点
        if has_history:
            self.btn_toggle.config(fg="#AAAAAA", cursor="hand2")
            # [新增] 首次产生历史数据时，自动点击展开
            if not self._has_ever_had_history:
                self._has_ever_had_history = True
                if not self.is_expanded:
                    # 必须在主线程队列稍微延迟一下调用，确保 UI 组件已经渲染完成
                    self.root.after(100, self.toggle_history)
        else:
            self.btn_toggle.config(fg="#333333", cursor="arrow")
            # 如果当前正处于展开状态但历史被清空（理论上目前不会发生），则强制收起
            if self.is_expanded:
                self.toggle_history()

        for i, lbl in enumerate(self.history_rows):
            try:
                bullet = self.history_bullets[i]
                time_lbl = self.history_times[i]
                row_frame = self.history_row_frames[i]
                
                if i < len(self.history):
                    item = self.history[i]
                    raw_text = item["text"]
                    time_str = item["time"]
                    
                    formatted_text = self._zh_pattern.sub(lambda m: f"\u200b{m.group(1)}\u200b", raw_text)
                    
                    lbl.config(text=formatted_text)
                    time_lbl.config(text=f"[{time_str}]") 
                    bullet.config(text="•") 
                    # [优化] 只有有数据的行才占用空间
                    row_frame.pack(fill=tk.X, padx=20, pady=2)
                else:
                    lbl.config(text="")
                    time_lbl.config(text="")
                    bullet.config(text="") 
                    # [优化] 没数据的行彻底从布局中移除，不占用高度
                    row_frame.pack_forget()
            except: pass

    def toggle_history(self, event=None):
        if self._is_closing: return
        # [修复] 拦截：如果没有历史记录，点击无效
        if not self.history: return

        self.is_expanded = not self.is_expanded
        
        if self.is_expanded:
            self.btn_toggle.config(text="▲")
            self.frm_history.pack(side=tk.BOTTOM, fill=tk.X, expand=False, pady=0)
        else:
            self.btn_toggle.config(text="▼")
            self.frm_history.pack_forget()
            
        self.update_height(immediate=True)

    def update_height(self, immediate=False):
        """
        核心高度计算逻辑 - 包含动画和延迟收缩策略
        :param immediate: 是否强制立即执行（用于手动交互，跳过延迟）
        """
        if self._is_closing: return
        try:
            self.root.update_idletasks()
            
            content_req_h = self.frm_content.winfo_reqheight()
            control_req_h = self.frm_control.winfo_reqheight()
            base_content_h = content_req_h + control_req_h
            
            ui_cfg = self.config.get("ui", {})
            min_config_h = ui_cfg.get('height', 200)
            
            base_height = max(min_config_h, base_content_h)
            
            extra_history_h = 0
            if self.is_expanded:
                extra_history_h = self.frm_history.winfo_reqheight()
            
            final_height = base_height + extra_history_h + 10 
            
            # --- 高度更新策略 ---
            
            # 1. 如果需要扩张 (final_height > target_height) 或 强制立即执行
            if final_height > self.target_height or immediate:
                # 立即取消任何挂起的收缩任务
                if self._shrink_job:
                    self.root.after_cancel(self._shrink_job)
                    self._shrink_job = None
                
                # [新增] 如果是 immediate 模式下的收缩 (手动收起)，则瞬时到位
                if immediate and final_height < self.target_height:
                    self._animating = False
                    self.target_height = final_height
                    self.current_height = final_height
                    self._apply_geometry(int(final_height))
                    return

                # 否则 (扩张或非收缩 immediate)，应用新高度并启动动画
                self.target_height = final_height
                if not self._animating:
                    self._animate_loop()
            
            # 2. 如果需要收缩 (final_height < target_height)
            elif final_height < self.target_height:
                # [修复] 智能防抖：
                # 只有当收缩目标发生变化时，才重置计时器。
                if self._shrink_job and self._pending_shrink_height is not None:
                    if abs(final_height - self._pending_shrink_height) < 2:
                        return # 目标一致，保持原计划，不重置
                    else:
                        self.root.after_cancel(self._shrink_job)

                # 记录新的计划高度
                self._pending_shrink_height = final_height
                
                # [优化] 自适应延迟策略
                # 如果高度差距巨大 (超过 100 像素)，说明内容已大幅清空，缩短等待时间到 1s
                # 如果差距较小，则维持配置中的长延迟 (如 5s)，保持稳定性
                gap = self.target_height - final_height
                
                anim_cfg = ui_cfg.get("animation", {})
                if gap > 100:
                    delay_sec = 1.0 # 巨幅变化时仅等待 1 秒
                else:
                    delay_sec = anim_cfg.get("shrink_delay", 5.0)
                
                delay_ms = int(delay_sec * 1000)
                
                # 启动延迟任务
                self._shrink_job = self.root.after(delay_ms, lambda h=final_height: self._execute_shrink(h))
                
        except: pass

    def _execute_shrink(self, target_h):
        """延迟回调：真正执行收缩"""
        if self._is_closing: return
        self._shrink_job = None
        
        # 再次确认：只有当新目标确实比当前目标小时才执行
        # (防止竞态条件)
        if target_h < self.target_height:
            self.target_height = target_h
            if not self._animating:
                self._animate_loop()

    def _animate_loop(self):
        """
        动画循环：以阻尼方式逼近目标高度
        """
        if self._is_closing: return
        try:
            diff = self.target_height - self.current_height
            
            # 停止条件：非常接近目标
            if abs(diff) < 1.0:
                self.current_height = self.target_height
                self._apply_geometry(int(self.target_height))
                self._animating = False
                return

            # 阻尼系数策略
            # 变大 (diff > 0): 快速响应 (0.4)，避免文字被遮挡
            # 变小 (diff < 0): 极慢收缩，从配置读取系数
            if diff > 0:
                step = diff * 0.4
                # 至少动 1px，避免最后无限逼近不动
                if step < 1.0: step = 1.0 
            else:
                anim_cfg = self.config.get("ui", {}).get("animation", {})
                factor = anim_cfg.get("shrink_factor", 0.01)
                step = diff * factor
                
                # [优化] 限制最大收缩速度，防止长距离时初速度太快
                # 例如限制每帧最多收缩 2 像素
                if step < -2.0: step = -2.0
            
            # 再次检查停止条件（防止过冲）
            if abs(diff) < 1.0 and abs(step) < 1.0:
                self.current_height = self.target_height
                self._apply_geometry(int(self.target_height))
                self._animating = False
                return

            self.current_height += step
            self._apply_geometry(int(self.current_height))
            
            self._animating = True
            # 约 60fps (16ms)
            self.root.after(16, self._animate_loop)
            
        except Exception:
            self._animating = False

    def _apply_geometry(self, height):
        w = self.root.winfo_width()
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        self.root.geometry(f"{w}x{height}+{x}+{y}")

    def start(self):
        self.root.mainloop()

    def quit(self):
        if self._is_closing: return
        self._is_closing = True 
        
        logger.info("UI Quit requested. Saving state...")
        try:
            x = self.root.winfo_x()
            y = self.root.winfo_y()
            if "ui" not in self.config: self.config["ui"] = {}
            self.config["ui"]["x"] = x
            self.config["ui"]["y"] = y
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
        except: pass

        try:
            self.root.destroy()
        except: pass
        
        logger.info("UI closed. Triggering application shutdown.")
        if self.on_close_callback:
            self.on_close_callback()
        else:
            os._exit(0)
