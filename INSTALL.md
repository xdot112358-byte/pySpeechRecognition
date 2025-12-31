# pySpeechRecognition 安装与配置指南

欢迎使用 pySpeechRecognition！本指南将引导你完成从环境搭建到软件运行的全过程。

---

## 第一步：安装虚拟声卡 (VB-Audio Cable)

*如果你只想识别麦克风的声音，可以跳过此步。如果你想识别电脑里播放的声音（如视频、网课），这是必须的。*

1.  **下载**：访问 [VB-Audio 官网](https://vb-audio.com/Cable/)，下载 **"VB-CABLE Driver Pack for Windows"**。
2.  **安装**：解压后右键点击 `VBCABLE_Setup_x64.exe`，选择 **“以管理员身份运行”**，点击 **"Install Driver"**。
3.  **重启**：安装完成后请务必重启电脑。
4.  **设置输出**：点击系统右下角声音图标，将输出设备设置为 **CABLE Input (VB-Audio Virtual Cable)**。
    *   *提示：此时你听不到声音，请在“录制”设置里右键 CABLE Output -> 属性 -> 侦听 -> 勾选“侦听此设备”并选择你的耳机。*

---

## 第二步：环境准备

### 1. 安装 Python
前往 [Python 官网](https://www.python.org/downloads/) 下载 Python 3.10 或更高版本。安装时务必勾选 **"Add Python to PATH"**。

### 2. 下载专用 Chrome 和 ChromeDriver (关键)
为了保证稳定性并防止被检测，建议使用 Chrome for Testing 专用版。

1.  访问下载地址：**[Chrome for Testing #Stable](https://googlechromelabs.github.io/chrome-for-testing/#stable)**
2.  在 **win64** 栏目下，分别下载：
    *   **chrome** (对应二进制文件)：用于运行识别引擎。
    *   **chromedriver** (对应驱动文件)：用于 Python 控制浏览器。
3.  **放置路径**：
    *   将 `chrome-win64.zip` 解压到项目根目录下的 `chrome-win64` 文件夹。
    *   将 `chromedriver-win64.zip` 解压到项目根目录下的 `chromedriver-win64` 文件夹。
    *   项目结构应类似：
        ```text
        E:\pySpeechRecognition\
        ├── chrome-win64\chrome-win64\chrome.exe
        └── chromedriver-win64\chromedriver-win64\chromedriver.exe
        ```

---

## 第三步：安装项目依赖

在项目根目录下打开命令行（cmd 或 PowerShell），执行：

```bash
pip install -r requirements.txt
```

---

## 第四步：配置 config.json

1.  将 `config.json.template` 复制一份并重命名为 `config.json`。
2.  打开 `config.json`，根据实际情况修改：
    *   **proxy**: 设置你的科学上网代理（Google 翻译必填）。
    *   **chrome**: 确认 `binary_path` 和 `driver_path` 指向你刚才下载的文件路径。
    *   **speech_recognition**: 设置 `language` (如 `en-US` 或 `zh-CN`)。
    *   **ui**: 可自定义窗口宽度、字体大小、颜色等。

---

## 第五步：运行

-   **正式使用**：双击 `start_app.vbs`（静默启动，无黑框）。
-   **调试排错**：双击 `run.bat`（显示命令行日志，方便看报错）。

---

## 常见问题

**Q: 点击 X 按钮没有彻底退出？**
A: 软件已内置递归进程清理机制，会自动杀掉当前启动的 Chrome 和 Driver。

**Q: 窗口大小调节很抖动？**
A: 请在配置中检查 `animation` 参数，默认已开启平滑阻尼动画和延迟收缩。

**Q: 无法显示翻译历史？**
A: 历史记录会在第一次产生翻译后自动展开。如果想手动控制，请点击底部的三角按钮。
