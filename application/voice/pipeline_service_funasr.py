"""
Application - 流水线服务（FunASR版本）
使用FunASR AutoModel实现ASR和说话人识别一体化
简化流程，提升性能
"""

import os
import logging
import threading
import time
from datetime import datetime
from typing import List, Dict, Optional, Callable

from domain.voice.audio_processor import AudioProcessor
from domain.voice.text_processor import TextProcessor
from domain.voice.diarization import DiarizationProcessor

from infra.audio_io.storage import AudioStorage
from infra.runners.asr_runner_funasr import ASRRunner

logger = logging.getLogger(__name__)


class ProgressSmoother:
    """进度平滑器 - 用于在长时间运行的步骤中平滑更新进度"""
    
    def __init__(self, callback: Callable, start_progress: int, end_progress: int, 
                 estimated_duration: float = None, update_interval: float = 0.5):
        """
        初始化进度平滑器
        
        Args:
            callback: 进度回调函数
            start_progress: 起始进度值
            end_progress: 目标进度值
            estimated_duration: 预估耗时（秒），如果为None则基于时间自动估算
            update_interval: 更新间隔（秒）
        """
        self.callback = callback
        self.start_progress = start_progress
        self.end_progress = end_progress
        self.estimated_duration = estimated_duration
        self.update_interval = update_interval
        self.start_time = None
        self.stop_flag = threading.Event()
        self.thread = None
        self.current_step = ""
        self.current_message = ""
        self.last_progress = start_progress - 1  # 记录上一次的进度，确保只递增
    
    def start(self, step: str, message: str = ""):
        """启动平滑进度更新"""
        self.current_step = step
        self.current_message = message
        self.start_time = time.time()
        self.stop_flag.clear()
        self.last_progress = self.start_progress - 1  # 重置上次进度
        
        # 启动后台线程
        self.thread = threading.Thread(target=self._smooth_progress, daemon=True)
        self.thread.start()
    
    def stop(self):
        """停止平滑进度更新"""
        self.stop_flag.set()
        if self.thread:
            self.thread.join(timeout=1.0)
    
    def _smooth_progress(self):
        """平滑更新进度的后台线程"""
        progress_range = self.end_progress - self.start_progress
        
        while not self.stop_flag.is_set():
            elapsed = time.time() - self.start_time
            
            # 如果提供了预估耗时，基于预估时间计算进度
            if self.estimated_duration and self.estimated_duration > 0:
                # 基于预估时间计算进度（最多到 end_progress - 1，留1%给完成时更新）
                ratio = min(elapsed / self.estimated_duration, 0.99)
                current_progress = int(self.start_progress + progress_range * ratio)
            else:
                # 如果没有预估时间，使用缓慢递增的方式
                # 根据更新间隔计算增量，确保平滑推进
                increment_per_second = progress_range / max(self.estimated_duration or 10.0, 1.0)
                increment = int(elapsed * increment_per_second)
                current_progress = min(self.start_progress + increment, self.end_progress - 1)
            
            # 确保进度在合理范围内
            current_progress = max(self.start_progress, min(current_progress, self.end_progress - 1))
            
            # 只有当进度真正增加时才调用回调（避免重复更新）
            if current_progress > self.last_progress:
                self.last_progress = current_progress
                if self.callback:
                    self.callback(self.current_step, current_progress, self.current_message)
            
            # 等待更新间隔
            time.sleep(self.update_interval)
            
            # 如果已经达到目标进度，退出
            if current_progress >= self.end_progress - 1:
                break


class PipelineService:
    """流水线服务 - FunASR一体化转写"""
    
    def __init__(self, 
                 audio_storage: AudioStorage,
                 asr_runner: ASRRunner,
                 audio_config: dict):
        
        # Infra依赖
        self.storage = audio_storage
        self.asr_runner = asr_runner
        
        # Domain对象（启用GPU加速）
        self.audio_processor = AudioProcessor(
            sample_rate=audio_config.get('sample_rate', 16000),
            use_gpu_accel=True  # 启用GPU硬件加速
        )
        self.text_processor = TextProcessor()
        self.diarization_processor = DiarizationProcessor()
        
        # 回调函数
        self.callback: Optional[Callable] = None
        # 当前活动的进度平滑器
        self.current_smoother: Optional[ProgressSmoother] = None
    
    def set_callback(self, callback: Callable):
        """设置进度回调"""
        self.callback = callback
    
    def _stop_smoother(self):
        """停止当前的进度平滑器"""
        if self.current_smoother:
            self.current_smoother.stop()
            self.current_smoother = None
    
    def _update_status(self, step: str, progress: int, message: str = "", data: Dict = None):
        """更新状态（同时在终端显示进度）"""
        # 在终端打印进度条（实时更新同一行）
        progress_bar = "█" * (progress // 5) + "░" * (20 - progress // 5)
        status_line = f"\r[{progress:3d}%] {progress_bar} | {step}: {message}"
        
        # 使用\r实现同行覆盖，完成时换行
        if progress >= 100:
            print(status_line)  # 完成时打印并换行
        else:
            print(status_line, end='', flush=True)  # 实时覆盖同一行
        
        # 调用WebSocket回调
        if self.callback:
            self.callback(step, progress, message, data)
    
    def execute_transcription(self, input_audio_path: str, 
                            hotword: str = '', 
                            language: str = 'zh',
                            instance_id: str = None,
                            cancellation_flag: Optional[Callable] = None) -> tuple:
        """
        执行完整的转写流程（FunASR一体化方式）
        
        Args:
            input_audio_path: 输入音频文件路径
            hotword: 热词
            language: 语言
            instance_id: 实例ID
            cancellation_flag: 可选的取消检查函数，返回True表示任务已被取消
            
        Returns:
            tuple: (转写结果, 文档文件名, 文档文件路径)
        """
        if not instance_id:
            import uuid
            instance_id = str(uuid.uuid4())[:8]
        
        def check_cancelled():
            """检查是否被取消"""
            if cancellation_flag and cancellation_flag():
                raise InterruptedError("转写任务已被取消")
        
        try:
            check_cancelled()
            self._update_status("开始", 0, "初始化转写任务...")
            start_time = datetime.now()
            
            # 步骤1: 准备音频为字节流（0% -> 10%）
            check_cancelled()
            # 启动平滑器：从0%平滑到10%，预估耗时2秒
            self._stop_smoother()  # 确保没有残留的平滑器
            smoother = ProgressSmoother(
                callback=lambda step, progress, msg: self._update_status(step, progress, msg),
                start_progress=0,
                end_progress=10,
                estimated_duration=2.0,
                update_interval=0.3  # 每0.3秒更新一次
            )
            self.current_smoother = smoother
            smoother.start("准备音频", "正在处理音频文件...")
            
            audio_bytes, duration = self.audio_processor.prepare_audio_bytes(input_audio_path)
            
            if audio_bytes is None:
                logger.error("音频准备失败")
                self._stop_smoother()
                return None, None, None
            
            check_cancelled()
            self._stop_smoother()
            self._update_status("准备音频", 10, "音频处理完成")
            
            # 步骤2: 音频处理完成提示（10% -> 30%）
            check_cancelled()
            smoother = ProgressSmoother(
                callback=lambda step, progress, msg: self._update_status(step, progress, msg),
                start_progress=10,
                end_progress=30,
                estimated_duration=1.0,
                update_interval=0.2
            )
            self.current_smoother = smoother
            smoother.start("准备音频", "音频处理完成")
            time.sleep(0.5)  # 短暂延迟以显示进度
            self._stop_smoother()
            self._update_status("准备音频", 30, "音频处理完成")
            
            # 步骤3: FunASR一体化转写（30% -> 80%）
            # 这是最耗时的步骤，根据音频时长估算耗时
            check_cancelled()
            # 估算转写耗时：通常为音频时长的0.1-0.3倍（取决于硬件）
            estimated_transcribe_time = max(duration * 0.15, 5.0)  # 至少5秒，或音频时长的15%
            
            smoother = ProgressSmoother(
                callback=lambda step, progress, msg: self._update_status(step, progress, msg),
                start_progress=30,
                end_progress=80,
                estimated_duration=estimated_transcribe_time,
                update_interval=0.4  # 每0.4秒更新一次，确保连续推进
            )
            self.current_smoother = smoother
            smoother.start("语音转录", "正在进行语音识别和说话人识别...")
            
            transcript_list = self.asr_runner.transcribe_with_speaker(
                audio_bytes,  # 传入字节流
                hotword=hotword
            )
            
            check_cancelled()
            self._stop_smoother()
            
            if not transcript_list:
                logger.error("转录失败")
                return None, None, None
            
            logger.info(f"转录完成，共 {len(transcript_list)} 个句子")
            self._update_status("语音转录", 80, f"识别完成，共{len(transcript_list)}个句子")
            
            # 步骤4: 合并连续相同说话人的片段（80% -> 90%）
            check_cancelled()
            # 合并操作通常很快，但使用平滑器确保连续
            smoother = ProgressSmoother(
                callback=lambda step, progress, msg: self._update_status(step, progress, msg),
                start_progress=80,
                end_progress=90,
                estimated_duration=1.0,
                update_interval=0.2
            )
            self.current_smoother = smoother
            smoother.start("合并片段", "正在合并连续的发言片段...")
            
            merged_transcript = self.diarization_processor.merge_consecutive_segments(
                transcript_list
            )
            
            self._stop_smoother()
            logger.info(f"合并后剩余 {len(merged_transcript)} 个片段")
            self._update_status("合并片段", 90, f"合并完成，剩余{len(merged_transcript)}个片段")
            
            # 步骤5: 修复转写文本（90% -> 95%）
            check_cancelled()
            # 文本处理通常很快，但使用平滑器确保连续
            smoother = ProgressSmoother(
                callback=lambda step, progress, msg: self._update_status(step, progress, msg),
                start_progress=90,
                end_progress=95,
                estimated_duration=0.5,
                update_interval=0.1
            )
            self.current_smoother = smoother
            smoother.start("文本处理", "正在处理转写文本...")
            
            for entry in merged_transcript:
                check_cancelled()  # 在循环中检查
                if 'text' in entry:
                    entry['text'] = self.text_processor.fix_transcript_text(entry['text'])
            
            self._stop_smoother()
            self._update_status("文本处理", 95, "文本处理完成")
            
            # 步骤6: 清理临时文件（95% -> 100%）
            check_cancelled()
            smoother = ProgressSmoother(
                callback=lambda step, progress, msg: self._update_status(step, progress, msg),
                start_progress=95,
                end_progress=100,
                estimated_duration=0.5,
                update_interval=0.1
            )
            self.current_smoother = smoother
            smoother.start("完成", "正在完成转写...")
            
            self.storage.cleanup_temp_files(instance_id)
            
            self._stop_smoother()
            end_time = datetime.now()
            elapsed = (end_time - start_time).seconds
            self._update_status("完成", 100, f"转写完成，耗时{elapsed}秒")
            
            logger.info(f"✅ 转写完成! 耗时: {elapsed}秒")
            
            return merged_transcript, None, None
            
        except InterruptedError:
            # 任务被取消，重新抛出异常
            self._stop_smoother()
            logger.info(f"转写任务 {instance_id} 已被取消")
            self.storage.cleanup_temp_files(instance_id)
            raise
        except Exception as e:
            self._stop_smoother()
            logger.error(f"转写流程失败: {e}")
            import traceback
            traceback.print_exc()
            
            # 清理临时文件
            self.storage.cleanup_temp_files(instance_id)
            
            return None, None, None

