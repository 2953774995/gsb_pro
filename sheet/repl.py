"""交互式命令行界面。"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import TextIO

from .address import Range, parse_cell_or_range, split_address
from .csv_io import load_csv, save_csv
from .display import render_table
from .engine import Workbook, format_value

SET_RE = re.compile(r"^set\s+([A-Za-z]+\d+)(?:\s+(.*))?$", re.IGNORECASE)
SHOW_RE = re.compile(r"^show(?:\s+(\S+))?$", re.IGNORECASE)


class Repl:
    def __init__(self, wb: Workbook | None = None, out: TextIO | None = None):
        self.wb = wb or Workbook()
        self.out = out or sys.stdout
        self.path: str | None = None
        self.running = True

    def say(self, text: str = "") -> None:
        print(text, file=self.out)

    def start(self, inp: TextIO | None = None) -> None:
        stream = inp or sys.stdin
        self.say("sheet 迷你电子表格，输入 help 查看命令。")
        while self.running:
            try:
                self.say("sheet> ")
                line = stream.readline()
            except EOFError:
                break
            if line == "":
                break
            result = self.execute(line.rstrip("\n"))
            if result is not None:
                self.say(result)
        self.say("再见。")

    def execute(self, command: str) -> str | None:
        text = command.strip()
        if not text:
            return None
        lower = text.lower()

        if lower in ("quit", "exit"):
            self.running = False
            return None
        if lower in ("help", "?"):
            return self.help_text()
        if lower == "show":
            return render_table(self.wb)
        if lower.startswith("show ") and len(text) > 5:
            return self.cmd_show(text[5:].strip())
        if lower.startswith("load ") and len(text) > 5:
            return self.cmd_load(text[5:].strip())
        if lower.startswith("save ") and len(text) > 5:
            return self.cmd_save(text[5:].strip())
        if lower.startswith("set ") and len(text) > 4:
            return self.cmd_set(text)
        if re.fullmatch(r"[A-Za-z]+\d+", text):
            return self.inspect_cell(text)
        if re.fullmatch(r"[A-Za-z]+\d+\s*:\s*[A-Za-z]+\d+", text):
            return self.cmd_show(text)
        return f"错误: 无法识别的命令: {text}（输入 help 查看帮助）"

    @staticmethod
    def help_text() -> str:
        return """命令清单：
  load <file.csv>       加载 CSV，替换当前表格
  save <file.csv>       保存当前表格；公式导出为计算后的值
  set <地址> <内容>     设置单元格，如 set B2 =A1*1.08
  show [A1:D10]         显示全表或指定区域
  <单元格地址>          查看该单元格的公式和值，如 B2
  help                  显示本帮助
  exit/quit             退出

公式示例：
  =A1+B2*2          =SUM(A1:A10)       =AVG(B1:B5)
  =MIN(...)         =MAX(...)          =COUNT(A1:C9)
  =A1>100           =\"合计: \"&B2      =(A1+2)*-3"""

    def cmd_load(self, path: str) -> str:
        if not path:
            return "用法: load <file.csv>"
        try:
            self.wb = load_csv(path)
            self.path = path
        except OSError as exc:
            return f"错误: 无法读取文件: {exc}"
        except Exception as exc:  # CSV/公式异常也要留在 REPL 中处理
            return f"错误: 加载失败: {exc}"
        return f"已加载 {path}：{self.wb.max_row} 行，{self.wb.max_col} 列"

    def cmd_save(self, path: str) -> str:
        if not path:
            return "用法: save <file.csv>"
        try:
            save_csv(self.wb, path)
        except OSError as exc:
            return f"错误: 无法写入文件: {exc}"
        return f"已保存 {path}"

    def cmd_set(self, command: str) -> str:
        match = SET_RE.fullmatch(command.strip())
        if not match:
            return '用法: set B2 =A1*1.08 （也可 set A1 文本；set A1 清空）'
        address = match.group(1).upper()
        # 内容以 = 开头视为公式，其余按常量/文本；省略内容则清空单元格。
        raw = (match.group(2) or "").strip()
        try:
            row, col = split_address(address)
            self.wb.set_value(row, col, raw)
        except (ValueError, OSError) as exc:
            return f"错误: {exc}"
        cell = self.wb.get_cell(row, col)
        if not raw:
            return f"{address} 已清空"
        return f"{address} = {raw}  ->  {format_value(cell.value)}"

    def cmd_show(self, target: str) -> str:
        try:
            normalized = parse_cell_or_range(target)
            if ":" in normalized:
                cell_range = Range.parse(normalized)
            else:
                row, col = split_address(normalized)
                cell_range = Range(row, col, row, col)
        except ValueError as exc:
            return f"错误: {exc}"
        return render_table(self.wb, cell_range)

    def inspect_cell(self, address_text: str) -> str:
        address = address_text.strip().upper()
        row, col = split_address(address)
        cell = self.wb.get_cell(row, col)
        value = format_value(cell.value)
        if cell.is_formula:
            return f"公式: {cell.raw}  值: {value}"
        if not cell.raw:
            return f"地址: {address}  值: (空)"
        return f"地址: {address}  值: {value}"


def run(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    wb = Workbook()
    path = argv[0] if argv else None
    if path:
        try:
            wb = load_csv(path)
        except (OSError, ValueError) as exc:
            print(f"错误: {exc}", file=sys.stderr)
            return 1
    Repl(wb).start()
    return 0
