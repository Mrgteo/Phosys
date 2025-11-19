# 🎙️ 音频转写系统

> 基于 AI 的实时语音识别与声纹分离系统  
> Domain-Driven Design (DDD) 三层架构设计

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109.0-009688.svg)](https://fastapi.tiangolo.com/)
[![ModelScope](https://img.shields.io/badge/ModelScope-1.11.0-orange.svg)](https://modelscope.cn/)

## 📋 目录

- [系统概述](#系统概述)
- [核心功能](#核心功能)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [API 接口](#api-接口)
- [使用指南](#使用指南)
- [配置说明](#配置说明)
- [技术栈](#技术栈)
- [更新日志](#更新日志)

## 🎯 系统概述

音频转写系统是一个专业的 AI 音频处理平台，能够自动识别音频中的多个说话人，进行精准的语音转文字转换，并可生成结构化的会议纪要。系统采用领域驱动设计（DDD）架构，具有高扩展性和可维护性。

### 主要特点

- 🎯 **多说话人识别**：基于 ModelScope CAM++ 模型，自动识别并区分不同说话人
- 📝 **高精度 ASR**：采用 SeACo-Paraformer 大模型，支持热词定制，识别准确率高
- 🔤 **智能标点恢复**：自动为识别文本添加标点符号，输出格式规范
- 📄 **文档自动生成**：支持导出 Word 格式的转写文档和会议纪要
- 🤖 **AI 会议纪要**：集成 DeepSeek/OpenAI API，自动生成结构化会议纪要
- ⚡ **批量处理**：支持多文件并发转写，提高处理效率
- 🔄 **实时推送**：WebSocket 实时推送处理进度和状态
- 🌐 **现代化界面**：基于 FastAPI 的响应式 Web 界面
- 📊 **历史记录**：自动保存转写历史，支持查询和管理

## ✨ 核心功能

### 1. 声纹分离 (Speaker Diarization)
- 自动检测音频中的说话人数量
- 识别每个说话人的发言时间段
- 支持 1-10 人的多说话人场景

### 2. 语音识别 (ASR)
- 基于 ModelScope FunASR 框架
- 支持中文、英文、中英混合、方言等多语言
- 可自定义热词，提升专业术语识别准确率
- 配合 VAD（语音端点检测）和 PUNC（标点恢复）模块

### 3. 会议纪要生成
- 集成 DeepSeek/OpenAI API
- 自动生成结构化会议纪要
- 包含会议主题、参与人员、讨论内容、行动清单等

### 4. 文件管理
- 支持多种音频格式（mp3, wav, m4a, flac, aac, ogg, wma 等）
- 文件上传、删除、下载功能
- 转写历史记录持久化存储
- 支持重新转写和追加生成纪要
- 支持停止转写任务（真正中断转写进程）
- 支持批量清空Dify生成文件
- 支持一键清空所有历史记录

## 🏗️ 系统架构

项目采用 **DDD（领域驱动设计）三层架构**：

```
voice/
├── domain/              # 领域层：核心业务逻辑
│   └── voice/
│       ├── audio_processor.py      # 音频处理逻辑
│       ├── text_processor.py       # 文本处理逻辑
│       ├── diarization.py          # 声纹分离逻辑
│       └── transcriber.py          # 转写协调器
│
├── application/         # 应用层：业务流程编排
│   └── voice/
│       ├── pipeline_service.py     # 转写流水线服务
│       └── actions.py              # 业务动作定义
│
├── infra/              # 基础设施层：技术实现
│   ├── audio_io/       # 音频存储管理
│   │   └── storage.py
│   ├── runners/        # 模型运行器
│   │   ├── asr_runner.py           # ASR 模型运行器
│   │   └── diarization_runner.py   # 声纹分离运行器
│   └── websocket/      # WebSocket 连接管理
│       └── connection_manager.py
│
├── api/                # API 层：对外接口
│   └── routers/
│       └── voice_gateway.py        # 语音服务网关
│
├── templates/          # 前端模板
│   ├── index.html      # 主页面
│   └── result.html     # 结果页面
│
├── static/             # 静态资源
├── uploads/            # 文件上传目录
├── transcripts/        # 转写结果目录
├── audio_temp/         # 临时音频文件
│
├── main.py             # 应用入口
└── config.py           # 配置文件
```

### 架构设计原则

- **Domain（领域层）**：包含核心业务逻辑，不依赖外部框架
- **Application（应用层）**：编排业务流程，协调领域对象
- **Infrastructure（基础设施层）**：提供技术支持（数据库、文件系统、第三方服务等）
- **API（接口层）**：处理 HTTP 请求，调用应用层服务

## 🚀 快速开始

### 系统要求

- **Python**: 3.8 或更高版本
- **FFmpeg**: 用于音频格式转换
- **内存**: 建议 4GB 以上
- **GPU**: 可选，支持 CUDA 加速

### 安装步骤

#### 1. 安装 FFmpeg

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install ffmpeg -y

# macOS
brew install ffmpeg

# Windows
# 下载并安装：https://ffmpeg.org/download.html
```

#### 2. 安装 Python 依赖

```bash
# 安装依赖包
pip install -r requirements.txt

# 如果使用国内镜像（推荐）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

#### 3. 配置环境变量（可选）

```bash
# 配置 DeepSeek API（用于生成会议纪要）
export DEEPSEEK_API_KEY="your-api-key"
export DEEPSEEK_API_BASE="https://api.deepseek.com"
export DEEPSEEK_MODEL="deepseek-chat"

# 或者使用 OpenAI API
export OPENAI_API_KEY="your-api-key"
export OPENAI_API_BASE="https://api.openai.com/v1"
export OPENAI_MODEL="gpt-3.5-turbo"

# 预加载模型（可选，首次启动会自动下载）
export PRELOAD_MODELS="true"

# 设置转写线程数（默认5）
export TRANSCRIBE_WORKERS="5"
```

#### 4. 启动服务

```bash
# 方式1：使用主程序启动
python main.py

# 方式2：使用 uvicorn 启动（开发模式）
uvicorn main:app --host 0.0.0.0 --port 8998 --reload

# 方式3：后台运行
nohup python main.py > app.log 2>&1 &
```

### 访问服务

启动成功后，访问以下地址：

- 🌐 **主页面**: http://localhost:8998
- 📚 **API 文档**: http://localhost:8998/docs
- 📖 **ReDoc 文档**: http://localhost:8998/redoc
- 💚 **健康检查**: http://localhost:8998/healthz

## 📡 API 接口

### 一站式转写接口

#### POST `/api/voice/transcribe_all`

**功能**: 上传音频 + 转写 + 生成纪要，一次完成

**参数**:
```json
{
  "audio_files": "文件对象（支持单个或多个）",
  "language": "zh | en | zh-en | zh-dialect",
  "hotword": "热词（空格分隔）",
  "generate_summary": "true | false（是否生成会议纪要）",
  "return_type": "json | file | both"
}
```

**return_type 说明**:
- `json`: 返回 JSON 格式的转写结果和下载链接
- `file`: 直接返回 Word 文档（单文件）或 ZIP 压缩包（多文件）
- `both`: 返回 JSON 格式，并在响应中包含文件的 base64 编码

**示例**:
```bash
# 上传单个文件，返回 JSON
curl -X POST "http://localhost:8998/api/voice/transcribe_all" \
  -F "audio_files=@meeting.mp3" \
  -F "language=zh" \
  -F "generate_summary=true" \
  -F "return_type=json"

# 上传多个文件，直接下载 ZIP
curl -X POST "http://localhost:8998/api/voice/transcribe_all" \
  -F "audio_files=@file1.mp3" \
  -F "audio_files=@file2.mp3" \
  -F "return_type=file" \
  -o transcripts.zip
```

### RESTful 文件资源接口

#### GET `/api/voice/files`

**功能**: 列出所有文件，支持过滤、排序、分页和统计。返回的文件对象包含可访问的下载URL。

**查询参数**:
- `status`: 过滤状态（`uploaded`/`processing`/`completed`/`error`）
- `limit`: 返回数量限制（分页大小）
- `offset`: 分页偏移量（默认 `0`）
- `include_history`: 是否包含历史记录（默认 `false`，从磁盘加载已完成的文件）

**排序规则**:
- 按状态优先级排序：`processing` > `uploaded` > `completed` > `error`
- 相同状态按 `upload_time` 降序排列（最新的在前）

**响应字段**:
- `files[]`: 文件列表，每个文件包含：
  - `id`: 文件唯一标识
  - `filename`: 存储文件名
  - `original_name`: 原始文件名
  - `filepath`: 服务器本地路径（**前端不可直接访问**）
  - `download_urls`: **可访问的下载链接**（重要！）
    - `audio`: 音频文件下载URL（**推荐使用此字段访问音频**）
    - `transcript`: 转写文档下载URL（如果存在）
    - `summary`: 会议纪要下载URL（如果存在）
  - `status`: 文件状态
  - `progress`: 处理进度（0-100）
  - 其他字段...

**重要说明**:
- ⚠️ **不要使用 `filepath` 字段**：这是服务器本地路径，前端无法直接访问
- ✅ **使用 `download_urls.audio`**：这是HTTP可访问的API路径

**示例**:
```bash
# 获取所有文件
curl "http://localhost:8998/api/voice/files"

# 获取所有已完成的文件
curl "http://localhost:8998/api/voice/files?status=completed&limit=10"

# 获取所有处理中的文件
curl "http://localhost:8998/api/voice/files?status=processing"

# 获取包含历史记录的所有文件
curl "http://localhost:8998/api/voice/files?include_history=true"

# 分页查询（第2页，每页20条）
curl "http://localhost:8998/api/voice/files?limit=20&offset=20"
```

#### GET `/api/voice/files/{file_id}`

**功能**: 获取文件详情

**查询参数**:
- `include_transcript`: 是否包含转写结果（默认 false）
- `include_summary`: 是否包含会议纪要（默认 false）

**示例**:
```bash
# 获取文件详情和转写结果
curl "http://localhost:8998/api/voice/files/{file_id}?include_transcript=true&include_summary=true"
```

#### PATCH `/api/voice/files/{file_id}`

**功能**: 更新文件（重新转写、生成纪要）

**请求体**:
```json
{
  "action": "retranscribe | generate_summary",
  "language": "zh",
  "hotword": "自定义热词"
}
```

**示例**:
```bash
# 重新转写
curl -X PATCH "http://localhost:8998/api/voice/files/{file_id}" \
  -H "Content-Type: application/json" \
  -d '{"action": "retranscribe", "language": "zh"}'

# 生成会议纪要
curl -X PATCH "http://localhost:8998/api/voice/files/{file_id}" \
  -H "Content-Type: application/json" \
  -d '{"action": "generate_summary"}'
```

#### DELETE `/api/voice/files/{file_id}`

**功能**: 删除文件和相关数据

**特殊操作**:
- `file_id = "_clear_dify"`: 清空Dify生成文件（删除所有 `transcripts_*.zip` 文件及其对应的音频文件）
- `file_id = "_clear_all"`: 清空所有历史记录（删除所有转写文件、音频文件和历史记录）

**示例**:
```bash
# 删除单个文件
curl -X DELETE "http://localhost:8998/api/voice/files/{file_id}"

# 清空Dify生成文件
curl -X DELETE "http://localhost:8998/api/voice/files/_clear_dify"

# 清空所有历史记录
curl -X DELETE "http://localhost:8998/api/voice/files/_clear_all"
```

**响应示例（清空操作）**:
```json
{
  "success": true,
  "message": "清空dify生成文件成功",
  "deleted": {
    "zip_files": 3,
    "audio_files": 3,
    "transcript_files": 3,
    "records": 3
  }
}
```

**注意事项**:
- 已停止转写的文件（`_cancelled = True`）可以正常删除
- 正在转写中的文件（`status = 'processing'` 且未取消）无法删除

### 向后兼容接口

为保持向后兼容，系统保留了以下传统接口：

| 方法 | 端点 | 功能 | 推荐新接口 |
|------|------|------|-----------|
| POST | `/api/voice/upload` | 上传音频文件 | `/api/voice/transcribe_all` |
| POST | `/api/voice/transcribe` | 开始转写 | `/api/voice/transcribe_all` |
| GET | `/api/voice/status/{file_id}` | 获取转写状态 | `/api/voice/files/{file_id}` |
| GET | `/api/voice/result/{file_id}` | 获取转写结果 | `/api/voice/files/{file_id}?include_transcript=true` |
| POST | `/api/voice/stop/{file_id}` | 停止转写 | - |
| GET | `/api/voice/history` | 获取历史记录 | `/api/voice/files?status=completed` |
| POST | `/api/voice/generate_summary/{file_id}` | 生成会议纪要 | `PATCH /api/voice/files/{file_id}` |

### 下载接口

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/api/voice/audio/{file_id}?download=1` | 下载音频文件 |
| GET | `/api/voice/download_transcript/{file_id}` | 下载转写文档 |
| GET | `/api/voice/download_summary/{file_id}` | 下载会议纪要 |
| GET | `/api/voice/download_file/{filename}` | 下载输出文件 |

### WebSocket 接口

#### WS `/api/voice/ws`

**功能**: 实时接收文件处理状态更新

**消息格式**:
```json
{
  "type": "file_status",
  "file_id": "文件ID",
  "status": "processing | completed | error",
  "progress": 50,
  "message": "正在转写..."
}
```

**客户端示例**:
```javascript
const ws = new WebSocket('ws://localhost:8998/api/voice/ws');

ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    console.log('进度更新:', data);
    
    if (data.type === 'file_status') {
        console.log(`文件 ${data.file_id}: ${data.status} (${data.progress}%)`);
    }
};

// 订阅特定文件的状态更新
ws.send(JSON.stringify({
    type: 'subscribe',
    file_id: 'your-file-id'
}));
```

## 📖 使用指南

### Web 界面使用

1. 打开浏览器访问 http://localhost:8998
2. 拖拽或选择音频文件上传（支持多文件）
3. 选择语言类型（中文/英文/中英混合/方言）
4. 可选：输入热词（空格分隔），如 "人工智能 深度学习"
5. 点击"开始转写"按钮
6. 实时查看转写进度
7. 转写完成后：
   - 查看转写结果
   - 下载 Word 文档
   - 生成会议纪要（可选）

### 命令行/API 使用

#### 场景1：快速转写单个文件

```bash
curl -X POST "http://localhost:8998/api/voice/transcribe_all" \
  -F "audio_files=@meeting.mp3" \
  -F "language=zh" \
  -F "return_type=json"
```

#### 场景2：批量转写多个文件

```bash
curl -X POST "http://localhost:8998/api/voice/transcribe_all" \
  -F "audio_files=@file1.mp3" \
  -F "audio_files=@file2.mp3" \
  -F "audio_files=@file3.mp3" \
  -F "return_type=file" \
  -o transcripts.zip
```

#### 场景3：转写并生成会议纪要

```bash
curl -X POST "http://localhost:8998/api/voice/transcribe_all" \
  -F "audio_files=@meeting.mp3" \
  -F "language=zh" \
  -F "generate_summary=true" \
  -F "hotword=季度报告 销售业绩 市场策略" \
  -F "return_type=both"
```

#### 场景4：分步处理（上传 → 转写 → 查询）

```bash
# 1. 上传文件
RESULT=$(curl -X POST "http://localhost:8998/api/voice/upload" \
  -F "audio_file=@meeting.mp3")
FILE_ID=$(echo $RESULT | jq -r '.file.id')

# 2. 开始转写
curl -X POST "http://localhost:8998/api/voice/transcribe" \
  -H "Content-Type: application/json" \
  -d "{\"file_id\": \"$FILE_ID\", \"language\": \"zh\"}"

# 3. 查询状态
curl "http://localhost:8998/api/voice/status/$FILE_ID"

# 4. 获取结果
curl "http://localhost:8998/api/voice/result/$FILE_ID"

# 5. 下载文档
curl "http://localhost:8998/api/voice/download_transcript/$FILE_ID" \
  -o transcript.docx
```

### Python SDK 示例

```python
import requests

# 一站式转写
def transcribe_audio(audio_path, language='zh', generate_summary=False):
    url = 'http://localhost:8998/api/voice/transcribe_all'
    
    files = {'audio_files': open(audio_path, 'rb')}
    data = {
        'language': language,
        'generate_summary': generate_summary,
        'return_type': 'json'
    }
    
    response = requests.post(url, files=files, data=data)
    return response.json()

# 使用
result = transcribe_audio('meeting.mp3', generate_summary=True)
print(f"转写完成: {result['message']}")
print(f"说话人数: {result['results'][0]['statistics']['speakers_count']}")
```

## ⚙️ 配置说明

### config.py 配置文件

#### 文件路径配置

```python
FILE_CONFIG = {
    "output_dir": "transcripts",  # 转写结果保存目录
    "temp_dir": "audio_temp",     # 临时文件目录
    "upload_dir": "uploads"       # 上传文件目录
}
```

#### 模型配置

```python
MODEL_CONFIG = {
    # 声纹分离模型
    "diarization": {
        "model_id": 'iic/speech_campplus_speaker-diarization_common',
        "revision": 'master'
    },
    
    # ASR 模型（语音转文字）
    "asr": {
        "model_id": 'iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch',
        "model_revision": 'v2.0.4'
    },
    
    # VAD 模型（语音端点检测）
    "vad": {
        "model_id": 'iic/speech_fsmn_vad_zh-cn-16k-common-pytorch',
        "model_revision": 'v2.0.4'
    },
    
    # PUNC 模型（标点恢复）
    "punc": {
        "model_id": 'iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch',
        "model_revision": 'v2.0.4'
    },
    
    # 热词配置（可选）
    "hotword": ''  # 示例：'人工智能 深度学习 神经网络'
}
```

#### 语言配置

```python
LANGUAGE_CONFIG = {
    "zh": {
        "name": "中文普通话",
        "description": "适用于标准普通话音频"
    },
    "zh-dialect": {
        "name": "方言混合",
        "description": "适用于包含方言的音频"
    },
    "zh-en": {
        "name": "中英混合",
        "description": "适用于中英文混合的音频"
    },
    "en": {
        "name": "英文",
        "description": "适用于纯英文音频"
    }
}
```

#### 音频处理配置

```python
AUDIO_PROCESS_CONFIG = {
    "sample_rate": 16000,  # 采样率
    "channels": 1          # 声道数
}
```

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | - |
| `DEEPSEEK_API_BASE` | DeepSeek API 地址 | https://api.deepseek.com |
| `DEEPSEEK_MODEL` | DeepSeek 模型名称 | deepseek-chat |
| `OPENAI_API_KEY` | OpenAI API 密钥 | - |
| `OPENAI_API_BASE` | OpenAI API 地址 | https://api.openai.com/v1 |
| `OPENAI_MODEL` | OpenAI 模型名称 | gpt-3.5-turbo |
| `PRELOAD_MODELS` | 启动时预加载模型 | false |
| `TRANSCRIBE_WORKERS` | 转写线程数 | 5 |

## 🛠️ 技术栈

### 后端框架
- **FastAPI** 0.109.0 - 现代化、高性能 Web 框架
- **Uvicorn** - ASGI 服务器
- **Python 3.8+** - 编程语言

### AI 模型
- **ModelScope** 1.11.0 - 阿里达摩院开源模型平台
- **FunASR** 1.0.0 - 阿里巴巴达摩院语音识别工具
- **SeACo-Paraformer** - 大规模语音识别模型（支持热词）
- **CAM++** - 声纹分离模型
- **FSMN-VAD** - 语音端点检测模型
- **CT-Transformer** - 标点恢复模型

### 音频处理
- **FFmpeg** - 音频格式转换
- **soundfile** 0.12.1 - 音频文件读写
- **pydub** - 音频切片和处理
- **PyTorch** 2.0+ - 深度学习框架

### 文档生成
- **python-docx** 1.1.0 - Word 文档生成

### 其他工具
- **jieba** 0.42.1 - 中文分词（热词处理）
- **OpenAI SDK** - AI 模型 API 调用
- **WebSockets** 12.0 - 实时通信
- **slowapi** 0.1.9 - API 速率限制

## 🔍 故障排除

### 常见问题

#### 1. FFmpeg 未找到

```bash
# 检查 FFmpeg 是否安装
which ffmpeg
ffmpeg -version

# Ubuntu/Debian 安装
sudo apt install ffmpeg

# macOS 安装
brew install ffmpeg
```

#### 2. 模型下载失败

首次运行时会自动从 ModelScope 下载模型（约 1-2GB），需要良好的网络连接。

如果下载失败：
- 检查网络连接
- 尝试使用代理
- 手动下载模型到 `~/.cache/modelscope/hub/` 目录

#### 3. 内存不足

```bash
# 减少并发转写线程数
export TRANSCRIBE_WORKERS="2"

# 或者增加系统交换空间
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

#### 4. 转写结果为空

检查：
- 音频文件格式是否正确
- 音频是否包含有效语音内容
- 音频质量是否过低
- 查看日志文件 `app.log` 获取详细错误信息

#### 5. 会议纪要生成失败

需要配置 API 密钥：
```bash
export DEEPSEEK_API_KEY="your-api-key"
# 或
export OPENAI_API_KEY="your-api-key"
```

如果未配置 API 密钥，系统会生成默认的统计型纪要。

## 📝 更新日志

### v3.1.1-FunASR (2025-11-13)

**功能增强与修复**

#### 新增功能
- ✅ **真正的停止转写功能**：支持中断正在进行的转写任务，通过 `_cancelled` 标志和 `InterruptedError` 机制实现
- ✅ **清空Dify生成文件**：新增 `DELETE /api/voice/files/_clear_dify` 接口，可精确删除Dify一站式转写生成的.zip文件及其对应的音频文件
- ✅ **清空所有历史记录**：新增 `DELETE /api/voice/files/_clear_all` 接口，可一键清空所有转写历史记录

#### 功能修复
- ✅ **文件名唯一性修复**：修复了批量转写时文件名冲突问题，使用微秒级时间戳和 `file_id` 确保每个文件生成唯一的转写文档文件名
- ✅ **删除已停止转写文件**：修复了停止转写后无法删除文件的问题，现在可以正常删除已停止的文件
- ✅ **WebSocket进度跳转修复**：修复了转写进度反复跳转的问题，优化了进度更新逻辑，确保进度只增不减
- ✅ **删除后UI立即更新**：修复了删除文件后前端界面不立即更新的问题，现在删除后立即从列表中移除并更新UI
- ✅ **删除错误提示修复**：修复了删除已停止转写文件时出现"删除失败"错误提示的问题，改进了错误处理逻辑

#### 技术改进
- ✅ 改进了转写任务的取消机制，使用 `cancellation_flag` 在转写流程的关键步骤检查取消状态
- ✅ 优化了WebSocket消息处理，防止进度回退和状态不一致
- ✅ 改进了文件删除的错误处理，正确解析FastAPI的HTTPException响应格式

### v3.1.0-FunASR (2025-11-06)

**版本标识**：FunASR一体化模式

#### 技术升级
- ✅ 统一版本号为 3.1.0-FunASR，标识FunASR一体化架构
- ✅ 系统状态接口返回版本信息统一

### v3.0.0 (2025-11-02)

**重大更新**：完整的架构重构

#### 架构变更
- ✅ 采用 DDD（领域驱动设计）三层架构
- ✅ 分离 Domain、Application、Infra 层
- ✅ 提高代码可维护性和扩展性

#### 新增功能
- ✅ 一站式转写接口 `/api/voice/transcribe_all`
- ✅ RESTful 风格文件资源接口
- ✅ 支持批量文件处理
- ✅ 支持三种返回模式（json/file/both）
- ✅ WebSocket 实时状态推送
- ✅ 历史记录持久化存储
- ✅ AI 会议纪要生成（集成 DeepSeek/OpenAI）
- ✅ 文件管理功能（重新转写、删除等）

#### 优化改进
- ✅ 优化音频处理流程
- ✅ 改进声纹分离准确率
- ✅ 增强热词功能
- ✅ 提升并发处理能力
- ✅ 完善错误处理和日志记录

#### 接口变更
- ⚠️ 移除 `/dify/transcribe` 接口
- ⚠️ 移除 `/v1/audio/transcriptions` 接口
- ✅ 保留向后兼容接口

## 📄 许可证

本项目使用的模型来自 [ModelScope](https://modelscope.cn/)，请遵守相关模型的使用协议。

## 🔗 相关链接

- [ModelScope 模型平台](https://modelscope.cn/)
- [FunASR 项目](https://github.com/alibaba-damo-academy/FunASR)
- [FastAPI 文档](https://fastapi.tiangolo.com/)
- [DeepSeek API](https://platform.deepseek.com/)

## 💬 支持与反馈

如有问题或建议，欢迎：
- 提交 Issue
- 发送反馈邮件
- 查看 API 文档：http://localhost:8998/docs

---

**⭐ 如果这个项目对你有帮助，欢迎 Star！**
