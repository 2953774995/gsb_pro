# zipmini

从零实现的 DEFLATE（RFC 1951）压缩器 + ZIP（PKZIP）归档工具。
**不依赖** `zlib` / `gzip` / `zipfile` 等任何现成压缩实现；唯一借用的标准库
功能是 `binascii.crc32`（CRC32 校验）。

## 用法

```console
$ python -m zipmini c archive.zip file1 file2 dir/   # 压缩（-l 1..9 调压缩级别）
$ python -m zipmini x archive.zip -d out/            # 解压（校验 CRC32）
$ python -m zipmini l archive.zip                    # 列出内容/大小/压缩率
```

`pip install .` 后会得到 `zipmini` 命令（入口 `zipmini.cli:main`）。

## 模块划分

| 模块 | 职责 |
| --- | --- |
| `zipmini/bitstream.py` | 位流读写。DEFLATE 数据位按 **LSB-first** 打包进字节；`BitWriter` 按位追加、`align()` 补齐字节；`BitReader` 支持 `peek/drop`（供 Huffman 查表）与字节对齐回退。 |
| `zipmini/huffman.py` | 规范 Huffman 码。`length_limited_code_lengths()` 用 **package-merge** 算法求码长上限 15 位的最优码长；`canonical_codes()` 按"码长升序、同码长按符号值升序"分配码字；编码端把码字**位反转**后交给 LSB-first 的位流（Huffman 码本身是 MSB-first 传输的）。 |
| `zipmini/deflate.py` | LZ77 + 三种块的编码器/解码器。LZ77 用 **3 字节哈希链**（`head[65536]` + `prev[32768]` 环）在 32KB 窗口内找最长匹配，链长上限 / nice-length / good-match 启发式控制速度。输出 token 流（字面量或 (距离, 长度)），再按 stored / 固定 Huffman / 动态 Huffman 三种方式中**精确位代价最小**的一种成块。 |
| `zipmini/archive.py` | ZIP 容器。`ZipWriter` 写 local file header + central directory + EOCD；`ZipReader` 从文件尾定位 EOCD、解析中央目录、按成员解压并**校验 CRC32 与长度**。支持目录条目、UTF-8 文件名（flag bit 11）、DOS 时间戳。 |
| `zipmini/cli.py` | 命令行 `c` / `x` / `l`。 |

## DEFLATE 编码流程

1. **LZ77**：输入 → token 序列（字面量 / 匹配）。匹配长度 3–258，距离 1–32768。
2. **选块类型**（按精确比特数取最小）：
   - **stored**：不可压缩数据（如随机字节）原样存放，只加 5 字节/块的
     LEN/NLEN 头，保证不会越压越大；
   - **固定 Huffman**：RFC 1951 预定义码表，适合小数据；
   - **动态 Huffman**：见下。
3. **动态 Huffman 块**（RFC 1951 §3.2.7）：
   - 统计 字面量/长度（0–285）与 距离（0–29）两个字母表的符号频率；
   - 各建一棵码长 ≤15 的 Huffman 树（package-merge）；不足两个非零符号时
     补齐，保证树完整、可被所有解码器接受；
   - 两棵树的码长序列拼接后做**游程编码**（16 = 重复前一长度 3–6 次，
     17 = 重复 0 长度 3–10 次，18 = 重复 0 长度 11–138 次）；
   - 游程符号（0–18）再建一棵码长 ≤7 的 Huffman 树，其码长按
     `16,17,18,0,8,...,15` 的顺序写入 HLIT/HDIST/HCLEN 头；
   - 最后依次写出全部 token 的 Huffman 码字与 extra bits。

## ZIP 文件布局

```
[local file header]  PK\x03\x04  版本/标志/方法/时间/CRC/大小/文件名 → 压缩数据
... 每个成员一份 ...
[central directory]  PK\x01\x02  同上 + 外部属性 + local header 偏移
[end of central dir] PK\x05\x06  成员数、目录大小与偏移
```

- 压缩方法：0 = stored，8 = raw DEFLATE（无 zlib 头）。写包时若 DEFLATE
  输出不比原文小，则退化为 stored。
- 时间戳为 DOS 日期/时间格式（2 秒粒度，1980 年起）。
- 解压时逐成员校验解压后长度与 CRC32，不匹配抛 `ZipError`。

## 测试

```console
$ python -m pytest tests/
```

- `test_bitstream.py`：LSB 序、跨字节读写、peek/drop、对齐、越界报错。
- `test_huffman.py`：等频/单符号/两符号/15 位上限/Kraft 完备性/规范码序。
- `test_deflate.py`：**手工构造**的 stored / 固定 / 动态三种块的参考字节流
  解码验证（不借助任何压缩库），以及空文件、1 字节、文本、重复模式、随机
  字节、窗口边界、数 MB 大文件的 roundtrip。
- `test_zip.py`：结构签名、多文件/目录/时间戳/非 ASCII 文件名 roundtrip、
  篡改一字节后 CRC 报错、**系统 `unzip` 解我们生成的包**、
  **我们解系统 `zip` 生成的包**。
- `test_cli.py`：`python -m zipmini c/x/l` 端到端。
