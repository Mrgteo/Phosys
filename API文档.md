# 音频转写系统 API 接口文档

> 版本: 3.1.3-FunASR  
> 更新时间: 2025-12-04  
> 基础URL: `http://localhost:8998`

---

## 目录

- [概述](#概述)
- [认证](#认证)
- [速率限制](#速率限制)
- [响应格式](#响应格式)
- [错误处理](#错误处理)
- [核心接口](#核心接口)
  - [RESTful文件资源接口](#restful文件资源接口)
  - [向后兼容接口](#向后兼容接口)
  - [下载接口](#下载接口)
  - [WebSocket接口](#websocket接口)
  - [辅助接口](#辅助接口)
- [数据模型](#数据模型)
- [使用示例](#使用示例)

---

## 概述

音频转写系统提供了一套完整的RESTful API，支持音频文件上传、语音识别、声纹分离、会议纪要生成等功能。系统采用领域驱动设计（DDD）架构，具有高性能和可扩展性。

### 核心功能

- 🎯 **多说话人识别**：自动识别并区分不同说话人
- 📝 **高精度ASR**：支持中文、英文、方言等多语言识别
- 🔤 **智能标点恢复**：自动添加标点符号
- 📄 **文档自动生成**：支持导出Word格式文档
- 🤖 **AI会议纪要**：集成DeepSeek/OpenAI生成结构化纪要
- ⚡ **批量处理**：支持多文件并发转写
- 🔄 **实时推送**：WebSocket实时推送处理进度
- 🎯 **词级别时间戳**：支持返回逐词时间戳，实现精确的音字同步
- ✨ **音字同步高亮**：播放音频时自动高亮对应的转写文字
- 📈 **平滑进度显示**：智能进度追踪器平滑推进，避免进度条跳跃

### 支持的音频格式

`mp3`, `wav`, `m4a`, `flac`, `aac`, `ogg`, `wma`

### 支持的语言类型

| 语言代码 | 语言名称 | 说明 |
|---------|---------|------|
| `zh` | 中文普通话 | 适用于标准普通话音频 |
| `zh-dialect` | 方言混合 | 适用于包含方言的音频 |
| `zh-en` | 中英混合 | 适用于中英文混合的音频 |
| `en` | 英文 | 适用于纯英文音频 |

---

## 认证

当前版本暂不需要认证。未来版本可能会引入API Key认证机制。

---

## 速率限制

- 默认限制：**200请求/小时/IP**
- 超出限制时，将返回 `429 Too Many Requests` 错误

---

## 响应格式

所有API响应均使用JSON格式，包含以下标准字段：

### 成功响应

```json
{
  "success": true,
  "message": "操作成功",
  "data": { ... }
}
```

### 失败响应

```json
{
  "success": false,
  "message": "错误描述",
  "error": "详细错误信息"
}
```

---

## 错误处理

### HTTP状态码

| 状态码 | 说明 |
|-------|------|
| 200 | 请求成功 |
| 400 | 请求参数错误 |
| 404 | 资源不存在 |
| 422 | 请求验证失败 |
| 429 | 超出速率限制 |
| 500 | 服务器内部错误 |

### 常见错误

| 错误信息 | 说明 | 解决方法 |
|---------|------|---------|
| `没有选择文件` | 未提供音频文件 | 确保在请求中包含音频文件 |
| `不支持的文件格式` | 文件格式不支持 | 使用支持的音频格式 |
| `文件不存在` | 文件ID无效 | 检查文件ID是否正确 |
| `文件正在处理中` | 文件正在转写 | 等待当前转写完成 |
| `文件转写未完成` | 转写未完成 | 等待转写完成后再请求结果 |

---

## 核心接口

### RESTful文件资源接口

### RESTful文件资源接口

#### GET `/api/voice/files`

**功能**：列出所有文件，支持过滤、排序、分页和统计。返回的文件对象包含可访问的下载URL。

**请求方式**：`GET`

**查询参数**：

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|-------|------|-----|-------|------|
| `status` | string | 否 | - | 过滤状态：`uploaded`/`processing`/`completed`/`error` |
| `limit` | integer | 否 | - | 返回数量限制（分页大小） |
| `offset` | integer | 否 | `0` | 分页偏移量（跳过多少条） |
| `include_history` | boolean | 否 | `false` | 是否包含历史记录（从磁盘加载已完成的文件） |

**排序规则**：
- 按状态优先级排序：`processing` > `uploaded` > `completed` > `error`
- 相同状态按 `upload_time` 降序排列（最新的在前）

**响应示例**：

```json
{
  "success": true,
  "files": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "filename": "meeting_20251102_143000.mp3",
      "original_name": "meeting.mp3",
      "filepath": "/home/user/phosys/uploads/meeting_20251102_143000.mp3",
      "size": 5242880,
      "status": "completed",
      "progress": 100,
      "language": "zh",
      "upload_time": "2025-11-02 14:30:00",
      "complete_time": "2025-11-02 14:35:00",
      "error_message": "",
      "download_urls": {
        "audio": "/api/voice/audio/a1b2c3d4-e5f6-7890-abcd-ef1234567890?download=1",
        "transcript": "/api/voice/download_transcript/a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "summary": "/api/voice/download_summary/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
      }
    }
  ],
  "pagination": {
    "total": 10,
    "limit": 10,
    "offset": 0,
    "returned": 3
  },
  "statistics": {
    "uploaded": 2,
    "processing": 1,
    "completed": 7,
    "error": 0
  }
}
```

**响应字段说明**：

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `success` | boolean | 请求是否成功 |
| `files` | array | 文件列表（已过滤、排序、分页） |
| `files[].id` | string | 文件唯一标识（UUID） |
| `files[].filename` | string | 存储文件名（带时间戳） |
| `files[].original_name` | string | 原始上传文件名 |
| `files[].filepath` | string | 服务器本地文件路径（**前端不可直接访问**） |
| `files[].size` | integer | 文件大小（字节） |
| `files[].status` | string | 文件状态：`uploaded`/`processing`/`completed`/`error` |
| `files[].progress` | integer | 处理进度（0-100） |
| `files[].language` | string | 语言类型（如 `zh`、`en`） |
| `files[].upload_time` | string | 上传时间 |
| `files[].complete_time` | string | 完成时间（可选） |
| `files[].error_message` | string | 错误信息（如果有） |
| `files[].download_urls` | object | **可访问的下载链接**（重要！） |
| `files[].download_urls.audio` | string | 音频文件下载URL（**推荐使用此字段访问音频**） |
| `files[].download_urls.transcript` | string | 转写文档下载URL（如果存在） |
| `files[].download_urls.summary` | string | 会议纪要下载URL（如果存在） |
| `pagination` | object | 分页信息 |
| `pagination.total` | integer | 过滤后的总文件数 |
| `pagination.limit` | integer | 分页大小 |
| `pagination.offset` | integer | 分页偏移量 |
| `pagination.returned` | integer | 实际返回的文件数 |
| `statistics` | object | 统计信息（基于全部文件，不受过滤影响） |
| `statistics.uploaded` | integer | 已上传状态的文件数 |
| `statistics.processing` | integer | 处理中状态的文件数 |
| `statistics.completed` | integer | 已完成状态的文件数 |
| `statistics.error` | integer | 错误状态的文件数 |

**重要说明**：

1. **下载URL使用**：
   - ⚠️ **不要使用 `filepath` 字段**：这是服务器本地路径，前端无法直接访问
   - ✅ **使用 `download_urls.audio`**：这是HTTP可访问的API路径
   - `download_urls.transcript` 和 `download_urls.summary` 仅在文件存在对应资源时出现

2. **历史记录**：
   - 默认只返回内存中的文件（当前会话）
   - `include_history=true` 时会从磁盘加载历史记录，可能影响性能

3. **统计信息**：
   - `statistics` 基于全部文件统计，不受 `status` 过滤参数影响
   - 用于显示整体状态概览

**cURL示例**：

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

# 组合查询：获取已完成的文件，包含历史记录，分页
curl "http://localhost:8998/api/voice/files?status=completed&include_history=true&limit=10&offset=0"
```

**使用示例（JavaScript）**：

```javascript
// 获取所有处理中的文件
const response = await fetch('/api/voice/files?status=processing');
const data = await response.json();

if (data.success) {
  data.files.forEach(file => {
    console.log(`文件: ${file.original_name}`);
    console.log(`状态: ${file.status}`);
    console.log(`进度: ${file.progress}%`);
    // 使用 download_urls.audio 访问音频文件
    console.log(`音频URL: ${file.download_urls.audio}`);
  });
  
  // 显示统计信息
  console.log('统计:', data.statistics);
}

// 分页加载
async function loadFilesPage(page = 1, pageSize = 20) {
  const offset = (page - 1) * pageSize;
  const response = await fetch(
    `/api/voice/files?limit=${pageSize}&offset=${offset}`
  );
  const data = await response.json();
  return data;
}
```

---

#### GET `/api/voice/files/{file_id}`

**功能**：获取指定文件的详细信息。

**请求方式**：`GET`

**路径参数**：

| 参数名 | 类型 | 必填 | 说明 |
|-------|------|-----|------|
| `file_id` | string | 是 | 文件唯一标识 |

**查询参数**：

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|-------|------|-----|-------|------|
| `include_transcript` | boolean | 否 | `false` | 是否包含转写结果 |
| `include_summary` | boolean | 否 | `false` | 是否包含会议纪要 |

**响应示例**：

```json
{
  "success": true,
  "file": {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "filename": "meeting.mp3",
    "size": 5242880,
    "status": "completed",
    "progress": 100,
    "language": "zh",
    "upload_time": "2025-11-02 14:30:00",
    "complete_time": "2025-11-02 14:35:00",
    "error_message": "",
    "download_urls": {
      "audio": "/api/voice/audio/a1b2c3d4-e5f6-7890-abcd-ef1234567890?download=1",
      "transcript": "/api/voice/download_transcript/a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "summary": "/api/voice/download_summary/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    }
  },
  "transcript": [
    {
      "speaker": "说话人1",
      "text": "会议内容...",
      "start_time": 0.5,
      "end_time": 3.2,
      "words": [
        {
          "text": "会议",
          "start": 0.5,
          "end": 0.8
        },
        {
          "text": "内容",
          "start": 0.8,
          "end": 1.1
        }
      ]
    }
  ],
  "statistics": {
    "speakers_count": 2,
    "segments_count": 25,
    "total_characters": 1250,
    "speakers": ["说话人1", "说话人2"]
  },
  "summary": {
    "raw_text": "## 会议纪要...",
    "generated_at": "2025-11-02 14:35:00",
    "model": "deepseek-chat",
    "status": "success"
  }
}
```

**cURL示例**：

```bash
# 获取文件基本信息
curl "http://localhost:8998/api/voice/files/a1b2c3d4-e5f6-7890-abcd-ef1234567890"

# 获取文件详情和转写结果
curl "http://localhost:8998/api/voice/files/a1b2c3d4-e5f6-7890-abcd-ef1234567890?include_transcript=true&include_summary=true"
```

---

#### PATCH `/api/voice/files/{file_id}`

**功能**：更新文件（重新转写、生成纪要）。

**请求方式**：`PATCH`

**路径参数**：

| 参数名 | 类型 | 必填 | 说明 |
|-------|------|-----|------|
| `file_id` | string | 是 | 文件唯一标识 |

**请求体**：

| 参数名 | 类型 | 必填 | 说明 |
|-------|------|-----|------|
| `action` | string | 是 | 操作类型：retranscribe/generate_summary |
| `language` | string | 否 | 语言类型（重新转写时） |
| `hotword` | string | 否 | 热词（重新转写时） |

**响应示例 (重新转写)**：

```json
{
  "success": true,
  "message": "已开始重新转写",
  "file_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "processing"
}
```

**响应示例 (生成纪要)**：

```json
{
  "success": true,
  "message": "会议纪要生成成功",
  "summary": {
    "raw_text": "## 会议纪要\n\n会议主题：...",
    "generated_at": "2025-11-02 14:40:00",
    "model": "deepseek-chat",
    "status": "success"
  }
}
```

**cURL示例**：

```bash
# 重新转写
curl -X PATCH "http://localhost:8998/api/voice/files/a1b2c3d4-e5f6-7890-abcd-ef1234567890" \
  -H "Content-Type: application/json" \
  -d '{"action": "retranscribe", "language": "zh", "hotword": "人工智能 深度学习"}'

# 生成会议纪要
curl -X PATCH "http://localhost:8998/api/voice/files/a1b2c3d4-e5f6-7890-abcd-ef1234567890" \
  -H "Content-Type: application/json" \
  -d '{"action": "generate_summary"}'
```

---

#### DELETE `/api/voice/files/{file_id}`

**功能**：删除文件及相关数据。

**请求方式**：`DELETE`

**路径参数**：

| 参数名 | 类型 | 必填 | 说明 |
|-------|------|-----|------|
| `file_id` | string | 是 | 文件唯一标识，支持特殊值：`_clear_all`（清空所有历史记录） |

**特殊操作**：

1. **清空所有历史记录** (`file_id = "_clear_all"`)：
   - 删除所有音频文件
   - 删除所有转写文档和会议纪要
   - 清空输出目录（保留 `history_records.json` 文件结构）
   - 清空历史记录文件

**响应示例（正常删除）**：

```json
{
  "success": true,
  "message": "文件删除成功"
}
```

**响应示例（清空所有历史记录）**：

```json
{
  "success": true,
  "message": "清空所有历史记录成功",
  "deleted": {
    "audio_files": 10,
    "transcript_files": 10,
    "records": 10
  }
}
```

**cURL示例**：

```bash
# 删除单个文件
curl -X DELETE "http://localhost:8998/api/voice/files/a1b2c3d4-e5f6-7890-abcd-ef1234567890"

# 清空所有历史记录
curl -X DELETE "http://localhost:8998/api/voice/files/_clear_all"
```

**注意事项**：
- 已停止转写的文件（`_cancelled = True`）可以正常删除
- 正在转写中的文件（`status = 'processing'` 且未取消）无法删除
- 清空操作会级联删除所有相关文件，请谨慎使用

---

### 向后兼容接口

以下接口为向后兼容保留，推荐使用新的RESTful接口。

#### POST `/api/voice/upload`

**功能**：上传音频文件（支持单个或多个文件，不执行转写）。

**请求方式**：`POST` (multipart/form-data)

**请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|-------|------|-----|------|
| `audio_file` | File | 是 | 音频文件（单个或多个同名字段） |

**使用方式**：
- **单个文件**：form-data 中一个 `audio_file` 字段
- **多个文件**：form-data 中多个 `audio_file` 字段（或使用 `audio_file[]`）

**响应示例（单个文件）**：

```json
{
  "success": true,
  "message": "文件上传成功",
  "files": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "filename": "meeting_20251102_143000.mp3",
      "original_name": "meeting.mp3",
      "filepath": "/home/user/phosys/uploads/meeting_20251102_143000.mp3",
      "size": 5242880,
      "upload_time": "2025-11-02 14:30:00",
      "status": "uploaded",
      "progress": 0
    }
  ],
  "file_ids": ["a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
  "file": {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "filename": "meeting_20251102_143000.mp3",
    "original_name": "meeting.mp3",
    "filepath": "/home/user/phosys/uploads/meeting_20251102_143000.mp3",
    "size": 5242880,
    "upload_time": "2025-11-02 14:30:00",
    "status": "uploaded",
    "progress": 0
  },
  "file_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**注意**：单个文件时，返回格式同时包含：
- `files` 数组（长度为1）：统一格式，方便模板转换节点使用
- `file_ids` 数组（长度为1）：方便批量转写
- `file` 对象：向后兼容字段
- `file_id` 字符串：向后兼容字段

**响应示例（多个文件）**：

```json
{
  "success": true,
  "message": "成功上传 3 个文件",
  "files": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "filename": "meeting1_20251102_143000.mp3",
      "original_name": "meeting1.mp3",
      "filepath": "/home/user/phosys/uploads/meeting1_20251102_143000.mp3",
      "size": 5242880,
      "upload_time": "2025-11-02 14:30:00",
      "status": "uploaded",
      "progress": 0
    },
    {
      "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "filename": "meeting2_20251102_143001.mp3",
      "original_name": "meeting2.mp3",
      "filepath": "/home/user/phosys/uploads/meeting2_20251102_143001.mp3",
      "size": 3145728,
      "upload_time": "2025-11-02 14:30:01",
      "status": "uploaded",
      "progress": 0
    }
  ],
  "file_ids": [
    "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "b2c3d4e5-f6a7-8901-bcde-f12345678901"
  ],
  "failed_files": null
}
```

**cURL示例**：

```bash
# 单个文件上传
curl -X POST "http://localhost:8998/api/voice/upload" \
  -F "audio_file=@meeting.mp3"

# 多个文件上传（使用多个同名字段）
curl -X POST "http://localhost:8998/api/voice/upload" \
  -F "audio_file=@meeting1.mp3" \
  -F "audio_file=@meeting2.mp3" \
  -F "audio_file=@meeting3.mp3"
```

---

#### POST `/api/voice/transcribe`

**功能**：开始转写（支持单文件或批量，支持等待完成）。

**请求方式**：`POST`

**请求体**：

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|-------|------|-----|-------|------|
| `file_id` | string | 否 | - | 单个文件ID |
| `file_ids` | string[] | 否 | - | 多个文件ID数组 |
| `language` | string | 否 | `zh` | 语言类型 |
| `hotword` | string | 否 | `""` | 热词 |
| `wait` | boolean | 否 | `true` | 是否等待完成 |
| `timeout` | integer | 否 | `3600` | 超时时间（秒） |

**响应示例 (阻塞模式，wait=true)**：

```json
{
  "success": true,
  "message": "转写完成 1 个文件",
  "file_ids": ["a1b2c3d4-e5f6-7890-abcd-ef1234567890"]
}
```

**响应示例 (非阻塞模式，wait=false)**：

```json
{
  "success": true,
  "message": "已开始转写 2 个文件",
  "file_ids": [
    "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "b2c3d4e5-f6a7-8901-bcde-f12345678901"
  ],
  "count": 2
}
```

---

#### GET `/api/voice/status/{file_id}`

**功能**：获取转写状态。

**推荐替代**：使用 `GET /api/voice/files/{file_id}`

**请求方式**：`GET`

**响应示例**：

```json
{
  "success": true,
  "status": "processing",
  "progress": 65,
  "error_message": ""
}
```

---

#### GET `/api/voice/result/{file_id}`

**功能**：获取转写结果。

**推荐替代**：使用 `GET /api/voice/files/{file_id}?include_transcript=true&include_summary=true`

**请求方式**：`GET`

**响应示例**：

```json
{
  "success": true,
  "file_info": {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "original_name": "meeting.mp3",
    "upload_time": "2025-11-02 14:30:00"
  },
  "transcript": [
    {
      "speaker": "说话人1",
      "text": "会议内容...",
      "start_time": 0.5,
      "end_time": 3.2,
      "words": [
        {
          "text": "会议",
          "start": 0.5,
          "end": 0.8
        },
        {
          "text": "内容",
          "start": 0.8,
          "end": 1.1
        }
      ]
    }
  ],
  "summary": {
    "raw_text": "## 会议纪要...",
    "generated_at": "2025-11-02 14:35:00"
  }
}
```

---

#### POST `/api/voice/stop/{file_id}`

**功能**：停止转写（真正中断转写任务）。

**请求方式**：`POST`

**实现机制**：
- 设置文件的 `_cancelled` 标志为 `True`
- 尝试取消关联的 `Future` 任务
- 转写流程会在关键步骤检查取消标志，如果已取消则抛出 `InterruptedError`
- 文件状态更新为 `uploaded`，进度重置为 0
- 发送WebSocket消息通知前端

**响应示例**：

```json
{
  "success": true,
  "message": "已停止转写"
}
```

**注意事项**：
- 如果转写任务已经开始执行，可能无法立即停止，但会在下一个检查点停止
- 停止后的文件可以正常删除
- 停止操作会立即更新文件状态并通过WebSocket推送

---

#### GET `/api/voice/history`

**功能**：获取历史记录。

**推荐替代**：使用 `GET /api/voice/files?status=completed&include_history=true`

**请求方式**：`GET`

**响应示例**：

```json
{
  "success": true,
  "records": [
    {
      "file_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "filename": "meeting.mp3",
      "transcribe_time": "2025-11-02 14:35:00",
      "status": "completed",
      "details": "2位发言人, 25段对话"
    }
  ],
  "total": 1
}
```

---

#### POST `/api/voice/generate_summary/{file_id}`

**功能**：生成会议纪要。

**推荐替代**：使用 `PATCH /api/voice/files/{file_id}` with `action=generate_summary`

**请求方式**：`POST`

**响应示例**：

```json
{
  "success": true,
  "summary": {
    "raw_text": "## 会议纪要...",
    "generated_at": "2025-11-02 14:40:00",
    "model": "deepseek-chat",
    "status": "success"
  }
}
```

---

### 下载接口

#### GET `/api/voice/audio/{file_id}`

**功能**：获取或下载音频文件。

**请求方式**：`GET`

**路径参数**：

| 参数名 | 类型 | 必填 | 说明 |
|-------|------|-----|------|
| `file_id` | string | 是 | 文件唯一标识 |

**查询参数**：

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|-------|------|-----|-------|------|
| `download` | integer | 否 | `0` | 是否下载（0=预览，1=下载） |

**响应**：文件流

**cURL示例**：

```bash
# 预览音频
curl "http://localhost:8998/api/voice/audio/a1b2c3d4-e5f6-7890-abcd-ef1234567890"

# 下载音频
curl "http://localhost:8998/api/voice/audio/a1b2c3d4-e5f6-7890-abcd-ef1234567890?download=1" \
  -o meeting.mp3
```

---

#### GET `/api/voice/download_transcript/{file_id}`

**功能**：下载转写结果Word文档。

**请求方式**：`GET`

**路径参数**：

| 参数名 | 类型 | 必填 | 说明 |
|-------|------|-----|------|
| `file_id` | string | 是 | 文件唯一标识 |

**响应**：Word文档文件流 (.docx)

**cURL示例**：

```bash
curl "http://localhost:8998/api/voice/download_transcript/a1b2c3d4-e5f6-7890-abcd-ef1234567890" \
  -o transcript.docx
```

---

#### GET `/api/voice/download_summary/{file_id}`

**功能**：下载会议纪要Word文档。

**请求方式**：`GET`

**路径参数**：

| 参数名 | 类型 | 必填 | 说明 |
|-------|------|-----|------|
| `file_id` | string | 是 | 文件唯一标识 |

**响应**：Word文档文件流 (.docx)

**cURL示例**：

```bash
curl "http://localhost:8998/api/voice/download_summary/a1b2c3d4-e5f6-7890-abcd-ef1234567890" \
  -o summary.docx
```

---

#### GET `/api/voice/download_file/{filename}`

**功能**：下载输出文件（Word文档、ZIP压缩包等）。

**请求方式**：`GET`

**路径参数**：

| 参数名 | 类型 | 必填 | 说明 |
|-------|------|-----|------|
| `filename` | string | 是 | 文件名 |

**响应**：文件流

**cURL示例**：

```bash
curl "http://localhost:8998/api/voice/download_file/transcripts_20251102_143500.zip" \
  -o transcripts.zip
```

---

### WebSocket接口

#### WS `/api/voice/ws`

**功能**：实时接收文件处理状态更新。

**连接方式**：`WebSocket`

**消息格式 (服务器→客户端)**：

```json
{
  "type": "file_status",
  "file_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "processing",
  "progress": 50,
  "message": "正在转写..."
}
```

**消息类型**：

| type | 说明 |
|------|------|
| `connected` | WebSocket连接已建立 |
| `file_status` | 文件状态更新 |
| `subscribed` | 已订阅文件更新 |

**客户端订阅 (客户端→服务器)**：

```json
{
  "type": "subscribe",
  "file_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**进度条细化优化** ⭐ 新功能：

系统实现了智能进度追踪机制，避免进度条跳跃显示，提升用户体验：

1. **智能进度追踪器（后端 `SmartProgressTracker`）**：
   - 后台线程平滑推进进度，每1%逐步更新
   - 根据预估时间计算更新间隔（0.05s - 0.5s），确保平滑显示
   - 任务完成时极速补齐进度（2ms间隔），保证视觉连续性
   - 主线程无需sleep等待，不影响业务处理速度

2. **WebSocket去重机制（后端 `ConnectionManager`）**：
   - 只有当进度值增加、状态变化或完成时才发送消息
   - 避免发送重复的进度值，减少网络开销
   - 防止长音频处理时进度条反复跳跃

3. **前端防回退保护（前端 `app.js`）**：
   - 使用 `Math.max()` 确保进度只增不减
   - 忽略网络延迟导致的进度回退消息
   - 只有真正有变化时才更新UI，避免重复刷新

**效果**：
- ✅ 进度条平滑推进，不再出现突然跳跃
- ✅ 减少网络消息数量，降低服务器负载
- ✅ 提升用户体验，进度显示更加流畅自然

**JavaScript示例**：

```javascript
// 建立WebSocket连接
const ws = new WebSocket('ws://localhost:8998/api/voice/ws');

// 连接建立
ws.onopen = function() {
    console.log('WebSocket已连接');
};

// 接收消息（含进度条细化优化）
ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    console.log('收到消息:', data);
    
    if (data.type === 'file_status') {
        console.log(`文件 ${data.file_id}: ${data.status} (${data.progress}%)`);
        
        // ✅ 进度条细化优化：只更新进度增加的情况
        const file = getFileById(data.file_id);
        if (file) {
            const progressIncreased = data.progress > file.progress;
            const statusChanged = data.status !== file.status;
            
            // 只有当进度增加、状态变化或完成时才更新
            if (progressIncreased || statusChanged || data.status === 'completed') {
                // 确保进度只增不减（防止回退）
                file.progress = Math.max(file.progress, data.progress);
                file.status = data.status;
                // 更新UI进度条
                updateProgress(data.file_id, file.progress, data.message);
            }
        }
    }
};

// 订阅特定文件的状态更新
function subscribeFile(fileId) {
    ws.send(JSON.stringify({
        type: 'subscribe',
        file_id: fileId
    }));
}

// 连接关闭
ws.onclose = function() {
    console.log('WebSocket已断开');
};

// 错误处理
ws.onerror = function(error) {
    console.error('WebSocket错误:', error);
};
```

**Python示例**：

```python
import asyncio
import websockets
import json

async def connect_websocket():
    uri = "ws://localhost:8998/api/voice/ws"
    
    async with websockets.connect(uri) as websocket:
        # 接收连接消息
        message = await websocket.recv()
        print(f"收到消息: {message}")
        
        # 订阅文件更新
        file_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        await websocket.send(json.dumps({
            "type": "subscribe",
            "file_id": file_id
        }))
        
        # 持续接收消息
        while True:
            message = await websocket.recv()
            data = json.loads(message)
            
            if data['type'] == 'file_status':
                print(f"文件 {data['file_id']}: {data['status']} ({data['progress']}%)")

# 运行
asyncio.run(connect_websocket())
```

---

### 辅助接口

#### GET `/api/voice/languages`

**功能**：获取支持的语言列表。

**请求方式**：`GET`

**响应示例**：

```json
{
  "success": true,
  "languages": [
    {
      "value": "zh",
      "name": "中文普通话",
      "description": "适用于标准普通话音频"
    },
    {
      "value": "zh-dialect",
      "name": "方言混合",
      "description": "适用于包含方言的音频"
    },
    {
      "value": "zh-en",
      "name": "中英混合",
      "description": "适用于中英文混合的音频"
    },
    {
      "value": "en",
      "name": "英文",
      "description": "适用于纯英文音频"
    }
  ]
}
```

---

#### GET `/api/voice/transcript_files`

**功能**：列出所有转写文件。

**请求方式**：`GET`

**响应示例**：

```json
{
  "success": true,
  "files": [
    {
      "filename": "transcript_20251102_143500.docx",
      "filepath": "/home/user/phosys/transcripts/transcript_20251102_143500.docx",
      "size": 15360,
      "modified": "2025-11-02 14:35:00",
      "type": "Word文档"
    }
  ]
}
```

---

#### GET `/`

**功能**：主页面。

**请求方式**：`GET`

**响应**：HTML页面

---

#### GET `/healthz`

**功能**：健康检查。

**请求方式**：`GET`

**响应示例**：

```json
{
  "status": "ok",
  "version": "3.1.3-FunASR"
}
```

---

#### GET `/api/status`

**功能**：获取系统状态。

**请求方式**：`GET`

**响应示例**：

```json
{
  "success": true,
  "system": "running",
  "version": "3.1.3-FunASR",
  "models_loaded": true
}
```

---

## 数据模型

### FileInfo（文件信息）

```typescript
interface FileInfo {
  id: string;                    // 文件唯一标识
  filename: string;              // 存储文件名
  original_name: string;         // 原始文件名
  filepath: string;              // 文件路径
  size: number;                  // 文件大小（字节）
  upload_time: string;           // 上传时间
  complete_time?: string;        // 完成时间
  status: FileStatus;            // 文件状态
  progress: number;              // 处理进度（0-100）
  language: string;              // 语言类型
  error_message?: string;        // 错误信息
  transcript_data?: Transcript[]; // 转写数据
  transcript_file?: string;      // 转写文档路径
  meeting_summary?: Summary;     // 会议纪要
}
```

### FileStatus（文件状态）

```typescript
type FileStatus = 
  | 'uploaded'    // 已上传
  | 'processing'  // 处理中
  | 'completed'   // 已完成
  | 'error';      // 错误
```

### Transcript（转写记录）

```typescript
interface Transcript {
  speaker: string;      // 说话人
  text: string;         // 转写文本
  start_time: number;   // 开始时间（秒）
  end_time: number;     // 结束时间（秒）
  words?: WordTimestamp[]; // 词级别时间戳（可选，用于音字同步）
}

interface WordTimestamp {
  text: string;         // 词或短语的文本
  start: number;        // 开始时间（秒）
  end: number;          // 结束时间（秒）
}
```

**说明**：
- `words` 字段为可选字段，包含该转写段中每个词或短语的精确时间戳
- 时间戳单位：秒（浮点数，精确到小数点后2-3位）
- 词级别时间戳的生成方式：
  - **优先方案**：如果 FunASR 模型支持，直接使用模型输出的词级别时间戳
  - **降级方案**：使用 Jieba 分词 + 线性插值生成时间戳（根据字符数比例分配时间）
- 前端可以使用 `words` 字段实现音字同步高亮显示功能

### Summary（会议纪要）

```typescript
interface Summary {
  raw_text: string;      // 纪要文本
  generated_at: string;  // 生成时间
  model: string;         // 使用的模型
  status: string;        // 状态：success/error
  error?: string;        // 错误信息（如有）
}
```

### Statistics（统计信息）

```typescript
interface Statistics {
  speakers_count: number;     // 说话人数量
  segments_count: number;     // 转写段数
  total_duration: number;     // 总时长（秒）
  total_characters: number;   // 总字符数
  speakers: string[];         // 说话人列表
}
```

---

## 使用示例

### 场景1：快速转写单个文件

```bash
# cURL
# 1. 上传文件
FILE_ID=$(curl -X POST "http://localhost:8998/api/voice/upload" \
  -F "audio_file=@meeting.mp3" | jq -r '.file.id')

# 2. 开始转写（wait=true 等待完成）
curl -X POST "http://localhost:8998/api/voice/transcribe" \
  -H "Content-Type: application/json" \
  -d "{\"file_id\": \"$FILE_ID\", \"language\": \"zh\", \"wait\": true}"
```

```python
# Python
import requests

base_url = "http://localhost:8998/api/voice"

# 1. 上传文件
with open('meeting.mp3', 'rb') as f:
    files = {'audio_file': f}
    response = requests.post(f'{base_url}/upload', files=files)
    upload_result = response.json()
    file_id = upload_result['file']['id']

# 2. 开始转写（wait=true 等待完成）
transcribe_data = {
    'file_id': file_id,
    'language': 'zh',
    'wait': True
}
response = requests.post(f'{base_url}/transcribe', json=transcribe_data)
result = response.json()

if result.get('success') and result.get('status') == 'completed':
    print(f"转写完成: {result['filename']}")
    print(f"转写段数: {len(result['transcript'])}")
```

---

### 场景2：批量转写多个文件

```bash
# cURL
# 上传多个文件
for file in file1.mp3 file2.mp3 file3.mp3; do
  FILE_ID=$(curl -X POST "http://localhost:8998/api/voice/upload" \
    -F "audio_file=@$file" | jq -r '.file.id')
  
  # 开始转写
  curl -X POST "http://localhost:8998/api/voice/transcribe" \
    -H "Content-Type: application/json" \
    -d "{\"file_id\": \"$FILE_ID\", \"language\": \"zh\", \"wait\": true}"
done
```

```python
# Python
import requests

base_url = "http://localhost:8998/api/voice"
files_to_transcribe = ['file1.mp3', 'file2.mp3', 'file3.mp3']

for file_path in files_to_transcribe:
    # 上传文件
    with open(file_path, 'rb') as f:
        files = {'audio_file': f}
        response = requests.post(f'{base_url}/upload', files=files)
        file_id = response.json()['file']['id']
    
    # 开始转写
    transcribe_data = {
        'file_id': file_id,
        'language': 'zh',
        'wait': True
    }
    response = requests.post(f'{base_url}/transcribe', json=transcribe_data)
    result = response.json()
    print(f"{file_path}: {result.get('message')}")
```

---

### 场景3：转写并生成会议纪要

```bash
# cURL
# 1. 上传文件
FILE_ID=$(curl -X POST "http://localhost:8998/api/voice/upload" \
  -F "audio_file=@meeting.mp3" | jq -r '.file.id')

# 2. 开始转写
curl -X POST "http://localhost:8998/api/voice/transcribe" \
  -H "Content-Type: application/json" \
  -d "{\"file_id\": \"$FILE_ID\", \"language\": \"zh\", \"hotword\": \"季度报告 销售业绩 市场策略\", \"wait\": true}"

# 3. 生成会议纪要
curl -X POST "http://localhost:8998/api/voice/generate_summary/$FILE_ID"
```

```python
# Python
import requests

base_url = "http://localhost:8998/api/voice"

# 1. 上传文件
with open('meeting.mp3', 'rb') as f:
    files = {'audio_file': f}
    response = requests.post(f'{base_url}/upload', files=files)
    file_id = response.json()['file']['id']

# 2. 开始转写（带热词）
transcribe_data = {
    'file_id': file_id,
    'language': 'zh',
    'hotword': '季度报告 销售业绩 市场策略',
    'wait': True
}
response = requests.post(f'{base_url}/transcribe', json=transcribe_data)
result = response.json()

# 3. 生成会议纪要
response = requests.post(f'{base_url}/generate_summary/{file_id}')
summary_result = response.json()

response = requests.post(url, files=files, data=data)
result = response.json()

if result['success']:
    # 获取转写结果
    transcript = result['results'][0]['transcript']
    summary = result['results'][0]['summary']
    
    # 获取文件（base64解码）
    for file_data in result['files']:
        filename = file_data['filename']
        content = base64.b64decode(file_data['content_base64'])
        with open(filename, 'wb') as f:
            f.write(content)
        print(f"已保存: {filename}")
```

---

### 场景4：分步处理（上传→转写→查询）

```bash
# 1. 上传文件
RESULT=$(curl -X POST "http://localhost:8998/api/voice/upload" \
  -F "audio_file=@meeting.mp3")
FILE_ID=$(echo $RESULT | jq -r '.file.id')

# 2. 开始转写
curl -X POST "http://localhost:8998/api/voice/transcribe" \
  -H "Content-Type: application/json" \
  -d "{\"file_id\": \"$FILE_ID\", \"language\": \"zh\", \"wait\": false}"

# 3. 查询状态
curl "http://localhost:8998/api/voice/status/$FILE_ID"

# 4. 获取结果
curl "http://localhost:8998/api/voice/result/$FILE_ID"

# 5. 下载文档
curl "http://localhost:8998/api/voice/download_transcript/$FILE_ID" \
  -o transcript.docx
```

---

### 场景5：使用WebSocket实时监控进度

```javascript
// 建立WebSocket连接
const ws = new WebSocket('ws://localhost:8998/api/voice/ws');

ws.onopen = function() {
    console.log('WebSocket已连接');
};

ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    
    if (data.type === 'file_status') {
        console.log(`文件 ${data.file_id}:`);
        console.log(`  状态: ${data.status}`);
        console.log(`  进度: ${data.progress}%`);
        console.log(`  消息: ${data.message}`);
        
        // 更新UI
        updateProgressBar(data.file_id, data.progress);
        
        if (data.status === 'completed') {
            console.log('转写完成！');
            // 获取转写结果
            fetchTranscript(data.file_id);
        }
    }
};

// 订阅文件更新
function subscribeFile(fileId) {
    ws.send(JSON.stringify({
        type: 'subscribe',
        file_id: fileId
    }));
}
```

---

### 场景6：重新转写已上传的文件

```bash
# cURL
FILE_ID="a1b2c3d4-e5f6-7890-abcd-ef1234567890"

curl -X PATCH "http://localhost:8998/api/voice/files/$FILE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "retranscribe",
    "language": "zh-en",
    "hotword": "人工智能 机器学习 深度学习"
  }'
```

```python
# Python
import requests

file_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
url = f"http://localhost:8998/api/voice/files/{file_id}"

data = {
    "action": "retranscribe",
    "language": "zh-en",
    "hotword": "人工智能 机器学习 深度学习"
}

response = requests.patch(url, json=data)
result = response.json()

if result['success']:
    print("已开始重新转写")
```

---

### 场景7：查询历史记录并下载

```python
import requests

# 获取历史记录
url = "http://localhost:8998/api/voice/files"
params = {
    'status': 'completed',
    'include_history': True,
    'limit': 10
}

response = requests.get(url, params=params)
result = response.json()

if result['success']:
    for file_info in result['files']:
        file_id = file_info['id']
        filename = file_info['original_name']
        
        print(f"文件: {filename}")
        print(f"  ID: {file_id}")
        print(f"  完成时间: {file_info['complete_time']}")
        
        # 下载转写文档
        download_url = f"http://localhost:8998/api/voice/download_transcript/{file_id}"
        doc_response = requests.get(download_url)
        
        with open(f"{filename}.docx", 'wb') as f:
            f.write(doc_response.content)
        
        print(f"  已下载: {filename}.docx\n")
```

---

## 最佳实践

### 1. 选择合适的接口

- **快速使用**：使用 `POST /api/voice/transcribe` 接口，设置 `wait=true` 等待完成
- **精细控制**：使用分步接口（上传→转写→查询）
- **文件管理**：使用RESTful接口（GET/PATCH/DELETE `/api/voice/files/*`）

### 2. 使用热词提高准确率

```python
# 示例：会议转写，提供专业术语
hotwords = "人工智能 深度学习 神经网络 自然语言处理 计算机视觉"

data = {
    'language': 'zh',
    'hotword': hotwords,
    'generate_summary': True
}
```

### 3. 选择合适的返回类型

- `return_type=json`：适合Web应用，获取结构化数据
- `return_type=file`：适合直接下载文档
- `return_type=both`：适合需要数据和文件的场景

### 4. 使用WebSocket实时监控

```javascript
// 对于长时间转写任务，建议使用WebSocket实时获取进度
const ws = new WebSocket('ws://localhost:8998/api/voice/ws');

ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    if (data.type === 'file_status') {
        updateUI(data);
    }
};
```

### 5. 错误处理

```python
import requests

try:
    response = requests.post(url, files=files, data=data, timeout=300)
    response.raise_for_status()
    result = response.json()
    
    if not result['success']:
        print(f"处理失败: {result['message']}")
    else:
        # 处理成功
        pass
        
except requests.exceptions.Timeout:
    print("请求超时")
except requests.exceptions.RequestException as e:
    print(f"请求错误: {e}")
```

### 6. 批量处理优化

```python
# 对于大量文件，使用批量接口而不是循环单文件
files = [
    ('audio_files', open('file1.mp3', 'rb')),
    ('audio_files', open('file2.mp3', 'rb')),
    ('audio_files', open('file3.mp3', 'rb'))
]

# 一次请求处理多个文件（系统会自动并发处理）
response = requests.post(url, files=files, data=data)
```

---

## 常见问题

### Q1: 支持哪些音频格式？

支持：`mp3`, `wav`, `m4a`, `flac`, `aac`, `ogg`, `wma`

### Q2: 文件大小有限制吗？

建议单个文件不超过 100MB。对于更大的文件，建议先进行分割处理。

### Q3: 转写需要多长时间？

通常情况下，转写时间约为音频时长的 1/3 到 1/2。例如，10分钟的音频大约需要 3-5 分钟完成转写。

### Q4: 如何生成会议纪要？

需要配置 DeepSeek 或 OpenAI API Key：

```bash
export DEEPSEEK_API_KEY="your-api-key"
# 或
export OPENAI_API_KEY="your-api-key"
```

然后在转写时设置 `generate_summary=true`。

### Q5: 热词如何使用？

热词用于提高特定词汇的识别准确率，多个热词用空格分隔：

```
hotword="人工智能 深度学习 神经网络"
```

### Q6: WebSocket连接断开怎么办？

WebSocket支持重连，建议实现自动重连机制：

```javascript
function connectWebSocket() {
    const ws = new WebSocket('ws://localhost:8998/api/voice/ws');
    
    ws.onclose = function() {
        console.log('连接断开，3秒后重连...');
        setTimeout(connectWebSocket, 3000);
    };
    
    return ws;
}
```

### Q7: 如何获取API文档？

访问以下地址查看交互式API文档：

- Swagger UI: http://localhost:8998/docs
- ReDoc: http://localhost:8998/redoc

---

## 更新日志

### v3.1.3-FunASR (2025-12-04)

**API简化与优化**

#### 接口变更
- ✅ **删除一站式转写接口**：移除 `POST /api/voice/transcribe_all` 接口，统一使用普通转写接口
- ✅ **删除清空Dify生成文件功能**：移除 `DELETE /api/voice/files/_clear_dify` 特殊操作
- ✅ **增强普通转写接口**：优化 `POST /api/voice/transcribe` 接口
  - 当 `wait=true` 时，返回结果包含 `status` 字段和 `transcript` 字段
  - `transcript` 中不包含 `words` 字段，只保留基本转写信息（speaker, text, start_time, end_time）
  - 单个文件时，顶层直接返回 `transcript`，方便 Dify 等工具使用

#### 技术改进
- ✅ 简化了API接口结构，统一使用RESTful风格
- ✅ 优化了转写接口的返回结构，更适合工作流工具集成
- ✅ 清理了代码中的冗余功能，提高代码可维护性

### v3.1.2-FunASR (2025-11-25)

**功能增强**

#### 新增功能
- ✅ **词级别时间戳**：后端自动生成每个词或短语的精确时间戳
  - 优先使用 FunASR 原生词级别时间戳（如果模型支持）
  - 降级方案：使用 Jieba 分词 + 线性插值生成时间戳
  - 确保所有转写结果都包含词级别时间信息
- ✅ **音字同步高亮显示**：前端实现音频播放与转写文字的实时同步
  - 播放音频时自动高亮当前播放位置对应的转写文字
  - 支持点击转写文字跳转到对应音频位置
  - 自动滚动到高亮词，提升阅读体验
  - 支持词级别和句子级别两种模式，向后兼容
- ✅ **进度条细化优化**：避免进度条跳跃显示，提升用户体验
  - 智能进度追踪器：后台线程平滑推进进度，每1%逐步更新
  - WebSocket去重机制：避免发送重复的进度值，减少网络开销
  - 前端防回退保护：确保进度只增不减，忽略网络延迟导致的进度回退
  - 快速追赶机制：任务完成时极速补齐进度，保证视觉连续性

#### 技术改进
- ✅ 优化了词级别时间戳的生成逻辑，确保文本完整性
- ✅ 改进了前端高亮匹配算法，使用左闭右开区间避免相邻词同时高亮
- ✅ 优化了 DOM 元素缓存机制，提升性能
- ✅ 添加了时间戳验证和错误处理，提高健壮性
- ✅ 实现了智能进度追踪器，后台线程平滑推进进度，避免进度条跳跃
- ✅ 优化了 WebSocket 消息发送逻辑，减少重复消息和网络开销

#### API变更
- ✅ `transcript` 数组中的每个条目现在包含可选的 `words` 字段，用于词级别时间戳
- ✅ `words` 字段结构：`[{text: string, start: number, end: number}, ...]`
- ✅ 所有返回转写结果的接口都已支持 `words` 字段

### v3.1.1-FunASR (2025-11-13)

**功能增强与修复**

#### 新增功能
- ✅ **真正的停止转写功能**：支持中断正在进行的转写任务，通过 `_cancelled` 标志和 `InterruptedError` 机制实现
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

- ✅ 统一版本号为 3.1.0-FunASR
- ✅ 标识FunASR一体化架构模式

### v3.0.0 (2025-11-02)

- ✅ 新增RESTful风格文件资源接口
- ✅ 支持批量文件处理
- ✅ 支持三种返回模式（json/file/both）
- ✅ WebSocket实时状态推送
- ✅ AI会议纪要生成
- ✅ 历史记录持久化
- ✅ 文件管理功能（重新转写、删除等）

---

## 技术支持

如有问题或建议，请：

- 📧 查看项目 README
- 📚 访问 API 文档：http://localhost:8998/docs
- 💬 提交 Issue

---

**⭐ 如果这个项目对你有帮助，欢迎 Star！**

