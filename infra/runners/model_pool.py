"""
模型池管理器 - 生产级并发优化
支持多个模型实例的对象池模式，解决全局锁导致的并发瓶颈
"""

import logging
import threading
import queue
import time
from typing import Optional, Callable, Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class ModelPool:
    """
    模型对象池
    
    特性:
    1. 支持动态扩展和收缩
    2. 自动健康检查
    3. 失败重试机制
    4. 负载均衡
    """
    
    def __init__(self, 
                 model_factory: Callable,
                 initial_size: int = 2,
                 max_size: int = 5,
                 min_size: int = 1,
                 max_idle_time: int = 300,  # 最大空闲时间(秒)
                 health_check_interval: int = 60):  # 健康检查间隔(秒)
        """
        初始化模型池
        
        Args:
            model_factory: 模型创建工厂函数
            initial_size: 初始池大小
            max_size: 最大池大小
            min_size: 最小池大小
            max_idle_time: 模型最大空闲时间
            health_check_interval: 健康检查间隔
        """
        self.model_factory = model_factory
        self.initial_size = initial_size
        self.max_size = max_size
        self.min_size = min_size
        self.max_idle_time = max_idle_time
        self.health_check_interval = health_check_interval
        
        # 可用模型队列
        self.available_models: queue.Queue = queue.Queue(maxsize=max_size)
        
        # 当前池大小
        self.current_size = 0
        self.size_lock = threading.Lock()
        
        # 统计信息
        self.stats = {
            'total_acquired': 0,
            'total_released': 0,
            'total_created': 0,
            'total_destroyed': 0,
            'acquisition_times': [],
            'active_count': 0
        }
        self.stats_lock = threading.Lock()
        
        # 模型最后使用时间
        self.model_last_used = {}
        self.last_used_lock = threading.Lock()
        
        # 初始化池
        self._initialize_pool()
        
        # 启动健康检查线程
        self.health_check_thread = threading.Thread(
            target=self._health_check_loop,
            daemon=True,
            name='ModelPool-HealthCheck'
        )
        self.health_check_thread.start()
        
        logger.info(f"模型池已初始化: initial_size={initial_size}, max_size={max_size}")
    
    def _initialize_pool(self):
        """初始化池，创建初始模型实例"""
        for i in range(self.initial_size):
            try:
                model = self._create_model()
                self.available_models.put(model)
                logger.info(f"初始化模型实例 {i+1}/{self.initial_size}")
            except Exception as e:
                logger.error(f"初始化模型失败: {e}")
    
    def _create_model(self) -> Any:
        """创建新模型实例"""
        with self.size_lock:
            if self.current_size >= self.max_size:
                raise RuntimeError(f"模型池已达到最大容量: {self.max_size}")
            
            model = self.model_factory()
            model_id = id(model)
            self.current_size += 1
            
            with self.stats_lock:
                self.stats['total_created'] += 1
            
            with self.last_used_lock:
                self.model_last_used[model_id] = time.time()
            
            logger.info(f"创建新模型实例, 当前池大小: {self.current_size}/{self.max_size}")
            return model
    
    def _destroy_model(self, model: Any):
        """销毁模型实例"""
        with self.size_lock:
            model_id = id(model)
            
            # 移除最后使用时间记录
            with self.last_used_lock:
                self.model_last_used.pop(model_id, None)
            
            # 清理模型资源
            try:
                if hasattr(model, 'cleanup'):
                    model.cleanup()
                del model
            except Exception as e:
                logger.error(f"销毁模型时出错: {e}")
            
            self.current_size -= 1
            
            with self.stats_lock:
                self.stats['total_destroyed'] += 1
            
            logger.info(f"销毁模型实例, 当前池大小: {self.current_size}/{self.max_size}")
    
    @contextmanager
    def acquire(self, timeout: float = 30.0):
        """
        获取模型实例（上下文管理器）
        
        Args:
            timeout: 获取超时时间(秒)
            
        Yields:
            模型实例
        """
        start_time = time.time()
        model = None
        
        try:
            # 尝试从队列获取模型
            try:
                model = self.available_models.get(timeout=timeout)
            except queue.Empty:
                # 队列为空，尝试创建新模型
                logger.warning("模型池无可用实例，尝试创建新实例...")
                try:
                    model = self._create_model()
                except RuntimeError as e:
                    # 达到最大容量，等待可用模型
                    logger.error(f"无法创建新模型: {e}，继续等待...")
                    model = self.available_models.get(timeout=timeout)
            
            acquisition_time = time.time() - start_time
            
            with self.stats_lock:
                self.stats['total_acquired'] += 1
                self.stats['acquisition_times'].append(acquisition_time)
                self.stats['active_count'] += 1
                # 只保留最近100次的获取时间
                if len(self.stats['acquisition_times']) > 100:
                    self.stats['acquisition_times'].pop(0)
            
            if acquisition_time > 1.0:
                logger.warning(f"获取模型耗时较长: {acquisition_time:.2f}秒")
            
            # 更新最后使用时间
            with self.last_used_lock:
                self.model_last_used[id(model)] = time.time()
            
            yield model
            
        finally:
            # 归还模型到池中
            if model is not None:
                try:
                    # 更新最后使用时间
                    with self.last_used_lock:
                        self.model_last_used[id(model)] = time.time()
                    
                    self.available_models.put_nowait(model)
                    
                    with self.stats_lock:
                        self.stats['total_released'] += 1
                        self.stats['active_count'] -= 1
                        
                except queue.Full:
                    # 队列已满，销毁模型
                    logger.warning("模型池已满，销毁多余模型")
                    self._destroy_model(model)
    
    def _health_check_loop(self):
        """健康检查循环（后台线程）"""
        while True:
            try:
                time.sleep(self.health_check_interval)
                self._perform_health_check()
            except Exception as e:
                logger.error(f"健康检查异常: {e}")
    
    def _perform_health_check(self):
        """执行健康检查"""
        current_time = time.time()
        
        # 检查空闲模型
        with self.last_used_lock:
            idle_models = []
            for model_id, last_used in list(self.model_last_used.items()):
                idle_time = current_time - last_used
                if idle_time > self.max_idle_time:
                    idle_models.append(model_id)
        
        # 移除空闲时间过长的模型（但保持最小池大小）
        if idle_models and self.current_size > self.min_size:
            logger.info(f"发现 {len(idle_models)} 个空闲模型，当前池大小: {self.current_size}")
            
            # 尝试从队列中移除并销毁空闲模型
            models_to_destroy = []
            for _ in range(min(len(idle_models), self.current_size - self.min_size)):
                try:
                    model = self.available_models.get_nowait()
                    if id(model) in idle_models:
                        models_to_destroy.append(model)
                    else:
                        # 不是空闲模型，放回队列
                        self.available_models.put_nowait(model)
                except queue.Empty:
                    break
            
            for model in models_to_destroy:
                self._destroy_model(model)
        
        # 记录统计信息
        with self.stats_lock:
            avg_acquisition_time = (
                sum(self.stats['acquisition_times']) / len(self.stats['acquisition_times'])
                if self.stats['acquisition_times'] else 0
            )
            logger.info(
                f"模型池状态: "
                f"当前大小={self.current_size}, "
                f"活跃数={self.stats['active_count']}, "
                f"总创建={self.stats['total_created']}, "
                f"总销毁={self.stats['total_destroyed']}, "
                f"平均获取时间={avg_acquisition_time:.3f}秒"
            )
    
    def get_stats(self) -> dict:
        """获取池统计信息"""
        with self.stats_lock:
            stats = self.stats.copy()
            if stats['acquisition_times']:
                stats['avg_acquisition_time'] = sum(stats['acquisition_times']) / len(stats['acquisition_times'])
                stats['max_acquisition_time'] = max(stats['acquisition_times'])
            else:
                stats['avg_acquisition_time'] = 0
                stats['max_acquisition_time'] = 0
            del stats['acquisition_times']  # 不返回原始列表
        
        stats['current_size'] = self.current_size
        stats['available_count'] = self.available_models.qsize()
        return stats
    
    def shutdown(self):
        """关闭模型池，清理所有资源"""
        logger.info("正在关闭模型池...")
        
        # 清空队列中的所有模型
        while not self.available_models.empty():
            try:
                model = self.available_models.get_nowait()
                self._destroy_model(model)
            except queue.Empty:
                break
        
        logger.info("模型池已关闭")


class ASRModelWrapper:
    """ASR模型包装器，用于池化管理"""
    
    def __init__(self, model_config: dict):
        from modelscope.pipelines import pipeline
        
        logger.info("正在创建ASR模型实例...")
        
        self.pipeline = pipeline(
            task='auto-speech-recognition',
            model=model_config['asr']['model_id'],
            model_revision=model_config['asr']['model_revision'],
            vad_model=model_config['vad']['model_id'],
            vad_model_revision=model_config['vad']['model_revision'],
            punc_model=model_config['punc']['model_id'],
            punc_model_revision=model_config['punc']['model_revision']
        )
        
        logger.info("ASR模型实例创建成功")
    
    def transcribe(self, audio_path: str, hotword: str = '') -> str:
        """执行语音识别"""
        if hotword:
            result = self.pipeline(input=audio_path, hotword=hotword)
        else:
            result = self.pipeline(input=audio_path)
        
        # 解析结果
        if isinstance(result, list) and result:
            return "".join([item['text'] for item in result])
        elif isinstance(result, dict) and 'text' in result:
            return result['text']
        else:
            return "[未识别到语音]"
    
    def cleanup(self):
        """清理模型资源"""
        try:
            if hasattr(self.pipeline, 'model'):
                del self.pipeline.model
            del self.pipeline
        except Exception as e:
            logger.error(f"清理ASR模型资源失败: {e}")


class DiarizationModelWrapper:
    """声纹分离模型包装器，用于池化管理"""
    
    def __init__(self, model_config: dict):
        from modelscope.pipelines import pipeline
        
        logger.info("正在创建声纹分离模型实例...")
        
        self.pipeline = pipeline(
            task='speaker-diarization',
            model=model_config['diarization']['model_id'],
            model_revision=model_config['diarization']['revision']
        )
        
        logger.info("声纹分离模型实例创建成功")
    
    def run(self, wav_path: str) -> list:
        """执行声纹分离"""
        result = self.pipeline(
            wav_path,
            max_speakers=10,
            min_speakers=1,
            threshold=0.5
        )
        
        return result.get('text', [])
    
    def cleanup(self):
        """清理模型资源"""
        try:
            if hasattr(self.pipeline, 'model'):
                del self.pipeline.model
            del self.pipeline
        except Exception as e:
            logger.error(f"清理声纹分离模型资源失败: {e}")

