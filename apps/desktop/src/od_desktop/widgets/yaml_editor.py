"""YAML 编辑器 —— QPlainTextEdit + 基本语法高亮."""
from __future__ import annotations

import re
from typing import Optional

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import (
    QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextOption,
)
from PySide6.QtWidgets import QPlainTextEdit, QWidget


class _YamlHighlighter(QSyntaxHighlighter):
    """YAML 基本语法高亮."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []

        # 注释 (# ...)
        fmt_comment = QTextCharFormat()
        fmt_comment.setForeground(QColor(106, 153, 85))
        fmt_comment.setFontItalic(True)
        self._rules.append((QRegularExpression(r"#.*$"), fmt_comment))

        # 键 (word:)
        fmt_key = QTextCharFormat()
        fmt_key.setForeground(QColor(156, 220, 254))
        self._rules.append((QRegularExpression(r"^\s*[\w.-]+\s*:"), fmt_key))

        # 字符串值 (引号内)
        fmt_str = QTextCharFormat()
        fmt_str.setForeground(QColor(206, 145, 120))
        self._rules.append((QRegularExpression(r"""[^:]*".*?"""), fmt_str))

        # 布尔 / null
        fmt_bool = QTextCharFormat()
        fmt_bool.setForeground(QColor(86, 156, 214))
        fmt_bool.setFontWeight(QFont.Bold)
        self._rules.append((
            QRegularExpression(r"\b(true|false|null|True|False|None)\b"),
            fmt_bool,
        ))

        # 数字
        fmt_num = QTextCharFormat()
        fmt_num.setForeground(QColor(181, 206, 168))
        self._rules.append((
            QRegularExpression(r"\b\d+\.?\d*\b"),
            fmt_num,
        ))

        # 列表项 (- ...)
        fmt_list = QTextCharFormat()
        fmt_list.setForeground(QColor(220, 180, 60))
        self._rules.append((
            QRegularExpression(r"^\s*-\s"),
            fmt_list,
        ))

    def highlightBlock(self, text: str) -> None:
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                match = it.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)


class YamlEditor(QPlainTextEdit):
    """带行号显示和 YAML 语法高亮的文本编辑器."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._highlighter = _YamlHighlighter(self.document())

        font = QFont("Consolas", 12)
        font.setStyleHint(QFont.Monospace)
        self.setFont(font)
        self.setTabStopDistance(32)
        self.setWordWrapMode(QTextOption.NoWrap)

        self.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                padding: 8px;
            }
        """)

    def set_yaml_text(self, text: str) -> None:
        """设置编辑器内容."""
        self.setPlainText(text)

    def get_yaml_text(self) -> str:
        """获取编辑器内容."""
        return self.toPlainText()
