# 拖拽转录台

把 webm / mp4 / mp3 等音视频**拖进窗口**，自动解码并转写成文字，完成后直接得到排版好的 Word 文档。全程在本机运行，不上传任何内容。

界面只有一个拖放区：拖进去 → 进度条 + 实时滚出的文字 → 底部可复制或导出。

## 它需要什么

| 依赖 | 说明 |
| --- | --- |
| 解码 | 优先用系统 ffmpeg；没有就用内置的 PyAV 解码，所以安装包不需要额外装 ffmpeg |
| 语音模型 | 首次转写自动下载到本机数据目录，约 1.6GB，只需一次 |
| 显卡（可选） | Windows/Linux 有 NVIDIA 显卡会走 GPU，速度快 5～10 倍；没有就用 CPU |

数据目录位置：Windows `%LOCALAPPDATA%\webm-transcriber`，macOS `~/Library/Application Support/webm-transcriber`，Linux `~/.local/share/webm-transcriber`。

## 安装（用安装包的人）

- **Windows**：运行 `拖拽转录-Setup.exe`，或解压 zip 后双击 `Transcriber.exe`。首次运行若弹 SmartScreen，点「更多信息 → 仍要运行」（本程序未做付费签名）。
- **macOS**：打开 dmg，把 App 拖进「应用程序」。目前只提供 Apple Silicon 包（Intel Mac 请从源码运行）。首次打开若提示"无法验证开发者"，在 App 上右键 → 打开 → 再点一次打开；仍不行就在终端执行 `xattr -cr /Applications/Transcriber.app`。
- **Linux**：解压 tar.gz 后运行里面的 `Transcriber`（`tar -xzf *.tar.gz && ./Transcriber/Transcriber`）。

转写结果默认落在**源文件旁边的「转录结果」文件夹**里（源目录不可写时才落到数据目录），界面底部「打开文件夹」可直接定位。

不想开界面也可以：把文件**拖到程序图标上**，或命令行 `Transcriber.exe 录音.webm`，会直接转写并落盘。

## 从源码运行（开发者）

```bash
python -m pip install -r requirements.txt
python app.py                    # 图形界面
python transcribe.py 录音.webm   # 命令行，结果写 ./output
```

命令行可选：`--lang=es`（指定语言，比自动检测准）、`--out=目录`、`--fmt=txt,md,srt,docx,vtt,json`。
已有转写结果想重新排版，不必重跑转录：`python reexport.py 某.srt --mode=lines`。

自检：`python test_gui.py`（21 项，打印 `GUI_OK` 即通过）、`python shot.py <txt>`（把界面渲染成图，检查排版）。

## 环境变量

| 变量 | 作用 |
| --- | --- |
| `W2T_HOME` | 数据目录（模型下载位置） |
| `W2T_MODEL_DIR` | 直接指定已存在的模型目录，跳过下载 |
| `W2T_MODEL` | 换模型，如 `large-v3`（更准更慢） |
| `W2T_FFMPEG` / `W2T_FFPROBE` | 指定 ffmpeg 路径 |
| `W2T_CUDA_DIR` | 放 `cudnn/cublas` 等 dll 的目录，指定后 Windows 走 GPU |

## 坏录像自动修复

浏览器 MediaRecorder（网课、会议、屏幕录制）被强杀或断电后，文件开头的 EBML/Info/Tracks 会丢，
播放器打不开但数据其实完好。拖这种文件进来会先自动重建头部再转写：
修好的录像留在源文件旁的「修复后」目录，Word 里会注明这份转写来自重建过头部的录像。

## 多语言与双语对照

转写支持 24 种语言（默认自动检测），双语的语向可以自选：底部「转写」选源语言、「译为」选译文语言，
勾上「双语」后 Word 与 md 会变成对照版 —— 原文加粗、译文紧随其下，元信息行标出「语向 西班牙语 → 法语」。
翻译用本机推理的 NLLB-200 模型，不联网、不上传内容；语向不支持时自动退回纯原文，不中断转写。

命令行同理：`python transcribe.py 录音.webm --lang=es --bilingual --tgt=fr`。

模型不随安装包分发（HF 上原始权重是 gated 的），首次勾选翻译时会自动从本项目 Release 下载
int8 版约 600MB。若下载不到，维护者需先构建一次：

```bash
# 1) 在 https://huggingface.co/facebook/nllb-200-distilled-600M 点 Agree and Access
# 2) 设好 HF_TOKEN 与 GH_PAT
python scripts/build_mt_model.py
```

没翻译模型时软件照常出纯原文转写，不会报错中断。

## 导出格式

Word（自动排版：按停顿聚段、时间标签、页码、中西文双字体）、Word（逐句对照）、txt、md、srt、vtt、json。
勾了双语的话，Word 与 md 会自动变成西中对照版。

## 已知限制

- 转写文本不带标点，程序只做轻度美化（首字母大写、段末补句号），不改词。
- macOS 没有可用的 CUDA 后端，只能 CPU 推理，长音频明显更慢。
- 未做代码签名与公证，首次运行会被 SmartScreen / Gatekeeper 拦一次。
