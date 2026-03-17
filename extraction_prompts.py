"""ChatLuna 风格的记忆提取 Prompt 模板"""

ENHANCED_MEMORY_PROMPT = """你是一个记忆提取专家。从以下对话中提取关键信息，并按优先级分类。

对话内容：
{conversation}

请按以下优先级提取记忆（从高到低）：
1. preferences - 用户偏好、喜好、厌恶
2. personal - 个人信息、身份、背景
3. interests - 兴趣爱好、热情所在
4. habits - 日常习惯、行为模式
5. skills - 技能、专长、能力
6. relationships - 人际关系、社交圈
7. factual - 事实性知识、信息
8. contextual - 上下文相关信息
9. temporal - 时间相关信息、日期
10. task - 任务相关、待办事项
11. location - 位置相关、地点信息

输出格式为 YAML，结构如下：

memories:
  - content: "具体记忆内容"
    type: "记忆类型（11种之一）"
    importance: 8
  - content: "另一条记忆"
    type: "preference"
    importance: 6

要求：
- 每条记忆的 importance 评分 1-10，其中：
  - 9-10: 极其重要（个人身份、核心偏好、关键信息）
  - 7-8: 重要（常提及的信息、明确表达的偏好）
  - 5-6: 中等（一般性信息、可能有用）
  - 3-4: 较低（细节信息、可能过时）
  - 1-2: 最低（琐碎信息、临时性内容）
- 只提取明确的、有价值的信息
- 避免重复或冗余
- 保持记忆简洁清晰
- 按优先级顺序排列

开始提取："""

# 记忆类型定义
MEMORY_TYPES = {
    "preference": "用户偏好、喜好、厌恶、品味",
    "personal": "个人信息、身份、背景、经历",
    "interest": "兴趣爱好、热情所在、关注领域",
    "habit": "日常习惯、行为模式、日程安排",
    "skill": "技能、专长、能力、擅长领域",
    "relationship": "人际关系、社交圈、家庭成员",
    "factual": "事实性知识、信息、数据",
    "contextual": "上下文相关信息、背景知识",
    "temporal": "时间相关信息、日期、周期",
    "task": "任务相关、待办事项、目标",
    "location": "位置相关、地点信息、地理位置",
}

# 优先级顺序
PRIORITY_ORDER = [
    "preference",
    "personal",
    "interest",
    "habit",
    "skill",
    "relationship",
    "factual",
    "contextual",
    "temporal",
    "task",
    "location",
]
