# config.py

"""
实时语音转录与声纹分离项目 配置文件
"""

# 1. 文件与目录配置
FILE_CONFIG = {
    "output_dir": "transcripts",  # 保存最终文本稿的目录
    "temp_dir": "audio_temp",  # 存放临时音频文件的目录
    "upload_dir": "uploads"  # 存放上传文件的目录
}

# 2. 模型配置
MODEL_CONFIG = {
    # 说话人识别模型（FunASR AutoModel集成方式）
    # 使用speech_eres2net_sv模型，基于ERes2Net架构
    # 集成在ASR中实现说话人识别，与demo.py使用的方式一致
    "diarization": {
        "model_id": 'iic/speech_campplus_sv_zh-cn_16k-common',  # ERes2Net说话人识别模型（去掉v2）
        "revision": 'v2.0.2'  # 模型版本
        # 注：该模型采用ERes2Net架构，性能优秀
    },

    # 语音转文本（ASR）模型 - SeACo-Paraformer 支持热词定制
    # SeACo-Paraformer是新一代热词定制化非自回归语音识别模型
    # 需要配合VAD和PUNC模型使用才能获得带标点的完整输出
    "asr": {
        "model_id": 'iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch',
        "model_revision": 'v2.0.4'
    },
    
    # VAD（语音端点检测）模型
    # 用于检测语音的起止点，提升识别准确率
    "vad": {
        "model_id": 'iic/speech_fsmn_vad_zh-cn-16k-common-pytorch',
        "model_revision": 'v2.0.4'
    },
    
    # PUNC（标点恢复）模型
    # 为识别结果添加标点符号，并去除多余空格
    "punc": {
        "model_id": 'iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch',
        "model_revision": 'v2.0.4'
    },
    
    # 热词配置（可选）
    # SeACo-Paraformer支持热词定制，可以提升特定词汇的识别准确率
    # 格式：空格分隔的热词列表，例如：'达摩院 魔搭 阿里巴巴'
    "hotword": ''  # 留空表示不使用热词，使用时填入热词，如：'人工智能 深度学习'
}

# 3. 语言配置
LANGUAGE_CONFIG = {
    "zh": {
        "name": "中文普通话",
        "description": "适用于标准普通话音频",
        "model_params": {}
    },
    "zh-dialect": {
        "name": "方言混合",
        "description": "适用于包含方言(如粤语、闽南语等)的音频",
        "model_params": {}
    },
    "zh-en": {
        "name": "中英混合",
        "description": "适用于中英文混合的音频",
        "model_params": {}
    },
    "en": {
        "name": "英文",
        "description": "适用于纯英文音频",
        "model_params": {}
    }
}

# 4. 音频处理配置
# ModelScope的语音模型通常要求音频为16kHz采样率的单声道WAV格式
AUDIO_PROCESS_CONFIG = {
    "sample_rate": 16000,
    "channels": 1
}

# 5. 并发与性能配置（生产级优化）
CONCURRENCY_CONFIG = {
    # 模型池配置
    "use_model_pool": True,   # ✅ 启用模型池，支持并发处理
    "asr_pool_size": 6,       # ASR模型池大小（6个实例，平衡性能与内存）
    "diarization_pool_size": 0,  # FunASR一体化模式不需要单独的声纹分离池
    
    # 线程池配置
    "transcription_workers": 12,  # 转写任务并发数（支持12个音频同时处理）
    "max_queue_size": 100,   # 任务队列最大长度
    
    # 内存限制
    "max_memory_mb": 8192,   # 最大内存使用(MB)，超过此值将拒绝新任务
    "memory_check_interval": 30,  # 内存检查间隔(秒)
    
    # 超时配置
    "task_timeout": 3600,    # 单个任务最大执行时间(秒)
    "model_acquire_timeout": 60,  # 获取模型超时时间(秒)
    
    # 限流配置
    "rate_limit": {
        "enabled": True,
        "requests_per_minute": 36,  # 每分钟最大请求数（配合12并发）
        "requests_per_hour": 240    # 每小时最大请求数（配合12并发）
    }
}

