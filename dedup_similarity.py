import math
from collections import Counter


def cosine_similarity(text1: str, text2: str) -> float:
    """余弦相似度"""
    words1 = text1.lower().split()
    words2 = text2.lower().split()
    
    counter1 = Counter(words1)
    counter2 = Counter(words2)
    
    all_words = set(counter1.keys()) | set(counter2.keys())
    if not all_words:
        return 0.0
    
    dot_product = sum(counter1[w] * counter2[w] for w in all_words)
    norm1 = math.sqrt(sum(v ** 2 for v in counter1.values()))
    norm2 = math.sqrt(sum(v ** 2 for v in counter2.values()))
    
    if norm1 == 0 or norm2 == 0:
        return 0.0
    
    return dot_product / (norm1 * norm2)


def jaccard_similarity(text1: str, text2: str) -> float:
    """Jaccard 相似度"""
    set1 = set(text1.lower().split())
    set2 = set(text2.lower().split())
    
    if not set1 and not set2:
        return 1.0
    
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    
    return intersection / union if union > 0 else 0.0


def levenshtein_similarity(text1: str, text2: str) -> float:
    """编辑距离相似度"""
    s1, s2 = text1.lower(), text2.lower()
    len1, len2 = len(s1), len(s2)
    
    if len1 == 0 and len2 == 0:
        return 1.0
    if len1 == 0 or len2 == 0:
        return 0.0
    
    dp = [[0] * (len2 + 1) for _ in range(len1 + 1)]
    
    for i in range(len1 + 1):
        dp[i][0] = i
    for j in range(len2 + 1):
        dp[0][j] = j
    
    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            if s1[i - 1] == s2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    
    max_len = max(len1, len2)
    return 1.0 - (dp[len1][len2] / max_len)


def bm25_similarity(query: str, document: str, k1: float = 1.5, b: float = 0.75) -> float:
    """BM25 评分"""
    query_words = query.lower().split()
    doc_words = document.lower().split()
    
    if not query_words or not doc_words:
        return 0.0
    
    doc_len = len(doc_words)
    avg_doc_len = doc_len
    
    doc_counter = Counter(doc_words)
    score = 0.0
    
    for word in set(query_words):
        freq = doc_counter.get(word, 0)
        if freq > 0:
            idf = math.log(1 + (1 - b + b * (doc_len / avg_doc_len)))
            bm25_score = idf * (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * (doc_len / avg_doc_len)))
            score += bm25_score
    
    max_score = len(set(query_words)) * math.log(2)
    return min(score / max_score if max_score > 0 else 0.0, 1.0)


def calculate_similarity(text1: str, text2: str) -> float:
    """
    综合相似度评分
    权重：0.5*BM25 + 0.35*cosine + 0.1*jaccard + 0.05*levenshtein
    """
    bm25_score = bm25_similarity(text1, text2)
    cosine_score = cosine_similarity(text1, text2)
    jaccard_score = jaccard_similarity(text1, text2)
    levenshtein_score = levenshtein_similarity(text1, text2)
    
    combined_score = (
        0.5 * bm25_score +
        0.35 * cosine_score +
        0.1 * jaccard_score +
        0.05 * levenshtein_score
    )
    
    return combined_score
