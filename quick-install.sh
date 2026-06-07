# 壹米云相册 - 快速安装 (无交互)
# 用法: bash quick-install.sh [照片路径] [端口]

PHOTOS_PATH="${1:-/mnt/data_sdc1/photos}"
PORT="${2:-8080}"
INSTALL_DIR="/opt/yimi-photo"

mkdir -p "$INSTALL_DIR" "$PHOTOS_PATH"

# 加载镜像
docker load -i "$(dirname "$0")/yimi-photo-v3.0.tar.gz"

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
      - ${PHOTOS_PATH}:/data/photos
      - /mnt:/mnt:ro
    environment:
      - TZ=Asia/Shanghai
EOF

cd "$INSTALL_DIR"
docker rm -f yimi-photo 2>/dev/null || true
docker compose up -d

echo "安装完成! 访问: http://$(ip route get 1 2>/dev/null | awk '{print $7; exit}'):${PORT}"
