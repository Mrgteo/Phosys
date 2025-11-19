"""
Infra - ASR执行器（FunASR AutoModel版本）
使用FunASR的AutoModel实现ASR和说话人识别一体化
与demo.py保持一致
"""

import os
import logging
import torch
from typing import Optional, List, Dict

# 禁用FunASR的表单打印
os.environ['FUNASR_CACHE_DIR'] = os.path.expanduser('~/.cache/modelscope')
import warnings
warnings.filterwarnings('ignore')

from funasr import AutoModel

from .model_pool import ModelPool

logger = logging.getLogger(__name__)


class FunASRModelWrapper:
    """FunASR AutoModel包装器，用于池化管理"""
    
    def __init__(self, model_config: dict):
        logger.info("正在创建FunASR AutoModel实例...")
        
        # 检测设备和硬件资源（与demo.py一致）
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        ngpu = 1 if self.device == "cuda" else 0
        
        # 获取CPU核心数（限制最大值，避免超大服务器导致内存问题）
        try:
            import psutil
            ncpu = psutil.cpu_count()
        except:
            import multiprocessing
            ncpu = multiprocessing.cpu_count()
        
        # ⚠️ 限制CPU核心数，避免在大型服务器上分配过多内存
        # FunASR每个核心会分配一定内存，112核可能导致OOM
        ncpu = min(ncpu, 16)  # 最多使用16个核心
        
        logger.info(f"使用设备: {self.device}, GPU数: {ngpu}, CPU核心数: {ncpu}")
        
        # 创建AutoModel（集成ASR、VAD、PUNC、说话人识别）
        # 参数与demo.py完全一致
        self.model = AutoModel(
            model=model_config['asr']['model_id'],
            model_revision=model_config['asr']['model_revision'],
            vad_model=model_config['vad']['model_id'],
            vad_model_revision=model_config['vad']['model_revision'],
            punc_model=model_config['punc']['model_id'],
            punc_model_revision=model_config['punc']['model_revision'],
            spk_model=model_config['diarization']['model_id'],  # 说话人识别模型
            spk_model_revision=model_config['diarization']['revision'],
            ngpu=ngpu,  # GPU数量
            ncpu=ncpu,  # CPU核心数
            device=self.device,
            disable_pbar=True,
            disable_log=True,  # 禁用日志，防止打印表单
            disable_update=True
        )
        
        logger.info("FunASR AutoModel实例创建成功")
    
    def transcribe_with_speaker(self, audio_input, hotword: str = '') -> Dict:
        """
        执行ASR和说话人识别（一体化）
        
        Args:
            audio_input: 音频输入（字节流或文件路径）
            hotword: 热词
            
        Returns:
            包含文本和说话人信息的结果
        """
        try:
            # 准备generate参数
            generate_kwargs = {
                'input': audio_input,
                'use_itn': True,
                'batch_size_s': 60,
                'is_final': True,
                'sentence_timestamp': True
            }
            
            # 只有当hotword非空时才传递（避免空字符串被解析为['<s>']）
            if hotword and hotword.strip():
                generate_kwargs['hotword'] = hotword
            
            # 调用FunASR生成
            res = self.model.generate(**generate_kwargs)
            
            if not res or len(res) == 0:
                return None
            
            return res[0]  # 返回第一个结果
            
        except Exception as e:
            logger.error(f"FunASR转写失败: {e}")
            raise
    
    def cleanup(self):
        """清理模型资源"""
        try:
            if hasattr(self, 'model'):
                del self.model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception as e:
            logger.error(f"清理FunASR模型资源失败: {e}")


class ASRRunner:
    """ASR执行器 - 使用FunASR AutoModel（支持模型池）"""
    
    def __init__(self, model_config: dict, use_pool: bool = True, pool_size: int = 3):
        """
        初始化ASR运行器（FunASR方式）
        
        Args:
            model_config: 模型配置
            use_pool: 是否使用模型池（生产环境推荐开启）
            pool_size: 模型池大小
        """
        self.model_config = model_config
        self.use_pool = use_pool
        
        if use_pool:
            logger.info(f"使用FunASR AutoModel + 模型池模式，池大小: {pool_size}")
            # 创建模型工厂函数
            def funasr_factory():
                return FunASRModelWrapper(model_config)
            
            # 创建模型池
            self.model_pool = ModelPool(
                model_factory=funasr_factory,
                initial_size=min(pool_size, 2),  # 初始创建较少实例
                max_size=pool_size,
                min_size=1,
                max_idle_time=600,  # 10分钟
                health_check_interval=300  # 5分钟，降低日志频率
            )
            self.model = None
        else:
            logger.info("使用FunASR AutoModel单例模式")
            self.model_pool = None
            self.model = FunASRModelWrapper(model_config)
    
    def transcribe_with_speaker(self, audio_input, hotword: str = '') -> Optional[List[Dict]]:
        """
        执行语音识别和说话人识别（FunASR一体化方式）
        
        Args:
            audio_input: 音频输入（字节流bytes或文件路径str）
            hotword: 热词
            
        Returns:
            List[Dict]: 转写结果列表，每项包含：
                - text: 文本内容
                - start: 开始时间(毫秒)
                - end: 结束时间(毫秒)
                - spk: 说话人ID
        """
        try:
            input_type = "字节流" if isinstance(audio_input, bytes) else "文件"
            logger.info(f"🎙️ 开始FunASR一体化转写 (输入类型: {input_type})")
            if hotword and hotword.strip():
                logger.info(f"📝 使用热词: {hotword}")
            else:
                logger.info("📝 无热词")
            
            # 根据模式选择执行方式
            if self.use_pool and self.model_pool:
                # 使用模型池
                logger.info("⏳ 正在从模型池获取模型实例...")
                with self.model_pool.acquire(timeout=60.0) as model:
                    logger.info("✅ 模型获取成功，开始转录...")
                    result = model.transcribe_with_speaker(audio_input, hotword)
            else:
                # 使用单例模型
                logger.info("🔄 使用单例模型进行转录...")
                result = self.model.transcribe_with_speaker(audio_input, hotword)
            
            if not result:
                logger.warning("⚠️ FunASR返回空结果")
                return None
            
            # 解析FunASR结果格式
            transcript_list = []
            
            if 'sentence_info' in result:
                # 有说话人信息的结果
                sentence_count = len(result['sentence_info'])
                
                # 创建说话人ID映射表（按出现顺序重新编号）
                speaker_id_map = {}  # 原始spk -> 连续编号
                next_speaker_number = 1
                
                for sentence in result['sentence_info']:
                    original_spk = sentence.get('spk', 0)
                    
                    # 第一次遇到这个说话人时，分配新的连续编号
                    if original_spk not in speaker_id_map:
                        speaker_id_map[original_spk] = next_speaker_number
                        next_speaker_number += 1
                    
                    # 使用映射后的连续编号
                    speaker_number = speaker_id_map[original_spk]
                    
                    transcript_list.append({
                        'text': sentence.get('text', ''),
                        'start_time': sentence.get('start', 0) / 1000.0,  # 转为秒
                        'end_time': sentence.get('end', 0) / 1000.0,
                        'speaker': f"发言人{speaker_number}"  # 使用连续编号
                    })
                
                logger.info(f"✅ 识别完成: 共{sentence_count}个句子, {len(speaker_id_map)}位说话人")
            elif 'text' in result:
                # 只有文本，没有说话人信息
                logger.warning("⚠️ 结果中无说话人信息，作为单人处理")
                transcript_list.append({
                    'text': result['text'],
                    'start_time': 0,
                    'end_time': 0,
                    'speaker': '发言人1'  # 单人时默认为发言人1
                })
            
            return transcript_list
            
        except Exception as e:
            logger.error(f"❌ FunASR转写失败: {e}")
            raise
    
    def get_pool_stats(self) -> Optional[dict]:
        """获取模型池统计信息"""
        if self.use_pool and self.model_pool:
            return self.model_pool.get_stats()
        return None
    
    def shutdown(self):
        """关闭运行器，清理资源"""
        if self.use_pool and self.model_pool:
            self.model_pool.shutdown()
        elif self.model:
            self.model.cleanup()

