# SAGE — Student Article Grading Engine

<p align="center">
  <strong>🎓 借助 AI 大模型能力，批量按要求批阅学生作文</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.135+-green?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Docker-ready-blue?logo=docker&logoColor=white" alt="Docker">
</p>

---

## ✨ 功能特性

- **批量批阅** — 上传包含多篇作文的文件，AI 自动拆分并逐篇批阅
- **自定义评分细则** — 上传评分标准文件，AI 严格按照标准评分
- **灵活的批阅指令** — 用户可自定义批阅要求和报告格式
- **实时进度** — SSE 流式传输，实时显示批阅进度
- **详细报告** — 包含审题立意、语言表达、议论文特征分析、总评与升格建议
- **多模型支持** — 兼容 OpenAI API 格式的任意大模型（OpenAI / DeepSeek / Qwen 等）
- **一键导出** — 批阅完成后可导出全部报告为 Markdown，或导出单篇为 **Word (.docx)** 和 **PDF**（*注：Windows 本地运行导出 PDF 需依赖 GTK3，Docker 环境已内置*）
- **现代 Web UI** — 暗色主题，拖拽上传，响应式设计

---

## 🚀 快速开始

### 方式一：Docker 部署（推荐）

1. **创建 `.env` 文件**：

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的 API Key 等配置
```

2. **启动服务**：

```bash
docker compose up -d
```

3. **访问** `http://localhost:8000`

### 方式二：本地开发

> 需要安装 [uv](https://docs.astral.sh/uv/)

```bash
# 克隆项目
git clone https://github.com/zack-zzq/SAGE.git
cd SAGE

# 安装依赖
uv sync

# 创建配置文件
cp .env.example .env
# 编辑 .env 填入你的 API Key

# 启动服务
uv run python -m sage.main
```

访问 `http://localhost:8000`

---

## ⚙️ 配置说明

所有配置项可通过 `.env` 文件或环境变量设置，也可在 Web UI 中实时修改。

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `OPENAI_API_KEY` | API 密钥 | （必填） |
| `OPENAI_BASE_URL` | API 地址 | `https://api.openai.com/v1` |
| `OPENAI_MODEL_ID` | 模型 ID | `gpt-4o` |
| `APP_HOST` | 监听地址 | `0.0.0.0` |
| `APP_PORT` | 监听端口 | `8000` |

> **提示**：如果使用国内大模型（如 DeepSeek、通义千问），只需修改 `OPENAI_BASE_URL` 和 `OPENAI_MODEL_ID` 即可。

---

## 📖 使用说明

1. **配置模型** — 点击右上角齿轮图标，输入 API Key、Base URL 和模型 ID（如已通过 `.env` 配置则可跳过）
2. **上传评分细则** — 将评分标准文件（`.docx` 或 `.txt`）拖拽到左侧上传区
3. **上传学生作文** — 将包含学生作文的文件拖拽到右侧上传区（支持多篇作文合并在一个文件中）
4. **编写批阅指令** — 在文本框中输入具体的批阅要求
5. **开始批阅** — 点击"开始批阅"按钮，等待 AI 完成批阅
6. **查看报告** — 批阅完成后，点击顶部标签切换查看各篇作文的批阅报告
7. **导出报告** — 点击报告右上角的"Word"或"PDF"导出单篇报告，或点击下方"导出全部报告"下载合并的 Markdown 文件

---

## 🏗️ 技术栈

- **后端**：Python 3.12 + FastAPI + OpenAI SDK
- **前端**：HTML / CSS / JavaScript（marked.js 渲染 Markdown）
- **包管理**：uv
- **部署**：Docker + GitHub Actions → GHCR

---

## 📦 项目结构

```
SAGE/
├── src/sage/               # 后端源码
│   ├── main.py             # FastAPI 入口
│   ├── config.py           # 配置管理
│   ├── llm_client.py       # LLM API 客户端
│   ├── document_parser.py  # 文档解析
│   ├── essay_splitter.py   # 作文拆分（LLM）
│   ├── essay_grader.py     # 作文批阅（LLM）
│   └── api/routes.py       # API 路由
├── static/                 # 前端文件
│   ├── index.html
│   ├── style.css
│   └── app.js
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

---

## 📄 License

MIT
