class ResultViewer {
    constructor() {
        this.fileId = null;
        this.fileData = null;
        this.transcriptData = null;
        this.wordElements = null;  // 缓存词元素
        this.lastHighlightedWord = null;  // 上次高亮的词
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
        this.loadFileData();
    }

    bindEvents() {
        // 返回按钮
        document.getElementById('back-btn')?.addEventListener('click', () => this.goBack());
        
        // 下载按钮
        document.getElementById('download-transcript-btn')?.addEventListener('click', () => this.downloadTranscript());
        document.getElementById('download-audio-btn-menu')?.addEventListener('click', () => this.downloadAudio());
        
        // 复制按钮
        document.getElementById('copy-transcript-btn')?.addEventListener('click', () => this.copyTranscript());
        
        // 搜索按钮
        document.getElementById('search-btn')?.addEventListener('click', () => this.showSearchModal());
        
        // 搜索模态窗口
        const modal = document.getElementById('search-modal');
        const closeBtn = modal?.querySelector('.close-btn');
        closeBtn?.addEventListener('click', () => this.closeSearchModal());
        
        // 点击模态窗口外部关闭
        modal?.addEventListener('click', (e) => {
            if (e.target === modal) {
                this.closeSearchModal();
            }
        });
        
        // 搜索输入
        document.getElementById('search-input')?.addEventListener('input', (e) => {
            this.performSearch(e.target.value);
        });
        
        // 音频播放器事件
        const audioPlayer = document.getElementById('audio-player');
        audioPlayer?.addEventListener('loadedmetadata', () => this.updateAudioTime());
        audioPlayer?.addEventListener('timeupdate', () => this.updateCurrentTime());
        
        // 播放速度选择
        document.getElementById('speed-select')?.addEventListener('change', (e) => this.changePlaybackSpeed(e.target.value));
    }

    goBack() {
        window.location.href = '/';
    }

    async loadFileData() {
        try {
            const response = await fetch(`/api/voice/result/${this.fileId}`);
            const result = await response.json();
            
            if (result.success) {
                this.fileData = result.file_info;
                this.transcriptData = result.transcript;
                
                this.renderFileInfo();
                this.renderTranscript();
                // 延迟加载音频，确保词元素已缓存
                setTimeout(() => {
                    this.loadAudio();
                }, 100);
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

    renderFileInfo() {
        if (!this.fileData) return;
        
        document.getElementById('file-name').textContent = this.fileData.original_name || '-';
        document.getElementById('upload-time').textContent = this.fileData.upload_time || '-';
    }

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
        
        const html = this.transcriptData.map((entry, index) => {
            // 如果有词级别时间戳，使用词级别渲染
            if (entry.words && entry.words.length > 0) {
                // 验证：检查所有词的文本是否完整
                const reconstructedText = entry.words.map(w => w.text).join('');
                if (entry.text && reconstructedText !== entry.text) {
                    console.warn(`句子 ${index} 分词后文本不匹配:`, {
                        original: entry.text,
                        reconstructed: reconstructedText,
                        originalLength: entry.text.length,
                        reconstructedLength: reconstructedText.length
                    });
                }
                
                const wordsHtml = entry.words.map((word, wordIndex) => {
                    // 验证时间戳有效性
                    const start = parseFloat(word.start);
                    const end = parseFloat(word.end);
                    if (isNaN(start) || isNaN(end) || start < 0 || end < 0) {
                        console.warn(`词时间戳无效: ${word.text}, start: ${word.start}, end: ${word.end}`);
                    }
                    
                    return `<span class="word-item" 
                           data-start="${start}" 
                           data-end="${end}"
                           data-sentence-index="${index}"
                           data-word-index="${wordIndex}">${this.escapeHtml(word.text)}</span>`;
                }).join('');
                
                return `
                    <div class="transcript-entry" data-index="${index}" data-start-time="${entry.start_time || 0}">
                        <div class="speaker-info">
                            <span class="speaker-label">${this.escapeHtml(entry.speaker || '发言人')}</span>
                            <span class="timestamp">${this.formatTime(entry.start_time)} - ${this.formatTime(entry.end_time)}</span>
                        </div>
                        <div class="transcript-text">${wordsHtml}</div>
                    </div>
                `;
            } else {
                // 降级到句子级别渲染（兼容旧数据）
                return `
                    <div class="transcript-entry" data-index="${index}" data-start-time="${entry.start_time || 0}">
                        <div class="speaker-info">
                            <span class="speaker-label">${this.escapeHtml(entry.speaker || '发言人')}</span>
                            <span class="timestamp">${this.formatTime(entry.start_time)} - ${this.formatTime(entry.end_time)}</span>
                        </div>
                        <div class="transcript-text">${this.escapeHtml(entry.text || '')}</div>
                    </div>
                `;
            }
        }).join('');
        
        transcriptContent.innerHTML = html;
        
        // 为每个转写条目添加点击事件（句子级别）
        this.bindTranscriptClickEvents();
        
        // 延迟缓存词元素，确保DOM完全更新
        setTimeout(() => {
            // 缓存词元素（用于音字同步）
            this.wordElements = document.querySelectorAll('.word-item');
            console.log(`✅ 已缓存 ${this.wordElements.length} 个词元素用于音字同步`);
            
            // 验证词元素的时间戳
            if (this.wordElements && this.wordElements.length > 0) {
                let validCount = 0;
                this.wordElements.forEach((wordEl, index) => {
                    const start = parseFloat(wordEl.dataset.start);
                    const end = parseFloat(wordEl.dataset.end);
                    if (!isNaN(start) && !isNaN(end) && start >= 0 && end >= 0) {
                        validCount++;
                    }
                    
                    // 为词元素添加点击事件
                    wordEl.style.cursor = 'pointer';
                    wordEl.addEventListener('click', (e) => {
                        e.stopPropagation();  // 阻止事件冒泡到句子
                        const startTime = parseFloat(wordEl.dataset.start);
                        if (!isNaN(startTime)) {
                            this.seekToTime(startTime);
                        }
                    });
                    if (!isNaN(start)) {
                        wordEl.title = `点击跳转到 ${this.formatTime(start)}`;
                    }
                });
                console.log(`✅ 有效时间戳的词元素: ${validCount}/${this.wordElements.length}`);
            } else {
                console.warn('⚠️ 未找到词元素，音字同步功能可能无法正常工作');
            }
        }, 0);
    }
    
    bindTranscriptClickEvents() {
        const entries = document.querySelectorAll('.transcript-entry');
        entries.forEach(entry => {
            entry.style.cursor = 'pointer';
            entry.addEventListener('click', () => {
                const startTime = parseFloat(entry.dataset.startTime);
                if (!isNaN(startTime)) {
                    this.seekToTime(startTime);
                }
            });
            
            // 添加悬停效果提示
            entry.title = '点击跳转到该时间点播放';
        });
    }
    
    seekToTime(time) {
        const audioPlayer = document.getElementById('audio-player');
        if (!audioPlayer) return;
        
        // 设置音频播放位置
        audioPlayer.currentTime = time;
        
        // 立即更新高亮（因为timeupdate事件可能有延迟）
        this.highlightCurrentWord(time);
        
        // 如果音频未播放，则开始播放
        if (audioPlayer.paused) {
            audioPlayer.play().catch(err => {
                console.error('播放失败:', err);
            });
        }
        
        // 显示提示
        this.showSuccess(`已跳转到 ${this.formatTime(time)}`);
    }


    loadAudio() {
        if (!this.fileData) return;
        
        const audioSource = document.getElementById('audio-source');
        const audioPlayer = document.getElementById('audio-player');
        
        if (audioSource && audioPlayer) {
            audioSource.src = `/api/voice/audio/${this.fileId}`;
            audioPlayer.load();
        }
    }

    updateAudioTime() {
        const audioPlayer = document.getElementById('audio-player');
        const totalTime = document.getElementById('total-time');
        
        if (audioPlayer && totalTime) {
            totalTime.textContent = this.formatTime(audioPlayer.duration);
        }
    }

    updateCurrentTime() {
        const audioPlayer = document.getElementById('audio-player');
        
        if (!audioPlayer) {
            return;
        }
        
        const currentTimeValue = audioPlayer.currentTime;
        
        // 音字同步：高亮当前播放的词（不依赖current-time元素）
        this.highlightCurrentWord(currentTimeValue);
    }
    
    highlightCurrentWord(currentTime) {
        // 如果没有词元素，尝试重新获取
        if (!this.wordElements || this.wordElements.length === 0) {
            this.wordElements = document.querySelectorAll('.word-item');
            if (!this.wordElements || this.wordElements.length === 0) {
                return;
            }
        }
        
        // 验证当前时间有效性
        if (isNaN(currentTime) || currentTime < 0) {
            return;
        }
        
        // 查找当前时间对应的词
        let foundWord = null;
        let lastWordEl = null;  // 记录最后一个词元素
        
        for (let wordEl of this.wordElements) {
            const start = parseFloat(wordEl.dataset.start);
            const end = parseFloat(wordEl.dataset.end);
            
            // 验证时间戳有效性
            if (isNaN(start) || isNaN(end) || start < 0 || end < 0) {
                continue;
            }
            
            // 记录最后一个有效的词元素
            lastWordEl = wordEl;
            
            // 区间判断：当前时间是否在 [start, end) 范围内
            // 使用左闭右开区间 [start, end)，避免相邻词同时高亮
            if (currentTime >= start && currentTime < end) {
                foundWord = wordEl;
                break;
            }
        }
        
        // 如果没找到匹配的词，但当前时间在最后一个词的范围内，高亮最后一个词
        // 这确保音频播放到最后时也能高亮
        if (!foundWord && lastWordEl) {
            const lastStart = parseFloat(lastWordEl.dataset.start);
            const lastEnd = parseFloat(lastWordEl.dataset.end);
            if (!isNaN(lastStart) && !isNaN(lastEnd) && currentTime >= lastStart && currentTime <= lastEnd) {
                foundWord = lastWordEl;
            }
        }
        
        // 如果找到匹配的词且与上次不同，更新高亮
        if (foundWord && foundWord !== this.lastHighlightedWord) {
            // 移除所有旧的高亮（防止多个词同时高亮）
            if (this.lastHighlightedWord) {
                this.lastHighlightedWord.classList.remove('active');
            }
            
            // 添加新高亮
            foundWord.classList.add('active');
            this.lastHighlightedWord = foundWord;
            
            // 滚动到可见区域（使用平滑滚动，但降低频率避免过于频繁）
            // 只在必要时滚动（词不在可见区域时）
            const rect = foundWord.getBoundingClientRect();
            const isVisible = rect.top >= 0 && rect.bottom <= window.innerHeight;
            if (!isVisible) {
                foundWord.scrollIntoView({ 
                    behavior: 'smooth', 
                    block: 'center',
                    inline: 'nearest'
                });
            }
        } else if (!foundWord && this.lastHighlightedWord) {
            // 如果没有找到匹配的词（例如音频暂停或跳转），移除高亮
            this.lastHighlightedWord.classList.remove('active');
            this.lastHighlightedWord = null;
        }
    }

    async downloadTranscript() {
        try {
            // 直接下载文件
            window.location.href = `/api/voice/download_transcript/${this.fileId}`;
        } catch (error) {
            console.error('下载转写结果失败:', error);
            alert('下载失败');
        }
    }

    async downloadAudio() {
        try {
            // 直接下载音频文件
            window.location.href = `/api/audio/${this.fileId}?download=1`;
        } catch (error) {
            console.error('下载音频失败:', error);
            alert('下载失败');
        }
    }

    changePlaybackSpeed(speed) {
        const audioPlayer = document.getElementById('audio-player');
        if (audioPlayer) {
            audioPlayer.playbackRate = parseFloat(speed);
            this.showSuccess(`播放速度已设置为 ${speed}x`);
        }
    }


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


    copyToClipboard(text) {
        if (navigator.clipboard) {
            navigator.clipboard.writeText(text).then(() => {
                this.showSuccess('已复制到剪贴板');
            }).catch(err => {
                console.error('复制失败:', err);
                this.fallbackCopy(text);
            });
        } else {
            this.fallbackCopy(text);
        }
    }

    fallbackCopy(text) {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        
        try {
            document.execCommand('copy');
            this.showSuccess('已复制到剪贴板');
        } catch (err) {
            console.error('复制失败:', err);
            alert('复制失败');
        }
        
        document.body.removeChild(textarea);
    }

    showSearchModal() {
        const modal = document.getElementById('search-modal');
        if (modal) {
            modal.classList.add('show');
            document.getElementById('search-input')?.focus();
        }
    }

    closeSearchModal() {
        const modal = document.getElementById('search-modal');
        if (modal) {
            modal.classList.remove('show');
            document.getElementById('search-input').value = '';
            document.getElementById('search-results').innerHTML = '<p class="text-muted">输入关键词开始搜索</p>';
        }
    }

    performSearch(keyword) {
        const searchResults = document.getElementById('search-results');
        if (!searchResults) return;
        
        if (!keyword || keyword.trim() === '') {
            searchResults.innerHTML = '<p class="text-muted">输入关键词开始搜索</p>';
            return;
        }
        
        if (!this.transcriptData || this.transcriptData.length === 0) {
            searchResults.innerHTML = '<p class="text-muted">暂无转写结果</p>';
            return;
        }
        
        const results = this.transcriptData.filter(entry => 
            entry.text && entry.text.includes(keyword)
        );
        
        if (results.length === 0) {
            searchResults.innerHTML = '<p class="text-muted">未找到匹配结果</p>';
            return;
        }
        
        const html = results.map((entry, index) => {
            const highlightedText = entry.text.replace(
                new RegExp(this.escapeRegex(keyword), 'g'),
                match => `<mark>${match}</mark>`
            );
            
            return `
                <div class="search-result-item" onclick="resultViewer.scrollToEntry(${this.transcriptData.indexOf(entry)})">
                    <div class="speaker">${this.escapeHtml(entry.speaker || '发言人')} - ${this.formatTime(entry.start_time)}</div>
                    <div class="text">${highlightedText}</div>
                </div>
            `;
        }).join('');
        
        searchResults.innerHTML = html;
    }

    scrollToEntry(index) {
        this.closeSearchModal();
        
        const entry = document.querySelector(`.transcript-entry[data-index="${index}"]`);
        if (entry) {
            entry.scrollIntoView({ behavior: 'smooth', block: 'center' });
            entry.style.background = '#fef5e7';
            setTimeout(() => {
                entry.style.background = '';
            }, 2000);
        }
    }


    // 工具方法
    formatTime(seconds) {
        if (!seconds || isNaN(seconds)) return '00:00';
        
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    escapeRegex(string) {
        return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    showSuccess(message) {
        // 简单的成功提示
        const toast = document.createElement('div');
        toast.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: #48bb78;
            color: white;
            padding: 15px 25px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
            z-index: 10000;
            animation: slideIn 0.3s ease;
        `;
        toast.innerHTML = `<i class="fas fa-check-circle"></i> ${message}`;
        document.body.appendChild(toast);
        
        setTimeout(() => {
            toast.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => {
                document.body.removeChild(toast);
            }, 300);
        }, 2000);
    }
}

// 初始化
let resultViewer;
document.addEventListener('DOMContentLoaded', () => {
    resultViewer = new ResultViewer();
});

// 添加动画样式
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

