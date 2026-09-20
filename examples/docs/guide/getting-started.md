# 快速开始

## 安装

### 环境要求

- Python 3.8+
  - 不需要任何第三方库
  - 测试需要 `pytest`

### 获取源码

```bash
git clone https://example.com/mdsite.git
cd mdsite
```

## 第一次构建

准备一个放 Markdown 的目录，然后运行：

```bash
python -m mdsite build docs/ site/
python -m mdsite serve site/ --port 8000
```

打开浏览器访问 [http://127.0.0.1:8000/](http://127.0.0.1:8000/) 即可预览。

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `docs/` | Markdown 源文件，支持任意嵌套子目录 |
| `site/` | 构建输出，直接部署即可 |
| `site/assets/style.css` | 构建时拷贝的主题样式 |
