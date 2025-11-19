"""
Domain - 文本处理领域逻辑
负责热词处理、智能后处理、文本清理等纯业务规则
"""

import re
from typing import List, Dict, Set


class TextProcessor:
    """文本处理器 - 处理热词、智能后处理等"""
    
    def process_hotword(self, hotword: str) -> str:
        """智能处理热词,提升识别效果"""
        if not hotword or not hotword.strip():
            return ''
        
        hotwords = [word.strip() for word in hotword.split() if word.strip()]
        unique_hotwords = list(dict.fromkeys(hotwords))
        expanded_hotwords = self._expand_hotwords(unique_hotwords)
        
        return ' '.join(expanded_hotwords)
    
    def _expand_hotwords(self, hotwords: List[str]) -> List[str]:
        """扩展热词,添加相关词汇"""
        expanded = set(hotwords)
        
        synonym_map = {
            'AI': ['人工智能', '机器学习', '深度学习'],
            '人工智能': ['AI', '机器学习', '深度学习'],
            '会议': ['开会', '讨论', '商议'],
            '项目': ['工程', '任务', '计划'],
            '技术': ['科技', '工程', '研发'],
            '产品': ['商品', '服务', '方案'],
            '市场': ['销售', '营销', '推广'],
            '客户': ['用户', '消费者', '买家'],
            '团队': ['小组', '部门', '组织'],
            '预算': ['费用', '成本', '资金']
        }
        
        for word in hotwords:
            if word in synonym_map:
                expanded.update(synonym_map[word])
        
        return list(expanded)
    
    def intelligent_post_process(self, text: str, speaker_id: int, 
                                 speaker_context: Dict, full_transcript: List) -> str:
        """智能后处理,结合上下文提升内容逻辑性"""
        if not text or text == "[未识别到语音]":
            return text
        
        # 基础文本清理
        processed_text = self.clean_text(text)
        
        # 上下文一致性检查
        processed_text = self._check_context_consistency(
            processed_text, speaker_id, speaker_context, full_transcript
        )
        
        return processed_text
    
    def clean_text(self, text: str) -> str:
        """后处理识别文本,去除多余空格"""
        if not text or text == "[未识别到语音]":
            return text
        
        # 去除中文字符之间的空格
        text = re.sub(r'([\u4e00-\u9fff])\s+([\u4e00-\u9fff])', r'\1\2', text)
        
        # 去除多个连续空格
        text = re.sub(r'\s+', ' ', text)
        
        # 去除首尾空格
        text = text.strip()
        
        return text
    
    def fix_transcript_text(self, text: str) -> str:
        """
        修复转写文本，确保末尾不是逗号
        
        Args:
            text: 待处理的转写文本
            
        Returns:
            修复后的文本，确保末尾不是逗号等非句末标点
        """
        if not text or text == "[未识别到语音]":
            return text
        
        # 先清理空格
        text = self.clean_text(text)
        
        # 修复末尾标点符号
        text = self._improve_sentence_completeness(text)
        
        return text
    
    def _check_context_consistency(self, text: str, speaker_id: int,
                                   speaker_context: Dict, full_transcript: List) -> str:
        """检查上下文一致性,修正可能的识别错误"""
        if not text or text == "[未识别到语音]":
            return text
        
        # 获取最近几段的内容
        recent_context = []
        for entry in full_transcript[-3:]:
            # 兼容 'speaker' 和 'speaker_id' 两种字段名
            entry_speaker = entry.get('speaker') or entry.get('speaker_id')
            if entry_speaker == speaker_id:
                recent_context.append(entry.get('text', ''))
        
        # 检查重复内容
        if recent_context:
            for prev_text in recent_context:
                if self._calculate_similarity(text, prev_text) > 0.8:
                    return "[重复内容已过滤]"
        
        # 改善句子完整性
        text = self._improve_sentence_completeness(text)
        
        # 修正常见识别错误
        text = self._fix_common_recognition_errors(text)
        
        return text
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算两个文本的相似度"""
        if not text1 or not text2:
            return 0
        
        set1 = set(text1)
        set2 = set(text2)
        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))
        
        return intersection / union if union > 0 else 0
    
    def _improve_sentence_completeness(self, text: str) -> str:
        """改善句子完整性,添加缺失的标点符号"""
        if not text:
            return text
        
        # 去除末尾空白字符
        text = text.rstrip()
        if not text:
            return text
        
        # 定义所有可能的句末标点符号（中文和英文）
        sentence_end_punctuation = '。！？!?.\n'
        
        # 检查文本末尾是否已有标点符号
        last_char = text[-1]
        
        # 如果末尾已经是句末标点符号，直接返回，不添加（避免重复）
        if last_char in sentence_end_punctuation:
            return text
        
        # 如果末尾是逗号、分号等非句末标点，需要替换为合适的句末标点
        # 发言内容结尾不允许是逗号
        if last_char in '，、；:;':
            # 移除末尾的逗号/分号
            text = text[:-1]
            # 根据内容添加合适的句末标点
            if any(word in text for word in ['吗', '呢', '什么', '怎么', '为什么', '如何']):
                text += '?'
            elif any(word in text for word in ['太', '很', '非常', '真的']):
                text += '!'
            else:
                text += '。'
            return text
        
        # 末尾没有标点符号，根据内容添加合适的标点
        if any(word in text for word in ['吗', '呢', '什么', '怎么', '为什么', '如何']):
            text += '?'
        elif any(word in text for word in ['太', '很', '非常', '真的']):
            text += '!'
        else:
            text += '。'
        
        return text
    
    def _fix_common_recognition_errors(self, text: str) -> str:
        """修正常见的语音识别错误"""
        if not text:
            return text
        
        # 这里可以添加常见的同音字错误修正规则
        # 实际应用中可以使用更复杂的NLP模型
        
        return text
    
    def extract_topics(self, text: str) -> Set[str]:
        """从文本中提取主题关键词"""
        topics = set()
        
        topic_keywords = {
            '技术': ['技术', '开发', '编程', '代码', '系统', '软件', '硬件'],
            '产品': ['产品', '功能', '特性', '设计', '界面', '用户体验'],
            '市场': ['市场', '销售', '客户', '用户', '推广', '营销'],
            '管理': ['管理', '团队', '项目', '计划', '目标', '策略'],
            '财务': ['预算', '成本', '费用', '收入', '利润', '投资'],
            '会议': ['会议', '讨论', '决策', '意见', '建议', '方案']
        }
        
        for topic, keywords in topic_keywords.items():
            if any(keyword in text for keyword in keywords):
                topics.add(topic)
        
        return topics
    
    def extract_entities(self, text: str) -> Set[str]:
        """从文本中提取实体"""
        entities = set()
        
        # 人名(简单规则)
        names = re.findall(r'[\u4e00-\u9fff]{2,4}', text)
        for name in names:
            if len(name) >= 2 and not any(char in name for char in '的了我是在有'):
                entities.add(f"人名:{name}")
        
        # 数字
        numbers = re.findall(r'\d+', text)
        for num in numbers:
            entities.add(f"数字:{num}")
        
        # 时间
        time_patterns = re.findall(r'\d+[年月日时分秒]', text)
        for time_pattern in time_patterns:
            entities.add(f"时间:{time_pattern}")
        
        return entities
    
    def analyze_sentiment(self, text: str) -> str:
        """分析文本情感倾向"""
        positive_words = ['好', '棒', '优秀', '成功', '满意', '喜欢', '支持', '同意']
        negative_words = ['差', '糟糕', '失败', '不满', '反对', '问题', '错误', '困难']
        
        positive_count = sum(1 for word in positive_words if word in text)
        negative_count = sum(1 for word in negative_words if word in text)
        
        if positive_count > negative_count:
            return 'positive'
        elif negative_count > positive_count:
            return 'negative'
        else:
            return 'neutral'
    
    def update_speaker_context(self, current_context: Dict, new_text: str, 
                              start_time: float, end_time: float) -> Dict:
        """更新发言人上下文信息"""
        if not current_context:
            current_context = {
                'recent_texts': [],
                'speaking_pattern': [],
                'vocabulary': set(),
                'topics': set(),
                'entities': set(),
                'sentiment_trend': [],
                'speaking_style': {},
                'last_update': start_time,
                'total_speaking_time': 0
            }
        
        # 更新最近文本
        current_context['recent_texts'].append(new_text)
        if len(current_context['recent_texts']) > 5:
            current_context['recent_texts'].pop(0)
        
        # 更新词汇表
        words = new_text.split()
        current_context['vocabulary'].update(words)
        
        # 提取主题和实体
        topics = self.extract_topics(new_text)
        entities = self.extract_entities(new_text)
        current_context['topics'].update(topics)
        current_context['entities'].update(entities)
        
        # 分析情感趋势
        sentiment = self.analyze_sentiment(new_text)
        current_context['sentiment_trend'].append(sentiment)
        if len(current_context['sentiment_trend']) > 10:
            current_context['sentiment_trend'].pop(0)
        
        # 更新说话模式
        duration = end_time - start_time
        current_context['speaking_pattern'].append(duration)
        current_context['total_speaking_time'] += duration
        if len(current_context['speaking_pattern']) > 10:
            current_context['speaking_pattern'].pop(0)
        
        current_context['last_update'] = start_time
        
        return current_context

