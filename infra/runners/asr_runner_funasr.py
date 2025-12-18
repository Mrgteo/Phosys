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
                    
                    text = sentence.get('text', '')
                    start_time = sentence.get('start', 0) / 1000.0  # 转为秒
                    end_time = sentence.get('end', 0) / 1000.0
                    
                    # 提取词级别时间戳
                    words = self._extract_word_timestamps(sentence, start_time, end_time, text)
                    
                    transcript_list.append({
                        'text': text,
                        'start_time': start_time,
                        'end_time': end_time,
                        'speaker': f"发言人{speaker_number}",  # 使用连续编号
                        'words': words  # 词级别时间戳
                    })
                
                logger.info(f"✅ 识别完成: 共{sentence_count}个句子, {len(speaker_id_map)}位说话人")
            elif 'text' in result:
                # 只有文本，没有说话人信息
                logger.warning("⚠️ 结果中无说话人信息，作为单人处理")
                text = result['text']
                words = self._extract_word_timestamps(None, 0, 0, text)
                transcript_list.append({
                    'text': text,
                    'start_time': 0,
                    'end_time': 0,
                    'speaker': '发言人1',  # 单人时默认为发言人1
                    'words': words
                })
            
            return transcript_list
            
        except Exception as e:
            logger.error(f"❌ FunASR转写失败: {e}")
            raise
    
    def _extract_word_timestamps(self, sentence: Dict, start_time: float, end_time: float, text: str) -> List[Dict]:
        """
        提取词级别时间戳
        
        Args:
            sentence: FunASR句子信息（可能包含词级别时间戳）
            start_time: 句子开始时间（秒）
            end_time: 句子结束时间（秒）
            text: 句子文本
            
        Returns:
            List[Dict]: 词级别时间戳列表，每项包含 {'text': str, 'start': float, 'end': float}
        """
        words = []
        
        # 方法1: 尝试从FunASR结果中提取词级别时间戳
        if sentence and 'words' in sentence:
            # FunASR可能提供词级别时间戳
            for word_info in sentence['words']:
                word_text = word_info.get('text', '')
                word_start = word_info.get('start', 0) / 1000.0  # 转为秒
                word_end = word_info.get('end', 0) / 1000.0
                if word_text:
                    words.append({
                        'text': word_text,
                        'start': word_start,
                        'end': word_end
                    })
            if words:
                logger.debug(f"✅ 从FunASR结果中提取到 {len(words)} 个词级别时间戳")
                return words
        
        # 方法2: 如果没有词级别时间戳，使用分词+线性插值
        if not text or not text.strip():
            return words
        
        try:
            import jieba
            import re
            
            # 使用jieba进行中文分词，保留所有字符（包括标点和空格）
            # 先分词，然后按原始文本顺序重建
            word_segments = list(jieba.cut(text, cut_all=False))
            
            # 移除空字符串，但保留其他字符（包括标点）
            word_list = [w for w in word_segments if w]
            
            if not word_list:
                return words
            
            # 计算每个词的时间戳（线性插值）
            duration = end_time - start_time
            if duration <= 0:
                # 如果时间戳无效，给每个词分配相同的时间
                duration = len(word_list) * 0.3  # 假设每个词0.3秒
                end_time = start_time + duration
            
            # 计算总字符数（用于按比例分配时间）
            total_chars = sum(len(w) for w in word_list)
            if total_chars == 0:
                return words
            
            current_time = start_time
            for word in word_list:
                # 根据字符数比例分配时间
                word_duration = (len(word) / total_chars) * duration
                word_start = current_time
                word_end = current_time + word_duration
                
                words.append({
                    'text': word,
                    'start': word_start,
                    'end': word_end
                })
                
                current_time = word_end
            
            # 确保最后一个词的结束时间等于句子结束时间
            if words:
                words[-1]['end'] = end_time
            
            # 验证：确保所有词的文本加起来等于原文本（去除空格比较）
            reconstructed_text = ''.join([w['text'] for w in words])
            if reconstructed_text.replace(' ', '') != text.replace(' ', ''):
                logger.warning(f"⚠️ 分词后文本不匹配，原文本长度: {len(text)}, 重建长度: {len(reconstructed_text)}")
            
            logger.debug(f"✅ 使用分词+插值生成 {len(words)} 个词级别时间戳")
            
        except Exception as e:
            logger.warning(f"⚠️ 词级别时间戳提取失败: {e}，将使用句子级别时间戳")
            # 如果分词失败，至少返回一个包含整个句子的词
            if text.strip():
                words.append({
                    'text': text.strip(),
                    'start': start_time,
                    'end': end_time
                })
        
        return words
    
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

