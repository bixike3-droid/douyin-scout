# 站点部署（douyin.baodaoxiaoyuan.cn）

`site/` 是纯静态页面，没有任何构建步骤和后端依赖：上传文件即可访问。

## 一、目录约定

服务器上建议这样放：

```
/var/www/douyin/
  index.html
  style.css
  app.js
  assets/
  download/
    yuanjing-latest.zip     # 打包产物（desktop/打包.bat 生成的 zip 改名即可）
```

页面里下载按钮的地址是 `https://douyin.baodaoxiaoyuan.cn/download/yuanjing-latest.zip`。
换文件只要覆盖同名 zip，页面不用改。要换成别的路径，改 `site/index.html` 里的 `#dlStable`
和 `site/app.js` 顶部的 `DOWNLOAD_BASE` 一行即可。

## 二、上传

```powershell
# 本地打包（产物在 dist/）
desktop\打包.bat

# 上传（示例：scp，换成你自己的账号/路径）
scp -r site\* user@服务器:/var/www/douyin/
scp dist\源镜-*.zip user@服务器:/var/www/douyin/download/yuanjing-latest.zip
```

## 三、Nginx

```nginx
server {
    listen 80;
    server_name douyin.baodaoxiaoyuan.cn;
    root /var/www/douyin;
    index index.html;

    # 静态资源缓存
    location ~* \.(css|js|svg|png|jpg|ico)$ {
        expires 7d;
        add_header Cache-Control "public";
    }

    # 安装包：不缓存，避免下了旧版本
    location /download/ {
        add_header Cache-Control "no-store";
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

HTTPS 用 certbot 一条命令：

```bash
sudo certbot --nginx -d douyin.baodaoxiaoyuan.cn
```

## 四、上线后自查

1. `https://douyin.baodaoxiaoyuan.cn/` 打开正常，深色/浅色都能切
2. 首屏三张卡片可点、可自动轮播
3. 点「下载 zip」能下到文件，且和本地 `dist/` 里的一致
4. 手机打开不横向滚动，引用块（说话人/正文）变成上下堆叠
5. 浏览器控制台无报错

## 五、备选托管

如果不想自己维护服务器，这几家都能直接连仓库或上传静态文件，且不需要公开仓库：

- Cloudflare Pages（国内访问一般，可绑自定义域名）
- Netlify / Vercel（同上）
- 对象存储（阿里云 OSS / 腾讯云 COS）+ CDN：既能放页面，也能放 zip，国内速度最好

安装包体积约 80MB，放对象存储时建议开 CDN 并设置 `Content-Disposition: attachment`。


## 六、程序内更新（自建版本源）

程序启动后 6 秒会请求一次：

```
https://douyin.baodaoxiaoyuan.cn/update/version.json
```

它只做三件事：读这个 JSON、和本地版本号比大小、发现新版就弹窗。**不上传任何数据**。
这个地址读不到时会回退 GitHub API；两边都不通就静默跳过，不影响使用。

### 目录约定

```
/var/www/douyin/
  update/
    version.json
  download/
    yuanjing-0.9.1-windows-x64.zip
```

### nginx 追加

```nginx
location /update/ {
    alias /var/www/douyin/update/;
    add_header Cache-Control "no-store";
    default_type application/json;
}
```

### version.json 格式

```json
{
  "version": "0.9.1",
  "name": "v0.9.1",
  "published_at": "2026-10-21",
  "zip_url": "https://douyin.baodaoxiaoyuan.cn/download/yuanjing-0.9.1-windows-x64.zip",
  "size": 99868601,
  "sha256": "54b11fbe7cd2ce7a7ead47effa4ec66ba48c6b59d404c141976aa1244581bc17",
  "notes": "## v0.9.1\n\n- 更新内容……",
  "page": "https://douyin.baodaoxiaoyuan.cn/",
  "prerelease": false
}
```

程序会用 `sha256` 校验下载到的 zip，不一致直接丢弃（防中间人被替换）。

### 发新版本的完整流程

```powershell
# 本地：打 zip 后生成 version.json（自动算 size / sha256）
.venv\Scripts\python.exe scripts\publish_update.py dist\yuanjing-0.9.2-windows-x64.zip --version 0.9.2 --notes notes.md

# 上传两样东西
scp dist\yuanjing-0.9.2-windows-x64.zip admin@139.224.200.6:/var/www/douyin/download/
scp dist\update\version.json        admin@139.224.200.6:/var/www/douyin/update/version.json
```
