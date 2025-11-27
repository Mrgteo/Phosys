// app.js - 音频转写系统前端JavaScript（多文件并发版本）

class TranscriptionApp {
    constructor() {
        this.uploadedFiles = [];  // 存储上传的文件列表
        this.statusInterval = null;
        this.refreshInterval = 120000;  // 当前刷新间隔（毫秒）- 30秒，降低服务器压力
        this.ws = null;  // WebSocket连接
        this.wsReconnectDelay = 3000;  // WebSocket重连延迟
        this.init();
    }

    init() {
        this.bindEvents();
        this.loadUploadedFiles();
        this.connectWebSocket();  // 🔌 建立WebSocket连接
        // WebSocket会在连接成功/失败后自动设置轮询
    }

    bindEvents() {
        // 辅助函数：安全绑定事件
        const safeBindEvent = (id, event, handler) => {
            const element = document.getElementById(id);
            if (element) {
                element.addEventListener(event, handler);
            } else {
                console.warn(`Element not found: ${id}`);
            }
        };
        
        // 文件上传事件
        safeBindEvent('audio-file-input', 'change', (e) => this.handleFileSelect(e));
        
        // 拖拽上传事件
        const uploadArea = document.getElementById('upload-area');
        if (uploadArea) {
            uploadArea.addEventListener('dragover', (e) => this.handleDragOver(e));
            uploadArea.addEventListener('dragleave', (e) => this.handleDragLeave(e));
            uploadArea.addEventListener('drop', (e) => this.handleDrop(e));
        }
        
        // 模态框关闭事件
        const closeBtn = document.querySelector('.close-btn');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => this.closeModal());
        }
        
        const errorModal = document.getElementById('error-modal');
        if (errorModal) {
            errorModal.addEventListener('click', (e) => {
                if (e.target.id === 'error-modal') {
                    this.closeModal();
                }
            });
        }
        
        // 历史记录操作按钮事件（使用事件委托，因为按钮在模态框内）
        document.addEventListener('click', (e) => {
            const btnClearDify = e.target.closest('#btn-clear-dify');
            const btnClearAll = e.target.closest('#btn-clear-all');
            
            if (btnClearDify) {
                e.preventDefault();
                e.stopPropagation();
                this.clearDifyFiles();
            } else if (btnClearAll) {
                e.preventDefault();
                e.stopPropagation();
                this.clearAllHistory();
            }
        });
    }

    startAutoRefresh(interval = 120000) {
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
            await this.loadUploadedFiles();
            
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

    // ======== WebSocket实时通信 ========
    
    connectWebSocket() {
        // 构建WebSocket URL
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/api/voice/ws`;
        
        console.log('🔌 正在连接WebSocket:', wsUrl);
        
        try {
            this.ws = new WebSocket(wsUrl);
            
            // 连接建立
            this.ws.onopen = (event) => {
                console.log('✅ WebSocket连接已建立');
                // WebSocket已连接，停止轮询
                this.stopAutoRefresh();
                console.log('🎯 轮询已停止，使用WebSocket实时推送');
            };
            
            // 接收消息
            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    console.log('📨 收到WebSocket消息:', data);
                    this.handleWebSocketMessage(data);
                } catch (error) {
                    console.error('解析WebSocket消息失败:', error);
                }
            };
            
            // 连接关闭
            this.ws.onclose = (event) => {
                console.log('⚠️ WebSocket连接已关闭');
                this.ws = null;
                // 启动轮询作为后备（直到WebSocket重连成功）
                if (!this.statusInterval) {
                    console.log('⚠️ 启动轮询作为后备方案');
                    this.startAutoRefresh(120000);
                }
                // 尝试重连
                setTimeout(() => {
                    console.log('🔄 尝试重新连接WebSocket...');
                    this.connectWebSocket();
                }, this.wsReconnectDelay);
            };
            
            // 连接错误
            this.ws.onerror = (error) => {
                console.error('❌ WebSocket错误:', error);
            };
            
        } catch (error) {
            console.error('❌ 创建WebSocket连接失败:', error);
            // 如果WebSocket不可用，使用轮询作为后备
            console.log('⚠️ WebSocket不可用，使用轮询模式');
            this.startAutoRefresh(120000);
        }
    }
    
    handleWebSocketMessage(data) {
        const { type, file_id, status, progress, message } = data;
        
        switch (type) {
            case 'connected':
                console.log('WebSocket已连接:', message);
                break;
                
            case 'file_status':
                console.log(`📝 文件状态更新: ${file_id} - ${status} (${progress}%)`);
                // 更新文件状态
                const file = this.uploadedFiles.find(f => f.id === file_id);
                
                // ✅ 修复：处理删除状态
                if (status === 'deleted') {
                    // 立即从列表中移除
                    this.uploadedFiles = this.uploadedFiles.filter(f => f.id !== file_id);
                    this.renderFileList();
                    console.log(`🗑️ 文件已删除: ${file_id}`);
                    return;
                }
                
                if (file) {
                    // ✅ 修复：只更新进度，如果新进度严格大于当前进度，或者状态发生变化
                    // 对于相同进度值，只有在状态变化时才更新（避免反复刷新）
                    const progressIncreased = progress > file.progress;
                    const statusChanged = status !== file.status;
                    const isCompleted = status === 'completed';
                    
                    // 只有当进度增加、状态变化或完成时才更新
                    if (progressIncreased || (statusChanged && progress >= file.progress) || isCompleted) {
                        // 确保进度只增不减（防止回退）
                        const newProgress = Math.max(file.progress, progress);
                        
                        // 只有真正有变化时才更新UI
                        if (newProgress !== file.progress || statusChanged) {
                            file.status = status;
                            file.progress = newProgress;
                            // 立即更新UI
                            this.renderFileList();
                        }
                        
                        // 如果转写完成，延迟刷新列表（移除已完成文件）
                        if (status === 'completed') {
                            console.log('✅ 转写完成，延迟刷新列表');
                            setTimeout(() => {
                                this.loadUploadedFiles();
                            }, 1000);
                        }
                    } else {
                        // 如果新进度小于当前进度，忽略（可能是旧消息或网络延迟）
                        console.log(`⚠️ 忽略进度回退或重复消息: ${file_id} 从 ${file.progress}% 到 ${progress}% (状态: ${file.status} -> ${status})`);
                    }
                } else {
                    // 文件不在当前列表中，可能是新文件或已完成文件
                    // 如果是processing状态，说明是新文件，需要添加到列表
                    if (status === 'processing' || status === 'uploaded') {
                        // 延迟加载，避免频繁调用
                        if (!this.pendingLoadTimeout) {
                            this.pendingLoadTimeout = setTimeout(() => {
                                this.loadUploadedFiles();
                                this.pendingLoadTimeout = null;
                            }, 500);
                        }
                    }
                }
                break;
                
            default:
                console.log('未处理的消息类型:', type);
        }
    }
    
    sendWebSocketMessage(message) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message));
        }
    }

    // 文件上传相关方法
    handleFileSelect(event) {
        const files = Array.from(event.target.files);
        if (files.length > 0) {
            this.uploadMultipleFiles(files);
        }
        // 清空input以允许重复上传同一文件
        event.target.value = '';
    }

    handleDragOver(event) {
        event.preventDefault();
        event.stopPropagation();
        event.currentTarget.classList.add('drag-over');
    }

    handleDragLeave(event) {
        event.preventDefault();
        event.stopPropagation();
        event.currentTarget.classList.remove('drag-over');
    }

    handleDrop(event) {
        event.preventDefault();
        event.stopPropagation();
        event.currentTarget.classList.remove('drag-over');
        
        const files = Array.from(event.dataTransfer.files);
        if (files.length > 0) {
            this.uploadMultipleFiles(files);
        }
    }

    async uploadMultipleFiles(files) {
        // 过滤出音频文件
        const audioFiles = files.filter(file => {
            const allowedTypes = ['audio/mp3', 'audio/wav', 'audio/m4a', 'audio/flac', 'audio/aac', 'audio/ogg', 'audio/wma', 'audio/mpeg'];
            const allowedExtensions = ['.mp3', '.wav', '.m4a', '.flac', '.aac', '.ogg', '.wma'];
            const fileExtension = file.name.toLowerCase().substring(file.name.lastIndexOf('.'));
            return allowedTypes.includes(file.type) || allowedExtensions.includes(fileExtension);
        });

        if (audioFiles.length === 0) {
            this.showError('没有有效的音频文件');
            return;
        }

        if (audioFiles.length !== files.length) {
            this.showSuccess(`已过滤 ${files.length - audioFiles.length} 个非音频文件`);
        }

        // 检查文件大小 (100MB限制)
        const maxSize = 100 * 1024 * 1024;
        const oversizedFiles = audioFiles.filter(file => file.size > maxSize);
        if (oversizedFiles.length > 0) {
            this.showError(`以下文件超过100MB限制：\n${oversizedFiles.map(f => f.name).join('\n')}`);
            return;
        }

        // 并发上传所有文件（不显示全屏遮罩，直接在文件列表中显示状态）
        const uploadPromises = audioFiles.map(file => this.uploadSingleFile(file));
        
        try {
            const results = await Promise.all(uploadPromises);
            const successResults = results.filter(r => r.success);
            const failCount = results.filter(r => !r.success).length;
            
            if (successResults.length > 0) {
                this.showSuccess(`成功上传 ${successResults.length} 个文件${failCount > 0 ? `，${failCount} 个失败` : ''}`);
                await this.loadUploadedFiles();
                
                // 自动开始转写上传成功的文件
                const uploadedFileIds = successResults.map(r => r.file.id);
                await this.autoStartTranscription(uploadedFileIds);
            } else {
                this.showError('所有文件上传失败');
            }
        } catch (error) {
            this.showError('上传失败: ' + error.message);
        }
    }

    async uploadSingleFile(file) {
        try {
            const formData = new FormData();
            formData.append('audio_file', file);
            
            const response = await fetch('/api/voice/upload', {
                method: 'POST',
                body: formData
            });
            
            const result = await response.json();
            return result;
            
        } catch (error) {
            console.error(`上传文件失败 ${file.name}:`, error);
            return { success: false, message: error.message };
        }
    }

    async loadUploadedFiles() {
        try {
            const response = await fetch('/api/voice/files');
            const result = await response.json();
            
            if (result.success) {
                // 显示所有未完成的文件（uploaded, processing, error）
                // 不显示已完成的文件（completed）
                const serverFiles = result.files.filter(f => 
                    f.status === 'uploaded' || f.status === 'processing' || f.status === 'error'
                );
                
                // ✅ 修复：合并服务器数据和WebSocket实时更新的数据
                // 保留WebSocket更新的最新进度，避免进度回退
                const mergedFiles = [];
                let hasChanges = false;  // 标记是否有实际变化
                
                // 处理服务器返回的文件
                serverFiles.forEach(serverFile => {
                    const localFile = this.uploadedFiles.find(f => f.id === serverFile.id);
                    if (localFile) {
                        // 如果本地文件存在，优先使用本地的进度（WebSocket实时更新）
                        // 但确保状态同步（如果服务器状态更新了，也要同步）
                        // ✅ 关键修复：确保进度只增不减，取本地和服务器进度的最大值
                        const mergedProgress = Math.max(localFile.progress || 0, serverFile.progress || 0);
                        
                        // 状态合并逻辑：
                        // - 如果本地是 processing，保持 processing（实时更新中）
                        // - 如果服务器状态是 completed 或 error，使用服务器状态
                        // - 否则使用服务器状态
                        let mergedStatus = serverFile.status;
                        if (localFile.status === 'processing' && serverFile.status !== 'completed' && serverFile.status !== 'error') {
                            mergedStatus = 'processing'; // 保持实时处理状态
                        }
                        
                        // ✅ 修复：只有当进度或状态有实际变化时才标记为有变化
                        const progressChanged = mergedProgress !== localFile.progress;
                        const statusChanged = mergedStatus !== localFile.status;
                        
                        if (progressChanged || statusChanged) {
                            hasChanges = true;
                        }
                        
                        mergedFiles.push({
                            ...serverFile,
                            progress: mergedProgress, // 确保进度只增不减
                            status: mergedStatus
                        });
                    } else {
                        // 服务器中有但本地没有的新文件
                        hasChanges = true;  // 新文件需要更新UI
                        mergedFiles.push(serverFile);
                    }
                });
                
                // 保留本地有但服务器没有的文件（可能是刚上传的，服务器还没同步）
                // ✅ 修复：但排除已删除的文件（deleted状态）
                this.uploadedFiles.forEach(localFile => {
                    if (!serverFiles.find(f => f.id === localFile.id)) {
                        // 只保留processing或uploaded状态的文件，排除deleted状态
                        if ((localFile.status === 'processing' || localFile.status === 'uploaded') 
                            && localFile.status !== 'deleted') {
                            mergedFiles.push(localFile);
                        } else {
                            hasChanges = true;  // 文件被移除，需要更新UI
                        }
                    }
                });
                
                // ✅ 修复：只有当有实际变化时才更新数组和渲染UI，避免不必要的重渲染导致进度条跳动
                if (hasChanges || mergedFiles.length !== this.uploadedFiles.length) {
                    this.uploadedFiles = mergedFiles;
                    this.renderFileList();
                }
            }
        } catch (error) {
            console.error('加载文件列表失败:', error);
        }
    }

    renderFileList() {
        const tbody = document.getElementById('file-list-tbody');
        const emptyDiv = document.getElementById('file-list-empty');
        
        if (!tbody || !emptyDiv) {
            console.error('File list elements not found');
            return;
        }
        
        if (this.uploadedFiles.length === 0) {
            tbody.innerHTML = '';
            emptyDiv.classList.add('show');
            return;
        }
        
        emptyDiv.classList.remove('show');
        
        const html = this.uploadedFiles.map(file => {
            const statusClass = `status-${file.status}`;
            const statusText = this.getStatusText(file.status);
            const statusIcon = this.getStatusIcon(file.status);
            
            // 根据状态显示不同的操作按钮
            let actionButton = '';
            if (file.status === 'processing') {
                // 正在转写：显示停止按钮
                actionButton = `
                    <button class="action-stop-btn" 
                            onclick="app.stopTranscription('${file.id}')"
                            title="停止转写">
                        <i class="fas fa-stop"></i>
                    </button>
                `;
            } else {
                // 其他状态：显示删除按钮
                actionButton = `
                    <button class="action-delete-btn" 
                            onclick="app.deleteFile('${file.id}')"
                            title="删除">
                        <i class="fas fa-trash"></i>
                    </button>
                `;
            }
            
            // 获取进度值（默认为0）
            const progress = file.progress || 0;
            
            // 生成进度条HTML（在转写中、已完成或出错时显示）
            let progressBarHtml = '';
            if (file.status === 'processing' || file.status === 'completed' || file.status === 'error') {
                // 根据状态添加不同的class
                let progressBarClass = '';
                if (file.status === 'processing') {
                    progressBarClass = 'processing';
                } else if (file.status === 'completed') {
                    progressBarClass = 'completed';
                } else if (file.status === 'error') {
                    progressBarClass = 'error';
                }
                
                // 确保进度值在0-100之间
                const safeProgress = Math.max(0, Math.min(100, progress));
                
                progressBarHtml = `
                    <div class="file-progress-container">
                        <div class="file-progress-bar ${progressBarClass}" style="width: ${safeProgress}%">
                            <span class="file-progress-text">${safeProgress}%</span>
                        </div>
                    </div>
                `;
            }
            
            return `
                <tr data-file-id="${file.id}">
                    <td class="file-title">${file.original_name}</td>
                    <td class="file-progress-cell">
                        ${progressBarHtml || '<span class="file-progress-empty">-</span>'}
                    </td>
                    <td>${file.upload_time}</td>
                    <td>
                        <span class="upload-status-badge ${statusClass}">
                            ${statusIcon} ${statusText}
                        </span>
                    </td>
                    <td>
                        ${actionButton}
                    </td>
                </tr>
            `;
        }).join('');
        
        tbody.innerHTML = html;
    }

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

    async autoStartTranscription(fileIds) {
        if (!fileIds || fileIds.length === 0) {
            return;
        }

        try {
            const response = await fetch('/api/voice/transcribe', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    file_ids: fileIds,
                    wait: false  // 🔧 不等待转写完成，立即返回，让前端可以实时显示状态
                })
            });

            const result = await response.json();
            
            if (result.success) {
                this.showSuccess(`已自动开始转写 ${result.count} 个文件`);
                
                // 立即刷新一次文件列表以显示 processing 状态
                await this.loadUploadedFiles();
                
                // WebSocket会实时推送状态，不需要频繁轮询
                console.log('✅ 转写已启动，WebSocket将实时推送状态更新');
                
            } else {
                this.showError(result.message || '启动转写失败');
            }
        } catch (error) {
            console.error('自动启动转写失败:', error);
            this.showError('启动转写失败: ' + error.message);
        }
    }

    async stopTranscription(fileId) {
        const file = this.uploadedFiles.find(f => f.id === fileId);
        if (!file) return;
        
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
                await this.loadUploadedFiles();
            } else {
                this.showError(result.message || '停止失败');
            }
        } catch (error) {
            this.showError('停止失败: ' + error.message);
        }
    }

    async deleteFile(fileId) {
        const file = this.uploadedFiles.find(f => f.id === fileId);
        if (!file) return;
        
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

    viewResult(fileId) {
        // 跳转到结果查看页面
        window.location.href = `/result.html?file_id=${fileId}`;
    }


    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // 注意: 下载转写、清空、导出、刷新、生成纪要等功能已移至result.html页面

    showError(message) {
        const errorMessage = document.getElementById('error-message');
        const errorModal = document.getElementById('error-modal');
        
        if (errorMessage) {
            errorMessage.textContent = message;
        }
        if (errorModal) {
            errorModal.style.display = 'block';
        }
    }

    showSuccess(message) {
        // 创建成功提示
        const successDiv = document.createElement('div');
        successDiv.className = 'success-toast';
        successDiv.innerHTML = `
            <i class="fas fa-check-circle"></i>
            <span>${message}</span>
        `;
        successDiv.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: #48bb78;
            color: white;
            padding: 15px 20px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(72, 187, 120, 0.4);
            z-index: 10000;
            display: flex;
            align-items: center;
            gap: 10px;
            animation: slideIn 0.3s ease-out;
        `;
        
        document.body.appendChild(successDiv);
        
        // 3秒后自动移除
        setTimeout(() => {
            successDiv.style.animation = 'slideOut 0.3s ease-out';
            setTimeout(() => {
                if (successDiv.parentNode) {
                    successDiv.parentNode.removeChild(successDiv);
                }
            }, 300);
        }, 3000);
    }

    closeModal() {
        const modal = document.getElementById('error-modal');
        if (modal) {
            modal.style.display = 'none';
        }
    }

    showLoading(show) {
        const overlay = document.getElementById('loading-overlay');
        if (overlay) {
            overlay.style.display = show ? 'block' : 'none';
        }
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    // 历史记录相关方法
    async openHistoryModal() {
        const modal = document.getElementById('history-modal');
        if (modal) {
            modal.style.display = 'block';
            await this.loadHistoryRecords();
        }
    }

    closeHistoryModal() {
        const modal = document.getElementById('history-modal');
        if (modal) {
            modal.style.display = 'none';
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

    renderHistoryRecords(records) {
        const tbody = document.getElementById('history-table-tbody');
        const emptyDiv = document.getElementById('history-empty');
        
        if (!tbody || !emptyDiv) {
            console.error('History table elements not found');
            return;
        }
        
        if (!records || records.length === 0) {
            tbody.innerHTML = '';
            emptyDiv.classList.add('show');
            return;
        }
        
        emptyDiv.classList.remove('show');
        
        const html = records.map((record, index) => {
            const statusClass = `history-status-${record.status}`;
            const statusText = this.getHistoryStatusText(record.status);
            const statusIcon = this.getHistoryStatusIcon(record.status);
            
            return `
                <tr>
                    <td>${index + 1}</td>
                    <td class="file-title">${this.escapeHtml(record.filename)}</td>
                    <td>${record.transcribe_time || '-'}</td>
                    <td>
                        <span class="history-status-badge ${statusClass}">
                            ${statusIcon} ${statusText}
                        </span>
                    </td>
                    <td class="text-center">
                        ${record.status === 'completed' 
                            ? `<button class="btn-view-result" onclick="app.viewHistoryResult('${record.file_id}')">
                                   <i class="fas fa-eye"></i> 查看结果
                               </button>`
                            : `<span class="text-muted">-</span>`
                        }
                    </td>
                    <td class="history-actions">
                        <button class="action-delete-btn" 
                                onclick="app.deleteHistoryRecord('${record.file_id}')"
                                title="删除">
                            <i class="fas fa-trash"></i>
                        </button>
                        <button class="action-refresh-btn" 
                                onclick="app.refreshHistoryRecord('${record.file_id}')"
                                title="刷新">
                            <i class="fas fa-sync-alt"></i>
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
        
        tbody.innerHTML = html;
    }

    getHistoryStatusText(status) {
        const statusMap = {
            'completed': '已完成',
            'processing': '处理中',
            'error': '失败'
        };
        return statusMap[status] || status;
    }

    getHistoryStatusIcon(status) {
        const iconMap = {
            'completed': '<i class="fas fa-check-circle"></i>',
            'processing': '<i class="fas fa-spinner fa-spin"></i>',
            'error': '<i class="fas fa-times-circle"></i>'
        };
        return iconMap[status] || '';
    }

    viewHistoryResult(fileId) {
        // 关闭历史记录模态框
        this.closeHistoryModal();
        // 跳转到结果查看页面
        window.location.href = `/result.html?file_id=${fileId}`;
    }

    async deleteHistoryRecord(fileId) {
        if (!confirm('确定要删除这条历史记录吗？')) {
            return;
        }

        try {
            const response = await fetch(`/api/voice/files/${fileId}`, {
                method: 'DELETE'
            });
            const result = await response.json();
            
            if (result.success) {
                this.showSuccess('历史记录删除成功');
                await this.loadHistoryRecords();
            } else {
                this.showError(result.message || '删除失败');
            }
        } catch (error) {
            this.showError('删除失败: ' + error.message);
        }
    }

    async refreshHistoryRecord(fileId) {
        try {
            await this.loadHistoryRecords();
            this.showSuccess('刷新成功');
        } catch (error) {
            this.showError('刷新失败: ' + error.message);
        }
    }

    async clearDifyFiles() {
        if (!confirm('确定要清空dify生成文件吗？\n\n这将删除：\n- 所有dify生成的.zip文件\n- 对应的上传音频文件\n- 相关的转写文档')) {
            return;
        }

        try {
            const response = await fetch('/api/voice/files/_clear_dify', {
                method: 'DELETE'
            });
            const result = await response.json();
            
            if (result.success) {
                const deleted = result.deleted || {};
                const message = `清空dify生成文件成功！\n删除：${deleted.zip_files || 0} 个ZIP文件，${deleted.audio_files || 0} 个音频文件，${deleted.records || 0} 条历史记录`;
                this.showSuccess(message);
                await this.loadHistoryRecords();
                await this.loadUploadedFiles(); // 刷新主列表
            } else {
                this.showError(result.message || '清空失败');
            }
        } catch (error) {
            this.showError('清空失败: ' + error.message);
        }
    }

    async clearAllHistory() {
        if (!confirm('⚠️ 警告：确定要清空所有历史记录吗？\n\n这将删除：\n- 所有音频文件\n- 所有转写文档\n- 所有会议纪要\n- 所有输出文件（.zip、.docx等）\n\n此操作不可恢复！')) {
            return;
        }

        // 二次确认
        if (!confirm('⚠️ 最后确认：真的要清空所有历史记录吗？\n\n此操作将永久删除所有数据！')) {
            return;
        }

        try {
            const response = await fetch('/api/voice/files/_clear_all', {
                method: 'DELETE'
            });
            const result = await response.json();
            
            if (result.success) {
                const deleted = result.deleted || {};
                const message = `清空所有历史记录成功！\n删除：${deleted.audio_files || 0} 个音频文件，${deleted.transcript_files || 0} 个转写文档，${deleted.records || 0} 条历史记录`;
                this.showSuccess(message);
                await this.loadHistoryRecords();
                await this.loadUploadedFiles(); // 刷新主列表
            } else {
                this.showError(result.message || '清空失败');
            }
        } catch (error) {
            this.showError('清空失败: ' + error.message);
        }
    }

}

// 全局函数
function closeModal() {
    app.closeModal();
}

// 初始化应用
const app = new TranscriptionApp();
