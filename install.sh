#!/bin/bash
# 壹米云相册 - 一键安装脚本
# 适用于 iStoreOS / OpenWrt / 群晖 / 任何支持 Docker 的 NAS

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       壹米云相册 - 一键安装脚本          ║${NC}"
echo -e "${BLUE}║       Yimi Cloud Photo v3.0              ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
echo ""

# 检查 Docker
if ! command -v docker &> /dev/null; then
    error "未检测到 Docker，请先安装 Docker"
fi

if ! docker info &> /dev/null 2>&1; then
    error "Docker 服务未启动，请先启动 Docker"
fi

# 检查 docker compose
COMPOSE_CMD=""
if docker compose version &> /dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    error "未检测到 docker compose，请先安装"
fi

ok "Docker 环境正常"

# 检查镜像文件
IMAGE_FILE="$SCRIPT_DIR/yimi-photo-v3.0.tar.gz"
if [ ! -f "$IMAGE_FILE" ]; then
    # 尝试未压缩版本
    IMAGE_FILE="$SCRIPT_DIR/yimi-photo-v3.0.tar"
fi

if [ ! -f "$IMAGE_FILE" ]; then
    error "未找到镜像文件 yimi-photo-v3.0.tar.gz，请确保与安装脚本在同一目录"
fi

# 加载镜像
info "正在加载镜像 (约 220MB, 请耐心等待)..."
if docker load -i "$IMAGE_FILE" 2>&1 | grep -q "Loaded"; then
    ok "镜像加载成功"
else
    # 可能已存在，检查一下
    if docker image inspect yimi-photo:v3.0 &> /dev/null 2>&1; then
        ok "镜像已存在"
    else
        error "镜像加载失败"
    fi
fi

# 安装目录
INSTALL_DIR="${1:-/opt/yimi-photo}"
info "安装目录: $INSTALL_DIR"

# 检测照片存储路径
DEFAULT_PHOTOS=""
for p in /mnt/data_sdc1/photos /mnt/sata2-2/photos /mnt/usb1/photos /volume1/photos /mnt/photo; do
    if [ -d "$(dirname "$p")" ]; then
        DEFAULT_PHOTOS="$p"
        break
    fi
done

if [ -z "$DEFAULT_PHOTOS" ]; then
    MOUNT_POINT=$(df -h 2>/dev/null | awk 'NR>1 && $5+0 < 90 {print $6}' | head -1)
    if [ -n "$MOUNT_POINT" ]; then
        DEFAULT_PHOTOS="$MOUNT_POINT/photos"
    else
        DEFAULT_PHOTOS="/mnt/data_sdc1/photos"
    fi
fi

echo ""
echo -e "${YELLOW}请确认以下配置 (直接回车使用默认值):${NC}"
echo ""

read -p "照片存储路径 [$DEFAULT_PHOTOS]: " PHOTOS_PATH
PHOTOS_PATH="${PHOTOS_PATH:-$DEFAULT_PHOTOS}"

read -p "访问端口 [8080]: " PORT
PORT="${PORT:-8080}"

read -p "外置硬盘挂载点 (浏览硬盘用, 不需要可留空) [/mnt]: " MOUNT_POINT_INPUT
MOUNT_POINT_INPUT="${MOUNT_POINT_INPUT:-/mnt}"

echo ""
info "配置确认:"
echo "  照片存储: $PHOTOS_PATH"
echo "  访问端口: $PORT"
echo "  硬盘挂载: ${MOUNT_POINT_INPUT:-无}"
echo ""
read -p "确认安装? (Y/n): " CONFIRM
if [ "$CONFIRM" = "n" ] || [ "$CONFIRM" = "N" ]; then
    echo "已取消"
    exit 0
fi

# 创建目录
mkdir -p "$INSTALL_DIR"
mkdir -p "$PHOTOS_PATH"

# 构建 volumes 配置
VOLUMES="      - ${PHOTOS_PATH}:/data/photos"
if [ -n "$MOUNT_POINT_INPUT" ]; then
    VOLUMES="$VOLUMES
      - ${MOUNT_POINT_INPUT}:${MOUNT_POINT_INPUT}:ro"
fi

# 创建 docker-compose.yml
cat > "$INSTALL_DIR/docker-compose.yml" << EOF
version: "3.8"

services:
  yimi-photo:
    image: yimi-photo:v3.0
    container_name: yimi-photo
    restart: unless-stopped
    ports:
      - "${PORT}:8080"
    volumes:
${VOLUMES}
    environment:
      - TZ=Asia/Shanghai
      - PYTHONUNBUFFERED=1
EOF

# 创建配置文件
cat > "$INSTALL_DIR/.env" << EOF
PHOTOS_PATH=${PHOTOS_PATH}
PORT=${PORT}
MOUNT_POINT=${MOUNT_POINT_INPUT}
EOF

echo ""
info "正在启动壹米云相册..."

cd "$INSTALL_DIR"

# 停止旧容器（如果存在）
docker rm -f yimi-photo 2>/dev/null || true

$COMPOSE_CMD up -d

# 等待启动
info "等待服务启动..."
for i in $(seq 1 30); do
    if curl -sf "http://localhost:${PORT}/api/stats" > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

# 验证
if curl -sf "http://localhost:${PORT}/api/stats" > /dev/null 2>&1; then
    ok "服务启动成功!"
else
    warn "服务可能还在启动中，请稍后访问"
fi

# 获取本机 IP
LOCAL_IP=$(ip route get 1 2>/dev/null | awk '{print $7; exit}' || hostname -I 2>/dev/null | awk '{print $1}' || echo "你的NAS-IP")

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              安装成功!                       ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  访问地址: http://${LOCAL_IP}:${PORT}          ║${NC}"
echo -e "${GREEN}║  数据目录: ${PHOTOS_PATH}                    ║${NC}"
echo -e "${GREEN}║                                              ║${NC}"
echo -e "${GREEN}║  管理命令:                                   ║${NC}"
echo -e "${GREEN}║    启动: cd ${INSTALL_DIR} && docker compose up -d    ║${NC}"
echo -e "${GREEN}║    停止: docker compose down                 ║${NC}"
echo -e "${GREEN}║    日志: docker logs -f yimi-photo           ║${NC}"
echo -e "${GREEN}║    卸载: docker rm -f yimi-photo             ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
