"""
SimHash 64-bit implementation for text deduplication.

This module provides a SimHash algorithm implementation based on SHA256
hashing for generating 64-bit fingerprints of text content.
"""

from __future__ import annotations

import hashlib
import re


def normalize_text(text: str) -> str:
    """
    Normalize text for SimHash computation.
    
    Converts text to lowercase and removes special characters,
    keeping only alphanumeric characters, Chinese characters, and whitespace.
    
    Args:
        text: The input text to normalize.
        
    Returns:
        Normalized text string.
    """
    text = text.lower()
    text = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def tokenize(text: str) -> list[str]:
    """
    Tokenize text into tokens for SimHash computation.
    
    For English text, splits by whitespace.
    For Chinese text, uses bigram tokenization.
    
    Args:
        text: The input text to tokenize.
        
    Returns:
        List of tokens.
    """
    tokens: list[str] = []
    words = text.split()
    
    for word in words:
        has_chinese = any('\u4e00' <= char <= '\u9fff' for char in word)
        
        if has_chinese:
            chars = [char for char in word if '\u4e00' <= char <= '\u9fff']
            for i in range(len(chars) - 1):
                tokens.append(chars[i] + chars[i + 1])
            if len(chars) == 1:
                tokens.append(chars[0])
        else:
            if word:
                tokens.append(word)
    
    return tokens


def _sha256_bytes(token: str) -> bytes:
    """
    Compute SHA256 hash of a token and return as bytes.
    
    Args:
        token: The token to hash.
        
    Returns:
        32-byte SHA256 hash.
    """
    return hashlib.sha256(token.encode('utf-8')).digest()


def _bits_to_hex(bits: list[int]) -> str:
    """
    Convert a list of bits to a hexadecimal string.
    
    Args:
        bits: List of 0s and 1s.
        
    Returns:
        Hexadecimal string representation.
    """
    hex_str = ''
    for i in range(0, len(bits), 4):
        nibble = 0
        for j in range(4):
            if i + j < len(bits):
                nibble = (nibble << 1) | bits[i + j]
            else:
                nibble = nibble << 1
        hex_str += format(nibble, 'x')
    return hex_str


def _hex_to_bits(hex_str: str) -> list[int]:
    """
    Convert a hexadecimal string to a list of bits.
    
    Args:
        hex_str: Hexadecimal string.
        
    Returns:
        List of 0s and 1s.
    """
    bits: list[int] = []
    for char in hex_str:
        nibble = int(char, 16)
        for i in range(3, -1, -1):
            bits.append((nibble >> i) & 1)
    return bits


class SimHasher:
    """
    SimHash implementation for text fingerprinting.
    
    Generates 64-bit SimHash fingerprints using SHA256-based token hashing.
    """
    
    DEFAULT_BIT_LENGTH: int = 64
    
    def __init__(self, bit_length: int = DEFAULT_BIT_LENGTH) -> None:
        """
        Initialize SimHasher with specified bit length.
        
        Args:
            bit_length: Number of bits for the hash (default: 64).
        """
        self.bit_length: int = bit_length
    
    def compute_simhash_hex(self, text: str) -> str:
        """
        Compute 64-bit SimHash fingerprint of text as hex string.
        
        The algorithm:
        1. Normalize and tokenize the text
        2. For each token, compute SHA256 hash
        3. For each bit position, accumulate +1 or -1 based on hash bits
        4. Generate final hash bits (1 if sum > 0, else 0)
        5. Convert to hexadecimal string
        
        Args:
            text: The input text to hash.
            
        Returns:
            Hexadecimal string representation of the SimHash.
        """
        normalized = normalize_text(text)
        tokens = tokenize(normalized)
        
        if not tokens:
            return '0' * (self.bit_length // 4)
        
        v = [0] * self.bit_length
        
        for token in tokens:
            h = _sha256_bytes(token)
            for i in range(self.bit_length):
                byte_index = i // 8
                bit_index = 7 - (i % 8)
                bit = (h[byte_index] >> bit_index) & 1
                v[i] += 1 if bit else -1
        
        bits = [1 if x > 0 else 0 for x in v]
        return _bits_to_hex(bits)


def hamming_distance_hex(hex1: str, hex2: str) -> int:
    """
    Calculate Hamming distance between two hexadecimal SimHash strings.
    
    Args:
        hex1: First hexadecimal SimHash string.
        hex2: Second hexadecimal SimHash string.
        
    Returns:
        Number of differing bits between the two hashes.
    """
    bits1 = _hex_to_bits(hex1)
    bits2 = _hex_to_bits(hex2)
    
    max_len = max(len(bits1), len(bits2))
    bits1 = bits1 + [0] * (max_len - len(bits1))
    bits2 = bits2 + [0] * (max_len - len(bits2))
    
    distance = 0
    for b1, b2 in zip(bits1, bits2):
        if b1 != b2:
            distance += 1
    
    return distance


def simhash_similarity(hex1: str, hex2: str) -> float:
    """
    Calculate similarity between two hexadecimal SimHash strings.
    
    Similarity is computed as: 1 - (hamming_distance / bit_length)
    
    Args:
        hex1: First hexadecimal SimHash string.
        hex2: Second hexadecimal SimHash string.
        
    Returns:
        Similarity score between 0.0 and 1.0.
    """
    bits1 = _hex_to_bits(hex1)
    bits2 = _hex_to_bits(hex2)
    
    max_len = max(len(bits1), len(bits2))
    if max_len == 0:
        return 1.0
    
    distance = hamming_distance_hex(hex1, hex2)
    return 1.0 - (distance / max_len)
