"""Анализатор: считает PnL по всем окнам + сравнивает с трейдером.

Запуск:
    python3 analyze.py
"""
from src.analyzer import compute_pnl

if __name__ == "__main__":
    compute_pnl()
