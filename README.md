# 壹米云相册 v3.0

轻量级私有云相册，专为 NAS 用户设计。一条命令安装，手机电脑随时访问。

## ✨ 特点

- 📱 移动端完美适配（iPhone/Android）
- 🗂️ 智能时间线，按日期自动整理
- 📂 硬盘浏览导入，直接引用不复制
- 🎬 视频缩略图自动生成
- 🖼️ 多尺寸缩略图，加载飞快
- 🔒 私有部署，数据完全在你手里
- ⚡ 轻量级，占用资源极少

## 📦 安装要求

- Docker (iStoreOS / 群晖 / OpenWrt / 任何 Linux NAS)
- 至少 256MB 可用内存
- 照片存储目录

## 🚀 一键安装

```bash
# 1. 下载安装包
wget https://github.com/leihongyue11-hash/yimi-photo/releases/latest/download/yimi-photo-v3.0.tar.gz
tar xzf yimi-photo-v3.0.tar.gz
cd yimi-photo-release

# 2. 一键安装
bash install.sh
```

安装脚本会自动：
- 检测 Docker 环境
- 引导你选择照片存储路径
- 配置端口和挂载点
- 启动服务

## 🔧 手动安装

```bash
# 1. 加载镜像
docker load -i yimi-photo.tar

# 2. 创建配置
mkdir -p /opt/yimi-photo
cd /opt/yimi-photo

# 3. 创建 docker-compose.yml
cat > docker-compose.yml << 'EOF'
version: "3.8"
services:
  yimi-photo:
    image: yimi-photo:latest
    container_name: yimi-photo
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - /你的照片目录:/data/photos    # 照片存储
      - /mnt:/mnt:ro                  # 硬盘浏览（可选）
    environment:
      - TZ=Asia/Shanghai
EOF

# 4. 启动
docker compose up -d
```

## 📖 使用说明

### 访问方式
- 手机/电脑浏览器打开：`http://你的NAS-IP:8080`
- 建议添加到手机主屏幕，体验接近原生 App

### 上传照片
- 点击底部导航的「上传」按钮
- 支持批量上传，支持 HEIC/HEIF/MP4/MOV 等格式

### 浏览硬盘
- 点击顶部「硬盘」图标
- 浏览 NAS 上的文件夹
- 点击「导入为相册」，直接引用不复制文件

### 创建相册
- 点击底部「相册」→ 右上角「+」
- 支持手动创建或从文件夹自动导入

## 🔄 升级

```bash
cd /opt/yimi-photo

# 加载新镜像
docker load -i yimi-photo-new.tar

# 重启
docker compose down
docker compose up -d
```

## ❓ 常见问题

**Q: 照片存储在哪里？**
A: 在安装时你选择的目录，所有照片原文件保存在那里，不会被移动或复制。

**Q: 支持什么格式？**
A: 图片：JPG/JPEG/PNG/GIF/HEIC/HEIF/BMP/TIFF/WebP
   视频：MP4/MOV/AVI/MKV/WebM/3GP

**Q: 占用多少资源？**
A: 空闲时约 50MB 内存，上传/缩略图生成时会短暂升高。

**Q: 数据安全吗？**
A: 所有数据存储在你自己的 NAS 上，不经过任何第三方服务器。

## 📝 更新日志

### v3.0.0
- 重构为模块化架构
- 修复文件夹相册创建时数据库锁定问题
- 移除密码认证，简化使用
- 集成 ffmpeg，视频缩略图自动生成
- 优化大文件上传，流式处理不占内存

## 📄 许可证

MIT License - 自由使用，自由分享。

---

**壹米云相册** - 你的照片，你的云端。

