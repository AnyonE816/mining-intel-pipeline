#!/usr/bin/env bash
set -e

echo "=============================="
echo " Mining Intel Pipeline — 初始化"
echo "=============================="

# 1. 创建虚拟环境
if [ ! -d "venv" ]; then
    echo "[1/4] 创建虚拟环境..."
    python3 -m venv venv
fi
source venv/bin/activate

# 2. 安装依赖
echo "[2/4] 安装依赖..."
pip install -q -r requirements.txt

# 3. 配置 API Key
if [ ! -f ".env" ]; then
    cp .env.example .env
fi

if grep -q "sk-your-dashscope-api-key-here" .env; then
    echo "[3/4] 配置 API Key..."
    read -p "请输入你的 DashScope API Key: " api_key
    # 替换占位 Key
    sed -i '' "s/sk-your-dashscope-api-key-here/$api_key/" .env
    echo "      ✅ API Key 已写入 .env"
else
    echo "[3/4] .env 已有 API Key，跳过"
fi

# 4. 重建向量库（已有则跳过）
CHROMA_FILE="data/chroma_db/chroma.sqlite3"
if [ -f "$CHROMA_FILE" ]; then
    echo "[4/4] 检测到已有向量库，跳过重建（如需强制重建请删除 data/chroma_db）"
else
    echo "[4/4] 重建向量库 (约2分钟)..."
    python pipeline/runner.py --step ingest
fi

echo ""
echo "=============================="
echo " ✅ 初始化完成，启动服务..."
echo "=============================="

uvicorn serve.main:app --host 0.0.0.0 --port 8000
