"""
Domain - 声纹分离领域逻辑
负责声纹分离相关的业务规则和后处理
"""

from typing import List, Tuple, Dict


class DiarizationProcessor:
    """声纹分离处理器 - 纯领域逻辑"""
    
    def post_process_diarization(self, raw_segments: List) -> List:
        """
        后处理声纹分离结果,提升准确性:
        1. 过滤过短的片段
        2. 合并过近的同一发言人片段
        3. 调整边界时间
        """
        if not raw_segments:
            return []
        
        # 过滤过短的片段
        min_duration = 0.5  # 最小片段长度(秒)
        filtered_segments = []
        
        for segment in raw_segments:
            start_s, end_s, speaker_id = segment
            duration = end_s - start_s
            
            if duration >= min_duration:
                filtered_segments.append(segment)
        
        # 合并过近的同一发言人片段
        merged_segments = self.merge_nearby_segments(filtered_segments)
        
        return merged_segments
    
    def merge_nearby_segments(self, segments: List) -> List:
        """
        合并过近的同一发言人片段,减少碎片化
        如果同一发言人的两个片段间隔小于0.3秒,则合并
        """
        if not segments:
            return []
        
        merged = []
        current_segment = list(segments[0])
        
        for i in range(1, len(segments)):
            next_segment = segments[i]
            
            # 检查是否是同一发言人且间隔很短
            if (next_segment[2] == current_segment[2] and 
                next_segment[0] - current_segment[1] <= 0.3):
                # 合并片段
                current_segment[1] = next_segment[1]
            else:
                # 保存当前片段,开始新片段
                merged.append(tuple(current_segment))
                current_segment = list(next_segment)
        
        # 添加最后一个片段
        merged.append(tuple(current_segment))
        
        return merged
    
    def merge_consecutive_segments(self, transcript_data: List[Dict]) -> List[Dict]:
        """合并属于同一个发言人的连续语音片段"""
        if not transcript_data:
            return []
        
        merged_transcript = []
        current_segment = dict(transcript_data[0])
        
        for i in range(1, len(transcript_data)):
            next_segment = transcript_data[i]
            
            # 检查是否是同一个发言人
            if next_segment['speaker'] == current_segment['speaker']:
                # 合并文本并更新结束时间
                current_segment['text'] += next_segment['text']
                current_segment['end_time'] = next_segment['end_time']
            else:
                # 发言人变了,保存当前片段
                merged_transcript.append(current_segment)
                current_segment = dict(next_segment)
        
        # 添加最后一个片段
        merged_transcript.append(current_segment)
        
        return merged_transcript

