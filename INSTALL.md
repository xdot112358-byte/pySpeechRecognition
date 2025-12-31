# pySpeechRecognition 安装与配置指南

欢迎使用 pySpeechRecognition！这是一个实时的语音识别与双语翻译字幕工具。

为了让软件能够“听见”电脑里播放的声音（如视频、会议、游戏），你需要按照以下步骤进行配置。请耐心按照顺序操作。

---

## 第一步：安装虚拟声卡 (VB-Audio Cable)

这是关键的一步。我们需要一根“虚拟的音频线”，把电脑播放的声音传输给软件。

1.  **下载软件**：
    *   访问 VB-Audio 官网：[https://vb-audio.com/Cable/](https://vb-audio.com/Cable/)
    *   点击下载 **"VB-CABLE Driver Pack for Windows"** (zip文件)。

2.  **安装驱动**：
    *   解压下载的 zip 文件。
    *   找到 `VBCABLE_Setup_x64.exe`，**右键点击**，选择 **“以管理员身份运行”** (Run as Administrator)。
    *   点击 **"Install Driver"**。
    *   安装完成后，**强烈建议重启电脑**。

3.  **配置 Windows 音频通道**：
    *   重启后，右键点击任务栏右下角的“小喇叭”图标，选择 **“声音设置”** (Sound Settings)。
    *   **设置输出设备 (Output/Playback)**:
        *   将默认输出设备选择为：**CABLE Input (VB-Audio Virtual Cable)**。
        *   *注意：此时你的耳机/扬声器可能会没声音，这是正常的，因为声音都跑进虚拟线里了。如果不使用软件时，请切回原来的扬声器。*
    *   **设置输入设备 (Input/Recording)**:
        *   确保存在设备：**CABLE Output (VB-Audio Virtual Cable)**。软件会自动通过 Chrome 调用它。

---

## 第二步：环境准备

### 1. 安装 Python
如果你还没安装 Python：
*   前往 [Python 官网](https://www.python.org/downloads/) 下载最新的 Python 3.x 版本（建议 3.10 或更高）。
*   **重要**：安装时务必勾选 **"Add Python to PATH"**。

### 2. 检查 Chrome 浏览器
本软件依赖 Chrome 浏览器进行语音识别。
*   打开 Chrome，在地址栏输入 `chrome://settings/help`。
*   查看版本号（例如：`131.0.xxxx.xx`），并确保它是最新的。

### 3. 下载 ChromeDriver (浏览器驱动)
软件需要通过驱动程序控制 Chrome。
*   访问 ChromeDriver 下载页：[https://googlechromelabs.github.io/chrome-for-testing/](https://googlechromelabs.github.io/chrome-for-testing/)
*   下载与你 **Chrome 版本完全一致** 的 `chromedriver-win64.zip`。
*   解压，将 `chromedriver.exe` 放入本项目的 `chromedriver-win64` 文件夹中（或者任何你记得住的地方，稍后在配置文件里填路径）。

---

## 第三步：安装项目依赖

1.  在项目文件夹中，按住 `Shift` 键并右键点击空白处，选择 **“在此处打开 Powershell 窗口”** 或 **“终端”**。
2.  输入以下命令并回车，安装所需的 Python 库：

```bash
pip install -r requirements.txt
```

---

## 第四步：修改配置文件

1.  在项目根目录下，找到 `config.json.template` 文件。
2.  将它重命名为 `config.json`（或者复制一份并重命名）。
3.  用记事本或代码编辑器打开 `config.json`，根据你的实际情况修改。

**重点配置项说明：**

```json
{
    "proxy": {
        "enabled": true, 
        // HTTP/HTTPS 代理 (优先级最高)
        "http": "http://127.0.0.1:10809",
        "https": "http://127.0.0.1:10809",
        // SOCKS5 代理 (仅当 http/https 为空时生效)
        "socks5": "127.0.0.1:10808"
    },
    "chrome": {
        // 填写你电脑上 Chrome.exe 的真实路径
        "binary_path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        // 填写 chromedriver.exe 的路径
        "driver_path": "./chromedriver-win64/chromedriver.exe",
        "use_headless": true
    },
    "speech_recognition": {
        // 语音识别输入语言，常用：
        // "en-US" (英语-默认), "zh-CN" (中文), "ja-JP" (日语)
        "language": "en-US",
        "watchdog_silence_ms": 3000
    },
    "translation": {
        // 翻译设置：从 source_lang 翻译到 target_lang
        "source_lang": "en",    // 源语言
        "target_lang": "zh-CN", // 目标语言
        "interim_translate_trigger_threshold": 50
    }
}
```

---

## 第五步：运行软件

**推荐启动方式：**

1.  **双击运行 `start_app.vbs`**。
    *   这会以静默模式启动软件，不会出现黑色的命令行窗口，提供最佳的 UI 体验。
    *   启动后，稍等片刻，你会看到一个半透明的字幕条出现在屏幕上方。

**调试模式（如果遇到问题）：**

1.  如果你双击 `start_app.vbs` 没有反应，或者想查看报错信息，请双击 `run.bat` 或在命令行运行 `python main.py`。
2.  这样可以看到详细的日志输出，方便排查配置错误。

**使用说明：**
*   **第一行（红色）**：实时识别到的语音内容。
*   **第二行（白色）**：翻译结果。
*   **第三行（绿色）**：翻译原文对照。
*   右上角点击 **×** 或双击字幕条即可退出软件。

---

## 常见问题 (FAQ)

**Q: 字幕条一直显示 "Waiting for speech..."？**
A: 
1. 检查 Windows 声音 **输出** 设备是否选为 **CABLE Input**。
2. 确保 Chrome 路径和 ChromeDriver 版本匹配。
3. 检查代理设置是否正确（Google 翻译必须使用代理）。

**Q: 我想同时听到声音，又想识别？**
A: 开启 Windows 的“侦听”功能：
1. 右键声音图标 -> 声音设置 -> 更多声音设置 -> **录制** 选项卡。
2. 双击 **CABLE Output** -> **“侦听” (Listen)** 选项卡。
3. 勾选 **“侦听此设备”**，并在下方选择你真实的耳机/扬声器。

**Q: 只有红色文字，没有翻译？**
A: 
1. 检查 `config.json` 中的 `proxy` 设置。
2. 确保你能访问 Google 翻译。
3. 观察日志窗口（如果是调试模式运行）是否有报错信息。