# 前端功能与API接口对应关系详细文档

> 版本: 3.1.1-FunASR  
> 更新时间: 2025-11-13  
> 说明: 本文档详细描述前端每个功能对应的API接口调用关系

---

## 目录

- [页面架构](#页面架构)
- [主页面功能详解](#主页面功能详解)
- [结果页面功能详解](#结果页面功能详解)
- [WebSocket实时通信](#websocket实时通信)
- [完整用户流程](#完整用户流程)
- [错误处理机制](#错误处理机制)
- [性能优化策略](#性能优化策略)

---

## 页面架构

系统包含两个主要页面：

### 1. 主页面 (index.html)
- **路径**: `/` 或 `/index.html`
- **JavaScript**: `/static/js/app.js`
- **核心类**: `TranscriptionApp`
- **主要功能**: 文件上传、转写管理、历史记录

### 2. 结果页面 (result.html)
- **路径**: `/result.html?file_id={file_id}`
- **JavaScript**: `/static/js/result.js`
- **核心类**: `ResultViewer`
- **主要功能**: 查看转写结果、下载文档、音频播放

---

## 主页面功能详解

### 功能1: 页面初始化

#### 1.1 触发时机
- 用户打开主页面
- 页面 DOM 加载完成后自动执行

#### 1.2 执行流程

```javascript
// app.js 第3-18行
class TranscriptionApp {
    constructor() {
        this.uploadedFiles = [];
        this.statusInterval = null;
        this.refreshInterval = 5000;
        this.ws = null;
        this.wsReconnectDelay = 3000;
        this.init();
    }

    init() {
        this.bindEvents();              // 绑定事件监听器
        this.loadUploadedFiles();       // 加载文件列表
        this.connectWebSocket();        // 建立WebSocket连接
    }
}
```

#### 1.3 API调用

**API 1: 获取文件列表**

```javascript
// app.js 第294-311行
async loadUploadedFiles() {
    const response = await fetch('/api/voice/files');
    const result = await response.json();
    
    if (result.success) {
        // 显示所有未完成的文件（uploaded, processing, error）
        // 不显示已完成的文件（completed）
        this.uploadedFiles = result.files.filter(f => 
            f.status === 'uploaded' || f.status === 'processing' || f.status === 'error'
        );
        this.renderFileList();
    }
}
```

| 项目 | 内容 |
|-----|------|
| **接口** | `GET /api/voice/files` |
| **请求参数** | 无（可选：`status`, `limit`, `offset`, `include_history`） |
| **响应数据** | `{ success, files: [], pagination, statistics }` |
| **files[]字段** | 每个文件包含：`id`, `filename`, `original_name`, `status`, `progress`, `download_urls` 等 |
| **download_urls** | **重要**：包含可访问的下载链接（`audio`, `transcript`, `summary`） |
| **数据处理** | 过滤出未完成的文件（uploaded, processing, error） |
| **UI更新** | 渲染文件列表表格 |
| **注意事项** | ⚠️ 不要使用 `filepath` 字段（服务器本地路径），使用 `download_urls.audio` 访问音频 |

**API 2: 建立WebSocket连接**

```javascript
// app.js 第93-149行
connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/voice/ws`;
    this.ws = new WebSocket(wsUrl);
}
```

| 项目 | 内容 |
|-----|------|
| **接口** | `WS /api/voice/ws` |
| **连接类型** | WebSocket持久连接 |
| **消息格式** | JSON格式 |
| **作用** | 实时接收文件状态更新 |

---

### 功能2: 文件上传

#### 2.1 触发时机
- 用户点击"上传文件"按钮选择文件
- 用户拖拽文件到上传区域

#### 2.2 执行流程

```
用户操作
    ↓
触发事件 (change / drop)
    ↓
handleFileSelect() / handleDrop()
    ↓
uploadMultipleFiles() - 批量处理
    ↓
uploadSingleFile() - 单个上传 (并发)
    ↓
API: POST /api/voice/upload
    ↓
返回文件ID
    ↓
自动开始转写
```

#### 2.3 关键代码

**步骤1: 文件选择处理**

```javascript
// app.js 第194-201行
handleFileSelect(event) {
    const files = Array.from(event.target.files);
    if (files.length > 0) {
        this.uploadMultipleFiles(files);
    }
    event.target.value = ''; // 清空以允许重复上传
}
```

**步骤2: 批量上传处理**

```javascript
// app.js 第226-273行
async uploadMultipleFiles(files) {
    // 1. 过滤音频文件
    const audioFiles = files.filter(file => {
        const allowedExtensions = ['.mp3', '.wav', '.m4a', '.flac', '.aac', '.ogg', '.wma'];
        const fileExtension = file.name.toLowerCase().substring(file.name.lastIndexOf('.'));
        return allowedExtensions.includes(fileExtension);
    });

    // 2. 检查文件大小
    const maxSize = 100 * 1024 * 1024; // 100MB
    const oversizedFiles = audioFiles.filter(file => file.size > maxSize);
    
    // 3. 并发上传所有文件
    const uploadPromises = audioFiles.map(file => this.uploadSingleFile(file));
    const results = await Promise.all(uploadPromises);
    
    // 4. 自动开始转写
    const uploadedFileIds = successResults.map(r => r.file.id);
    await this.autoStartTranscription(uploadedFileIds);
}
```

**步骤3: 单个文件上传**

```javascript
// app.js 第275-292行
async uploadSingleFile(file) {
    const formData = new FormData();
    formData.append('audio_file', file);
    
    const response = await fetch('/api/voice/upload', {
        method: 'POST',
        body: formData
    });
    
    const result = await response.json();
    return result;
}
```

#### 2.4 API详细说明

**API: 上传音频文件**

| 项目 | 内容 |
|-----|------|
| **接口** | `POST /api/voice/upload` |
| **请求方式** | `multipart/form-data` |
| **请求参数** | `audio_file`: File对象 |
| **文件限制** | 单个文件最大100MB |
| **支持格式** | mp3, wav, m4a, flac, aac, ogg, wma |

**请求示例**:
```http
POST /api/voice/upload HTTP/1.1
Content-Type: multipart/form-data; boundary=----WebKitFormBoundary

------WebKitFormBoundary
Content-Disposition: form-data; name="audio_file"; filename="meeting.mp3"
Content-Type: audio/mpeg

[文件二进制数据]
------WebKitFormBoundary--
```

**响应示例**:
```json
{
  "success": true,
  "message": "文件上传成功",
  "file": {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "filename": "meeting_20251102_143000.mp3",
    "original_name": "meeting.mp3",
    "filepath": "/home/user/phosys/uploads/meeting_20251102_143000.mp3",
    "size": 5242880,
    "upload_time": "2025-11-02 14:30:00",
    "status": "uploaded",
    "progress": 0
  }
}
```

#### 2.5 文件验证逻辑

```javascript
// 前端验证
允许的音频格式: ['.mp3', '.wav', '.m4a', '.flac', '.aac', '.ogg', '.wma']
文件大小限制: 100MB (104,857,600 bytes)

// 验证失败处理
- 非音频文件: 自动过滤，显示提示
- 超大文件: 阻止上传，显示错误
```

---

### 功能3: 自动开始转写

#### 3.1 触发时机
- 文件上传成功后**自动触发**
- 无需用户手动操作

#### 3.2 执行流程

```javascript
// app.js 第396-431行
async autoStartTranscription(fileIds) {
    const response = await fetch('/api/voice/transcribe', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            file_ids: fileIds,
            wait: false  // 🔧 不等待转写完成，立即返回
        })
    });

    const result = await response.json();
    
    if (result.success) {
        this.showSuccess(`已自动开始转写 ${result.count} 个文件`);
        await this.loadUploadedFiles(); // 刷新列表显示 processing 状态
    }
}
```

#### 3.3 API详细说明

**API: 开始转写**

| 项目 | 内容 |
|-----|------|
| **接口** | `POST /api/voice/transcribe` |
| **请求方式** | `application/json` |
| **阻塞模式** | `wait: false` (非阻塞，立即返回) |
| **批量支持** | 支持多个文件ID同时转写 |

**请求示例**:
```json
{
  "file_ids": [
    "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "b2c3d4e5-f6a7-8901-bcde-f12345678901"
  ],
  "language": "zh",
  "hotword": "",
  "wait": false
}
```

**响应示例 (非阻塞模式)**:
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

#### 3.4 关键参数说明

| 参数 | 类型 | 说明 |
|-----|------|------|
| `file_ids` | array | 文件ID数组，支持批量转写 |
| `language` | string | 语言类型：zh/en/zh-en/zh-dialect，默认zh |
| `hotword` | string | 热词，空格分隔，提高特定词汇识别率 |
| `wait` | boolean | 是否等待完成：false=立即返回，true=阻塞等待 |
| `timeout` | integer | 超时时间（秒），仅wait=true时有效，默认3600 |

---

### 功能4: 实时状态更新 (WebSocket)

#### 4.1 WebSocket连接建立

```javascript
// app.js 第93-149行
connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/voice/ws`;
    
    this.ws = new WebSocket(wsUrl);
    
    // 连接成功
    this.ws.onopen = (event) => {
        console.log('✅ WebSocket连接已建立');
        this.stopAutoRefresh(); // 停止轮询
    };
    
    // 接收消息
    this.ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        this.handleWebSocketMessage(data);
    };
    
    // 连接关闭
    this.ws.onclose = (event) => {
        console.log('⚠️ WebSocket连接已关闭');
        this.startAutoRefresh(5000); // 启动轮询作为后备
        setTimeout(() => this.connectWebSocket(), 3000); // 3秒后重连
    };
}
```

#### 4.2 消息处理流程

```javascript
// app.js 第151-191行
handleWebSocketMessage(data) {
    const { type, file_id, status, progress, message } = data;
    
    switch (type) {
        case 'connected':
            console.log('WebSocket已连接:', message);
            break;
            
        case 'file_status':
            // 更新文件状态
            const file = this.uploadedFiles.find(f => f.id === file_id);
            if (file) {
                file.status = status;
                file.progress = progress;
                this.renderFileList(); // 立即更新UI
                
                if (status === 'completed') {
                    setTimeout(() => this.loadUploadedFiles(), 500);
                }
            }
            break;
    }
}
```

#### 4.3 WebSocket消息格式

**服务器 → 客户端消息类型**

**1. 连接成功消息**
```json
{
  "type": "connected",
  "message": "WebSocket连接已建立"
}
```

**2. 文件状态更新消息**
```json
{
  "type": "file_status",
  "file_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "processing",
  "progress": 50,
  "message": "正在转写..."
}
```

**状态值说明**:
| 状态 | 说明 | 进度范围 |
|-----|------|---------|
| `uploaded` | 已上传 | 0 |
| `processing` | 转写中 | 1-99 |
| `completed` | 已完成 | 100 |
| `error` | 出错 | 0 |

**3. 订阅确认消息**
```json
{
  "type": "subscribed",
  "file_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "message": "已订阅文件 xxx 的状态更新"
}
```

**客户端 → 服务器消息**

**订阅文件更新**
```json
{
  "type": "subscribe",
  "file_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

#### 4.4 WebSocket优势

| 对比项 | WebSocket模式 | 轮询模式 |
|-------|--------------|---------|
| **实时性** | 实时推送（延迟<100ms） | 延迟5秒 |
| **服务器负载** | 低（仅推送变化） | 高（每5秒查询） |
| **网络流量** | 极低（仅传输变化） | 高（重复传输） |
| **用户体验** | 流畅、即时反馈 | 有延迟感 |

---

### 功能5: 文件列表显示

#### 5.1 触发时机
- 页面加载时
- 文件上传后
- WebSocket推送状态更新时
- 轮询刷新时（WebSocket断开时）

#### 5.2 渲染逻辑

```javascript
// app.js 第313-374行
renderFileList() {
    const tbody = document.getElementById('file-list-tbody');
    const emptyDiv = document.getElementById('file-list-empty');
    
    if (this.uploadedFiles.length === 0) {
        tbody.innerHTML = '';
        emptyDiv.classList.add('show');
        return;
    }
    
    const html = this.uploadedFiles.map(file => {
        const statusClass = `status-${file.status}`;
        const statusText = this.getStatusText(file.status);
        const statusIcon = this.getStatusIcon(file.status);
        
        // 根据状态显示不同的操作按钮
        let actionButton = '';
        if (file.status === 'processing') {
            // 转写中：显示停止按钮
            actionButton = `<button onclick="app.stopTranscription('${file.id}')">
                                <i class="fas fa-stop"></i>
                            </button>`;
        } else {
            // 其他状态：显示删除按钮
            actionButton = `<button onclick="app.deleteFile('${file.id}')">
                                <i class="fas fa-trash"></i>
                            </button>`;
        }
        
        return `<tr data-file-id="${file.id}">
                    <td>${file.original_name}</td>
                    <td>${file.upload_time}</td>
                    <td><span class="${statusClass}">${statusIcon} ${statusText}</span></td>
                    <td>${actionButton}</td>
                </tr>`;
    }).join('');
    
    tbody.innerHTML = html;
}
```

#### 5.3 状态显示

**状态图标和文本映射**

```javascript
// app.js 第376-394行
getStatusText(status) {
    const statusMap = {
        'uploaded': '已上传',
        'processing': '正在转写',
        'completed': '已完成',
        'error': '出错'
    };
    return statusMap[status] || status;
}

getStatusIcon(status) {
    const iconMap = {
        'uploaded': '<i class="fas fa-check-circle"></i>',
        'processing': '<i class="fas fa-spinner fa-spin"></i>',
        'completed': '<i class="fas fa-check-double"></i>',
        'error': '<i class="fas fa-exclamation-circle"></i>'
    };
    return iconMap[status] || '';
}
```

**视觉效果**:
- `uploaded`: 绿色对勾图标 ✓
- `processing`: 旋转的加载图标 ⟳
- `completed`: 双对勾图标 ✓✓
- `error`: 红色感叹号图标 ⚠

---

### 功能6: 停止转写

#### 6.1 触发时机
- 点击文件列表中的"停止"按钮（仅在 processing 状态时显示）

#### 6.2 执行流程

```javascript
// app.js 第509-532行
async stopTranscription(fileId) {
    const file = this.uploadedFiles.find(f => f.id === fileId);
    if (!file) return;
    
    // 确认对话框
    if (!confirm(`确定要停止转写 "${file.original_name}" 吗？`)) {
        return;
    }

    try {
        const response = await fetch(`/api/voice/stop/${fileId}`, {
            method: 'POST'
        });
        const result = await response.json();
        
        if (result.success) {
            this.showSuccess('已停止转写');
            await this.loadUploadedFiles(); // 刷新列表
        } else {
            this.showError(result.message || '停止失败');
        }
    } catch (error) {
        this.showError('停止失败: ' + error.message);
    }
}
```

#### 6.3 API详细说明

| 项目 | 内容 |
|-----|------|
| **接口** | `POST /api/voice/stop/{file_id}` |
| **请求方式** | POST |
| **路径参数** | `file_id`: 文件唯一标识 |
| **实现机制** | 设置 `_cancelled` 标志，尝试取消Future任务，转写流程会在关键步骤检查并中断 |
| **状态更新** | 文件状态更新为 `uploaded`，进度重置为 0 |
| **WebSocket推送** | 立即推送状态更新消息 |

**响应示例**:
```json
{
  "success": true,
  "message": "已停止转写"
}
```

**注意事项**:
- ✅ 现在支持真正中断转写任务，通过 `_cancelled` 标志和 `InterruptedError` 机制实现
- ✅ 停止后的文件可以正常删除
- ✅ 如果转写任务已经开始执行，可能无法立即停止，但会在下一个检查点停止

---

### 功能7: 删除文件

#### 7.1 触发时机
- 点击文件列表中的"删除"按钮（非 processing 状态时显示，或已停止转写的文件）
- 点击历史记录中的"删除"按钮

#### 7.2 执行流程

```javascript
// app.js 第534-577行
async deleteFile(fileId) {
    const file = this.uploadedFiles.find(f => f.id === fileId);
    if (!file) return;
    
    // 确认对话框
    if (!confirm(`确定要删除文件 "${file.original_name}" 吗？`)) {
        return;
    }

    try {
        const response = await fetch(`/api/voice/files/${fileId}`, {
            method: 'DELETE'
        });
        
        // ✅ 修复：正确处理HTTP错误响应
        const result = await response.json();
        
        // 检查HTTP状态码
        if (!response.ok) {
            // HTTP错误响应（如400, 404, 500等）
            // FastAPI的HTTPException返回格式: {"detail": "错误信息"}
            const errorMsg = result.detail || result.message || `删除失败: HTTP ${response.status}`;
            this.showError(errorMsg);
            return;
        }
        
        if (result.success) {
            // ✅ 修复：立即从本地数组中移除文件，立即更新UI
            this.uploadedFiles = this.uploadedFiles.filter(f => f.id !== fileId);
            this.renderFileList();
            
            this.showSuccess('文件删除成功');
            
            // 然后刷新列表确保同步
            await this.loadUploadedFiles();
        } else {
            this.showError(result.message || result.detail || '删除失败');
        }
    } catch (error) {
        this.showError('删除失败: ' + error.message);
    }
}
```

#### 7.3 API详细说明

| 项目 | 内容 |
|-----|------|
| **接口** | `DELETE /api/voice/files/{file_id}` |
| **请求方式** | DELETE |
| **路径参数** | `file_id`: 文件唯一标识，支持特殊值：`_clear_dify`、`_clear_all` |
| **删除内容** | 音频文件 + 转写结果 + 相关文档 |
| **特殊操作** | `_clear_dify`（清空Dify生成文件）、`_clear_all`（清空所有历史记录） |

**响应示例（正常删除）**:
```json
{
  "success": true,
  "message": "文件删除成功"
}
```

**响应示例（清空Dify生成文件）**:
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

#### 7.4 删除限制

```javascript
// 前端限制
- processing 状态的文件不显示删除按钮（除非已停止转写）
- 删除前需要用户确认
- 删除后立即从UI中移除文件

// 后端限制
- processing 状态且未取消的文件无法删除（返回400错误）
- 已停止转写的文件（_cancelled = True）可以正常删除
- 删除操作会级联删除所有相关文件
```

#### 7.5 清空功能

**清空Dify生成文件** (`file_id = "_clear_dify"`):
- 删除所有 `transcripts_*.zip` 文件
- 删除对应的音频文件、转写文档和会议纪要
- 从历史记录中移除相关记录

**清空所有历史记录** (`file_id = "_clear_all"`):
- 删除所有音频文件、转写文档和会议纪要
- 清空输出目录和历史记录文件

---

### 功能8: 查看历史记录

#### 8.1 触发时机
- 点击"查看历史记录"链接
- 打开历史记录模态框

#### 8.2 执行流程

```javascript
// app.js 第569-598行
async openHistoryModal() {
    const modal = document.getElementById('history-modal');
    if (modal) {
        modal.style.display = 'block';
        await this.loadHistoryRecords();
    }
}

async loadHistoryRecords() {
    try {
        const response = await fetch('/api/voice/history');
        const result = await response.json();
        
        if (result.success) {
            this.renderHistoryRecords(result.records);
        } else {
            this.showError('加载历史记录失败');
        }
    } catch (error) {
        console.error('加载历史记录失败:', error);
        this.showError('加载历史记录失败: ' + error.message);
    }
}
```

#### 8.3 API详细说明

| 项目 | 内容 |
|-----|------|
| **接口** | `GET /api/voice/history` |
| **请求方式** | GET |
| **返回内容** | 所有已完成的转写记录 |
| **排序方式** | 按完成时间倒序 |

**响应示例**:
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

#### 8.4 历史记录渲染

```javascript
// app.js 第600-657行
renderHistoryRecords(records) {
    const tbody = document.getElementById('history-table-tbody');
    const emptyDiv = document.getElementById('history-empty');
    
    if (!records || records.length === 0) {
        tbody.innerHTML = '';
        emptyDiv.classList.add('show');
        return;
    }
    
    const html = records.map((record, index) => `
        <tr>
            <td>${index + 1}</td>
            <td>${this.escapeHtml(record.filename)}</td>
            <td>${record.transcribe_time || '-'}</td>
            <td><span class="history-status-badge">${statusText}</span></td>
            <td>
                <button onclick="app.viewHistoryResult('${record.file_id}')">
                    <i class="fas fa-eye"></i> 查看结果
                </button>
            </td>
            <td>
                <button onclick="app.deleteHistoryRecord('${record.file_id}')">
                    <i class="fas fa-trash"></i>
                </button>
                <button onclick="app.refreshHistoryRecord('${record.file_id}')">
                    <i class="fas fa-sync-alt"></i>
                </button>
            </td>
        </tr>
    `).join('');
    
    tbody.innerHTML = html;
}
```

---

### 功能9: 查看转写结果

#### 9.1 触发时机
- 点击历史记录中的"查看结果"按钮

#### 9.2 执行流程

```javascript
// app.js 第677-682行
viewHistoryResult(fileId) {
    // 关闭历史记录模态框
    this.closeHistoryModal();
    // 跳转到结果查看页面
    window.location.href = `/result.html?file_id=${fileId}`;
}
```

**注意**: 这是页面跳转，不是API调用。跳转到结果页面后，由结果页面的JavaScript负责加载数据。

---

### 功能10: 轮询刷新（后备方案）

#### 10.1 触发时机
- WebSocket连接失败时
- WebSocket断开连接时
- 作为WebSocket的后备方案

#### 10.2 轮询机制

```javascript
// app.js 第58-89行
startAutoRefresh(interval = 5000) {
    // 如果间隔没有变化，不需要重新创建定时器
    if (this.statusInterval && this.refreshInterval === interval) {
        return;
    }
    
    // 先停止现有的定时器
    this.stopAutoRefresh();
    
    // 记录当前刷新间隔
    this.refreshInterval = interval;
    
    // 创建新的定时器
    this.statusInterval = setInterval(async () => {
        await this.loadUploadedFiles(); // 刷新文件列表
        
        // 如果历史记录模态框是打开的，也刷新历史记录
        const historyModal = document.getElementById('history-modal');
        if (historyModal && historyModal.style.display === 'block') {
            await this.loadHistoryRecords();
        }
    }, interval);
    
    console.log(`自动刷新已设置: ${interval}ms`);
}

stopAutoRefresh() {
    if (this.statusInterval) {
        clearInterval(this.statusInterval);
        this.statusInterval = null;
    }
}
```

#### 10.3 轮询策略

| 项目 | 配置 |
|-----|------|
| **刷新间隔** | 120000ms (120秒，2分钟) |
| **API调用** | `GET /api/voice/files` |
| **请求参数** | 无（默认返回所有文件） |
| **响应数据** | `{ success, files: [], pagination, statistics }`，每个文件包含 `download_urls` 字段 |
| **触发条件** | WebSocket连接失败或断开 |
| **停止条件** | WebSocket重新连接成功 |
| **注意事项** | 使用 `download_urls.audio` 访问音频，不要使用 `filepath` |

---

## 结果页面功能详解

### 功能1: 页面初始化

#### 1.1 触发时机
- 从URL参数获取 `file_id`
- 页面加载完成后自动执行

#### 1.2 执行流程

```javascript
// result.js 第1-22行
class ResultViewer {
    constructor() {
        this.fileId = null;
        this.fileData = null;
        this.transcriptData = null;
        this.init();
    }

    init() {
        // 从URL获取file_id
        const urlParams = new URLSearchParams(window.location.search);
        this.fileId = urlParams.get('file_id');
        
        if (!this.fileId) {
            alert('未指定文件ID');
            this.goBack();
            return;
        }

        this.bindEvents();
        this.loadFileData(); // 加载文件数据
    }
}
```

#### 1.3 API调用

**API: 获取转写结果**

```javascript
// result.js 第68-89行
async loadFileData() {
    try {
        const response = await fetch(`/api/voice/result/${this.fileId}`);
        const result = await response.json();
        
        if (result.success) {
            this.fileData = result.file_info;
            this.transcriptData = result.transcript;
            
            this.renderFileInfo();    // 渲染文件信息
            this.renderTranscript();  // 渲染转写内容
            this.loadAudio();        // 加载音频
        } else {
            alert(result.message || '加载文件数据失败');
            this.goBack();
        }
    } catch (error) {
        console.error('加载文件数据失败:', error);
        alert('加载文件数据失败');
        this.goBack();
    }
}
```

| 项目 | 内容 |
|-----|------|
| **接口** | `GET /api/voice/result/{file_id}` |
| **请求方式** | GET |
| **路径参数** | `file_id`: 文件唯一标识 |

**响应示例**:
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
      "text": "大家好，今天我们讨论项目进展。",
      "start_time": 0.5,
      "end_time": 3.2
    },
    {
      "speaker": "说话人2",
      "text": "好的，我先汇报一下我负责的部分。",
      "start_time": 3.5,
      "end_time": 6.8
    }
  ],
  "summary": {
    "raw_text": "## 会议纪要\n\n...",
    "generated_at": "2025-11-02 14:35:00",
    "model": "deepseek-chat"
  }
}
```

---

### 功能2: 渲染转写内容

#### 2.1 渲染逻辑

```javascript
// result.js 第98-126行
renderTranscript() {
    const transcriptContent = document.getElementById('transcript-content');
    if (!transcriptContent) return;
    
    if (!this.transcriptData || this.transcriptData.length === 0) {
        transcriptContent.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-microphone-slash"></i>
                <p>暂无转写结果</p>
            </div>
        `;
        return;
    }
    
    const html = this.transcriptData.map((entry, index) => `
        <div class="transcript-entry" 
             data-index="${index}" 
             data-start-time="${entry.start_time || 0}">
            <div class="speaker-info">
                <span class="speaker-label">${this.escapeHtml(entry.speaker || '发言人')}</span>
                <span class="timestamp">${this.formatTime(entry.start_time)} - ${this.formatTime(entry.end_time)}</span>
            </div>
            <div class="transcript-text">${this.escapeHtml(entry.text || '')}</div>
        </div>
    `).join('');
    
    transcriptContent.innerHTML = html;
    this.bindTranscriptClickEvents(); // 绑定点击事件
}
```

#### 2.2 转写条目结构

每条转写记录包含：
- **说话人标签**: 说话人1、说话人2...
- **时间戳**: 开始时间 - 结束时间 (mm:ss)
- **转写文本**: 完整的发言内容

#### 2.3 交互功能

**点击跳转播放**

```javascript
// result.js 第128-158行
bindTranscriptClickEvents() {
    const entries = document.querySelectorAll('.transcript-entry');
    entries.forEach(entry => {
        entry.style.cursor = 'pointer';
        entry.addEventListener('click', () => {
            const startTime = parseFloat(entry.dataset.startTime);
            this.seekToTime(startTime);
        });
        entry.title = '点击跳转到该时间点播放';
    });
}

seekToTime(time) {
    const audioPlayer = document.getElementById('audio-player');
    if (!audioPlayer) return;
    
    // 设置音频播放位置
    audioPlayer.currentTime = time;
    
    // 如果音频未播放，则开始播放
    if (audioPlayer.paused) {
        audioPlayer.play().catch(err => {
            console.error('播放失败:', err);
        });
    }
    
    this.showSuccess(`已跳转到 ${this.formatTime(time)}`);
}
```

**无API调用**: 纯前端操作，直接操作HTML5 Audio元素。

---

### 功能3: 音频播放器

#### 3.1 加载音频

```javascript
// result.js 第161-171行
loadAudio() {
    if (!this.fileData) return;
    
    const audioSource = document.getElementById('audio-source');
    const audioPlayer = document.getElementById('audio-player');
    
    if (audioSource && audioPlayer) {
        audioSource.src = `/api/voice/audio/${this.fileId}`;
        audioPlayer.load();
    }
}
```

| 项目 | 内容 |
|-----|------|
| **音频源** | `/api/voice/audio/{file_id}` |
| **加载方式** | 浏览器自动请求音频流 |
| **播放控制** | HTML5 Audio原生控件 |

**HTML结构**:
```html
<audio id="audio-player" controls>
    <source id="audio-source" src="/api/voice/audio/{file_id}" type="audio/mpeg">
    您的浏览器不支持音频播放
</audio>
```

#### 3.2 播放控制功能

| 功能 | 实现方式 | API调用 |
|-----|---------|---------|
| 播放/暂停 | HTML5 Audio原生 | 无 |
| 进度条拖动 | HTML5 Audio原生 | 无 |
| 音量调节 | HTML5 Audio原生 | 无 |
| 播放速度 | `audioPlayer.playbackRate` | 无 |
| 跳转时间 | `audioPlayer.currentTime` | 无 |

---

### 功能4: 下载转写结果

#### 4.1 触发时机
- 点击"下载转写结果"按钮

#### 4.2 执行流程

```javascript
// result.js 第191-199行
async downloadTranscript() {
    try {
        // 直接下载文件
        window.location.href = `/api/voice/download_transcript/${this.fileId}`;
    } catch (error) {
        console.error('下载转写结果失败:', error);
        alert('下载失败');
    }
}
```

| 项目 | 内容 |
|-----|------|
| **接口** | `GET /api/voice/download_transcript/{file_id}` |
| **文件格式** | Word文档 (.docx) |
| **下载方式** | 浏览器自动下载 |
| **文件内容** | 完整的转写结果 + 格式化排版 |

**下载文件示例名称**:
```
transcript_20251102_143500.docx
```

---

### 功能5: 下载音频文件

#### 5.1 执行流程

```javascript
// result.js 第201-209行
async downloadAudio() {
    try {
        // 直接下载音频文件
        window.location.href = `/api/audio/${this.fileId}?download=1`;
    } catch (error) {
        console.error('下载音频失败:', error);
        alert('下载失败');
    }
}
```

| 项目 | 内容 |
|-----|------|
| **接口** | `GET /api/audio/{file_id}?download=1` |
| **文件格式** | 原始上传的音频格式 |
| **查询参数** | `download=1` 触发下载，`download=0` 为在线播放 |

---

### 功能6: 复制转写结果

#### 6.1 触发时机
- 点击"复制"按钮

#### 6.2 执行流程

```javascript
// result.js 第220-231行
copyTranscript() {
    if (!this.transcriptData || this.transcriptData.length === 0) {
        alert('暂无转写结果');
        return;
    }
    
    const text = this.transcriptData.map(entry => 
        `${entry.speaker || '发言人'} [${this.formatTime(entry.start_time)} - ${this.formatTime(entry.end_time)}]:\n${entry.text}`
    ).join('\n\n');
    
    this.copyToClipboard(text);
}
```

**复制内容格式**:
```
说话人1 [00:00 - 00:03]:
大家好，今天我们讨论项目进展。

说话人2 [00:03 - 00:06]:
好的，我先汇报一下我负责的部分。
```

**无API调用**: 使用 `navigator.clipboard.writeText()` 或 `document.execCommand('copy')` 实现。

---

### 功能7: 搜索转写内容

#### 7.1 触发时机
- 点击"搜索"按钮打开搜索框
- 在搜索框中输入关键词

#### 7.2 执行流程

```javascript
// result.js 第283-321行
performSearch(keyword) {
    const searchResults = document.getElementById('search-results');
    if (!searchResults) return;
    
    if (!keyword || keyword.trim() === '') {
        searchResults.innerHTML = '<p class="text-muted">输入关键词开始搜索</p>';
        return;
    }
    
    // 在已加载的转写数据中搜索
    const results = this.transcriptData.filter(entry => 
        entry.text && entry.text.includes(keyword)
    );
    
    if (results.length === 0) {
        searchResults.innerHTML = '<p class="text-muted">未找到匹配结果</p>';
        return;
    }
    
    // 高亮显示匹配的关键词
    const html = results.map((entry, index) => {
        const highlightedText = entry.text.replace(
            new RegExp(this.escapeRegex(keyword), 'g'),
            match => `<mark>${match}</mark>`
        );
        
        return `
            <div class="search-result-item" onclick="resultViewer.scrollToEntry(${this.transcriptData.indexOf(entry)})">
                <div class="speaker">${entry.speaker} - ${this.formatTime(entry.start_time)}</div>
                <div class="text">${highlightedText}</div>
            </div>
        `;
    }).join('');
    
    searchResults.innerHTML = html;
}
```

**无API调用**: 纯前端搜索，在内存中的 `transcriptData` 数组中过滤。

#### 7.3 搜索功能特点

- **实时搜索**: 输入时立即显示结果
- **关键词高亮**: 使用 `<mark>` 标签高亮匹配文本
- **点击跳转**: 点击搜索结果可滚动到对应位置
- **高亮效果**: 跳转后目标条目会短暂高亮显示

---

### 功能8: 调整播放速度

#### 8.1 执行流程

```javascript
// result.js 第211-217行
changePlaybackSpeed(speed) {
    const audioPlayer = document.getElementById('audio-player');
    if (audioPlayer) {
        audioPlayer.playbackRate = parseFloat(speed);
        this.showSuccess(`播放速度已设置为 ${speed}x`);
    }
}
```

**支持的播放速度**:
- 0.5x (慢速)
- 0.75x
- 1.0x (正常)
- 1.25x
- 1.5x
- 2.0x (快速)

**无API调用**: 直接操作HTML5 Audio的 `playbackRate` 属性。

---

## WebSocket实时通信

### 连接生命周期

```
[页面加载]
    ↓
建立WebSocket连接
    ↓
[连接成功] → 停止轮询 → 实时接收消息
    ↓
[连接断开] → 启动轮询 → 3秒后尝试重连
    ↓
循环...
```

### 消息流转图

```
服务器端转写进程
    ↓
更新文件状态
    ↓
WebSocket推送消息
    ↓
前端handleWebSocketMessage()
    ↓
更新uploadedFiles数组
    ↓
renderFileList()
    ↓
UI实时刷新
```

### 优势对比

| 特性 | WebSocket | 轮询 |
|-----|----------|------|
| 延迟 | <100ms | 5000ms |
| CPU占用 | 低 | 高 |
| 网络流量 | 极小 | 大 |
| 服务器压力 | 小 | 大 |
| 实时性 | 优秀 | 一般 |
| 兼容性 | 现代浏览器 | 所有浏览器 |

---

## 完整用户流程

### 流程1: 首次使用 - 上传并转写

```
1. 用户打开主页
   ↓ API: GET /api/voice/files
   ↓ API: WS /api/voice/ws (建立连接)

2. 用户选择/拖拽音频文件
   ↓ 前端: 验证文件格式和大小
   ↓ API: POST /api/voice/upload (批量上传)
   ↓ 返回: file_id数组

3. 自动开始转写
   ↓ API: POST /api/voice/transcribe
   ↓ 参数: {file_ids: [...], wait: false}
   ↓ 返回: 立即返回成功

4. 实时显示进度
   ↓ WebSocket: 接收status更新
   ↓ 前端: 更新进度条和状态

5. 转写完成
   ↓ WebSocket: status=completed, progress=100
   ↓ 前端: 显示"已完成"，隐藏进度条
   ↓ 文件从列表中移除（进入历史记录）
```

### 流程2: 查看历史记录

```
1. 用户点击"查看历史记录"
   ↓ 前端: 打开模态框
   ↓ API: GET /api/voice/history

2. 显示历史列表
   ↓ 前端: 渲染历史记录表格

3. 用户点击"查看结果"
   ↓ 前端: 跳转到 /result.html?file_id={id}
   ↓ API: GET /api/voice/result/{file_id}
   ↓ API: GET /api/voice/audio/{file_id} (音频流)

4. 查看和交互
   ↓ 前端: 渲染转写内容
   ↓ 前端: 加载音频播放器
   ↓ 用户: 点击转写条目跳转播放
   ↓ 用户: 搜索关键词
   ↓ 用户: 复制内容

5. 下载文档
   ↓ API: GET /api/voice/download_transcript/{file_id}
   ↓ 浏览器: 自动下载Word文档
```

### 流程3: 删除文件

```
1. 用户点击"删除"按钮
   ↓ 前端: 显示确认对话框

2. 用户确认删除
   ↓ API: DELETE /api/voice/files/{file_id}
   ↓ 返回: {success: true}

3. 刷新列表
   ↓ API: GET /api/voice/files
   ↓ 前端: 重新渲染文件列表
```

---

## 错误处理机制

### 前端错误处理

#### 1. 文件上传错误

```javascript
// 验证失败
if (!allowedExtensions.includes(fileExtension)) {
    this.showError('不支持的文件格式');
    return;
}

if (file.size > maxSize) {
    this.showError('文件超过100MB限制');
    return;
}

// 上传失败
try {
    const response = await fetch('/api/voice/upload', {...});
    const result = await response.json();
    if (!result.success) {
        this.showError(result.message);
    }
} catch (error) {
    this.showError('上传失败: ' + error.message);
}
```

#### 2. WebSocket连接错误

```javascript
// 连接失败
this.ws.onerror = (error) => {
    console.error('❌ WebSocket错误:', error);
};

// 连接断开
this.ws.onclose = (event) => {
    console.log('⚠️ WebSocket连接已关闭');
    this.startAutoRefresh(5000); // 启动轮询后备
    setTimeout(() => this.connectWebSocket(), 3000); // 3秒后重连
};
```

#### 3. API请求错误

```javascript
async deleteFile(fileId) {
    try {
        const response = await fetch(`/api/voice/files/${fileId}`, {
            method: 'DELETE'
        });
        const result = await response.json();
        
        if (result.success) {
            this.showSuccess('文件删除成功');
        } else {
            this.showError(result.message || '删除失败');
        }
    } catch (error) {
        this.showError('删除失败: ' + error.message);
    }
}
```

### 用户提示方式

#### 1. 错误提示（模态框）

```javascript
showError(message) {
    const errorMessage = document.getElementById('error-message');
    const errorModal = document.getElementById('error-modal');
    
    errorMessage.textContent = message;
    errorModal.style.display = 'block';
}
```

显示为模态对话框，需要用户点击"确定"关闭。

#### 2. 成功提示（Toast）

```javascript
showSuccess(message) {
    const successDiv = document.createElement('div');
    successDiv.className = 'success-toast';
    successDiv.innerHTML = `
        <i class="fas fa-check-circle"></i>
        <span>${message}</span>
    `;
    // 样式: 右上角绿色提示框
    // 3秒后自动消失
}
```

显示为右上角浮动提示，3秒后自动消失。

---

## 性能优化策略

### 1. 批量上传优化

```javascript
// 并发上传，不是串行
const uploadPromises = audioFiles.map(file => this.uploadSingleFile(file));
const results = await Promise.all(uploadPromises);
```

**优势**: 多个文件同时上传，不需要等待前一个文件上传完成。

### 2. WebSocket vs 轮询

```javascript
// WebSocket连接成功 → 停止轮询
this.ws.onopen = () => {
    this.stopAutoRefresh();
};

// WebSocket断开 → 启动轮询
this.ws.onclose = () => {
    this.startAutoRefresh(5000);
};
```

**优势**: 优先使用WebSocket，降低服务器负载和网络流量。

### 3. 按需加载历史记录

```javascript
// 只在打开历史记录模态框时才加载
async openHistoryModal() {
    modal.style.display = 'block';
    await this.loadHistoryRecords(); // 延迟加载
}
```

**优势**: 减少页面初始加载时间。

### 4. 智能刷新

```javascript
// 只刷新未完成的文件
this.uploadedFiles = result.files.filter(f => 
    f.status === 'uploaded' || f.status === 'processing' || f.status === 'error'
);
```

**优势**: 减少DOM操作，已完成的文件移至历史记录。

### 5. 搜索优化

```javascript
// 前端内存搜索，不请求服务器
const results = this.transcriptData.filter(entry => 
    entry.text && entry.text.includes(keyword)
);
```

**优势**: 即时响应，无网络延迟。

---

## API调用统计

### 主页面 (index.html)

| API接口 | 调用时机 | 频率 |
|--------|---------|------|
| `GET /api/voice/files` | 页面加载、刷新 | 初始1次 + 轮询时每120秒（WebSocket断开时） |
| `POST /api/voice/upload` | 上传文件 | 每个文件1次 |
| `POST /api/voice/transcribe` | 上传后自动触发 | 每批文件1次 |
| `POST /api/voice/stop/{file_id}` | 点击停止按钮 | 按需 |
| `DELETE /api/voice/files/{file_id}` | 点击删除按钮 | 按需 |
| `GET /api/voice/history` | 打开历史记录 | 按需 |
| `WS /api/voice/ws` | 页面加载 | 1次（持久连接） |

### 结果页面 (result.html)

| API接口 | 调用时机 | 频率 |
|--------|---------|------|
| `GET /api/voice/result/{file_id}` | 页面加载 | 1次 |
| `GET /api/voice/audio/{file_id}` | 音频播放器加载 | 1次 |
| `GET /api/voice/download_transcript/{file_id}` | 点击下载按钮 | 按需 |
| `GET /api/audio/{file_id}?download=1` | 点击下载音频 | 按需 |

---

## 总结

### 核心设计理念

1. **非阻塞设计**: 上传和转写不阻塞界面，用户可继续操作
2. **实时反馈**: WebSocket推送状态，用户实时看到进度
3. **智能降级**: WebSocket失败时自动切换到轮询
4. **批量处理**: 支持多文件并发上传和转写
5. **用户友好**: 清晰的状态提示和错误处理

### 技术亮点

- ✅ **WebSocket实时通信**: 降低延迟，提升体验
- ✅ **Promise并发处理**: 批量上传不串行
- ✅ **智能状态管理**: 根据状态显示不同操作
- ✅ **前端优化**: 搜索、播放控制等无需请求服务器
- ✅ **错误容错**: 完善的错误处理和用户提示

### 数据流向

```
用户操作
    ↓
前端JavaScript (app.js / result.js)
    ↓
API接口 (FastAPI后端)
    ↓
业务逻辑处理
    ↓
WebSocket推送 / HTTP响应
    ↓
前端更新UI
    ↓
用户看到结果
```

---

## 最新更新 (v3.1.1-FunASR, 2025-11-13)

### 功能增强
- ✅ **真正的停止转写功能**：现在可以真正中断转写任务，通过 `_cancelled` 标志和 `InterruptedError` 机制实现
- ✅ **清空Dify生成文件**：新增清空Dify生成文件功能，可精确删除Dify一站式转写生成的.zip文件及其对应的音频文件
- ✅ **清空所有历史记录**：新增一键清空所有历史记录功能

### 问题修复
- ✅ **文件名唯一性修复**：修复了批量转写时文件名冲突问题，使用微秒级时间戳和 `file_id` 确保唯一性
- ✅ **删除已停止转写文件**：修复了停止转写后无法删除文件的问题
- ✅ **WebSocket进度跳转修复**：修复了转写进度反复跳转的问题，确保进度只增不减
- ✅ **删除后UI立即更新**：修复了删除文件后前端界面不立即更新的问题
- ✅ **删除错误提示修复**：修复了删除已停止转写文件时出现"删除失败"错误提示的问题

---

**文档完成！** 🎉

本文档详细描述了音频转写系统前端的每个功能及其对应的API接口调用关系，包括触发时机、执行流程、请求参数、响应数据等完整信息。

