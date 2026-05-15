# astrbot_plugin_pansou

AstrBot 插件，对接自建 [PanSou](https://github.com/fish2018/pansou) 网盘搜索 API。

## 功能

- 聚合搜索百度、阿里、夸克、天翼、UC、115、PikPak、迅雷、123、移动等网盘
- 支持指定一个或多个网盘类型筛选
- 结果按网盘类型分组显示，附带资源链接

## 前置条件

先部署好 PanSou 服务：

```bash
docker run -d --name pansou -p 8888:8888 ghcr.io/fish2018/pansou:latest
```

## 插件配置

在 AstrBot WebUI → 插件 → PanSou → 配置 中填写：

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `api_base` | PanSou 服务地址 | `http://localhost:8888` |
| `max_results` | 每种网盘最多显示条数 | `5` |
| `timeout` | 请求超时秒数 | `20` |

## 使用方法

```
/搜索 <资源名>              搜索所有网盘
/搜索 百度 <资源名>         只搜百度网盘
/搜索 阿里 夸克 <资源名>    搜阿里云盘 + 夸克网盘
/搜索帮助                   显示帮助信息
```

### 支持的网盘关键词

| 关键词 | 对应网盘 |
|--------|---------|
| 百度 / baidu | 百度网盘 |
| 阿里 / 阿里云 / aliyun | 阿里云盘 |
| 夸克 / quark | 夸克网盘 |
| 天翼 / tianyi | 天翼云盘 |
| UC / uc | UC网盘 |
| 115 | 115网盘 |
| PikPak / pikpak | PikPak |
| 迅雷 / xunlei | 迅雷网盘 |
| 123 | 123网盘 |
| 移动 / mobile | 移动云盘 |
| 磁力 / magnet | 磁力链接 |

## 示例对话

```
用户: /搜索 流浪地球2
Bot:  🔍 正在搜索 [全部网盘] 中的「流浪地球2」，请稍候…
Bot:  🎯 「流浪地球2」搜索结果 (8 条)

      ━━━ 阿里云盘 (3 条) ━━━
      1. 流浪地球2 4K HDR 国语
         🔗 https://www.aliyundrive.com/s/xxxxx
      ...
```
