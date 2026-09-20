# 命令行参考

## mdsite build

`mdsite build <输入目录> <输出目录> [--theme default|dark]`

- 递归扫描输入目录的 `.md` 文件
- 按目录结构生成对应的 `.html`
- 把主题 CSS 拷到 `输出目录/assets/style.css`

## mdsite serve

`mdsite serve <输出目录> --port 8000`

基于 `http.server` 的本地预览服务，`Ctrl+C` 停止。

## 错误处理

目录不存在、文件不可读、主题名写错等情况都会给出明确报错，
退出码为 `2`，不会把 traceback 糊到屏幕上。
