"""
AstrBot 插件 - PanSou 网盘搜索
对接自建 PanSou API，聚合搜索百度、阿里、夸克等主流网盘。

配置项（在 AstrBot WebUI → 插件 → 盘搜 → 配置 中修改）：
  api_base    - PanSou 服务地址，如 http://192.168.1.100:8888
  max_results - 每种网盘默认显示条数
  timeout     - 请求超时秒数
  auth_token  - 可选，PanSou 认证 Token

使用方法：
  /搜索 <资源名>                  搜索所有网盘
  /搜索 10 <资源名>               所有网盘，每类最多10条
  /搜索 百度 <资源名>             只搜百度网盘
  /搜索 百度 10 <资源名>          百度网盘，最多10条
  /搜索 阿里 夸克 5 <资源名>      阿里+夸克，每类最多5条
  /搜索帮助                       显示帮助
"""

import urllib.parse
import re
import aiohttp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Star, register, Context

# 网盘别名 → PanSou cloud_types 值
CLOUD_ALIAS: dict = {
    "百度": "baidu",    "baidu": "baidu",
    "阿里": "aliyun",   "aliyun": "aliyun",  "阿里云": "aliyun",
    "夸克": "quark",    "quark": "quark",
    "天翼": "tianyi",   "tianyi": "tianyi",
    "uc": "uc",         "UC": "uc",
    "115": "115",
    "pikpak": "pikpak", "PikPak": "pikpak",
    "迅雷": "xunlei",   "xunlei": "xunlei",
    "123": "123",
    "移动": "mobile",   "mobile": "mobile",
    "磁力": "magnet",   "magnet": "magnet",
}

CLOUD_NAMES: dict = {
    "baidu":  "百度网盘",
    "aliyun": "阿里云盘",
    "quark":  "夸克网盘",
    "tianyi": "天翼云盘",
    "uc":     "UC网盘",
    "115":    "115网盘",
    "pikpak": "PikPak",
    "xunlei": "迅雷网盘",
    "123":    "123网盘",
    "mobile": "移动云盘",
    "magnet": "磁力链接",
    "ed2k":   "电驴链接",
    "others": "其他",
}

HELP_TEXT = """📦 网盘搜索插件使用说明

指令: /搜索 [网盘类型] [数量] <资源名>

示例:
  /搜索 流浪地球                → 搜索所有网盘
  /搜索 10 流浪地球             → 所有网盘，每类最多10条
  /搜索 百度 流浪地球            → 只搜百度网盘
  /搜索 百度 10 流浪地球         → 百度网盘，最多10条
  /搜索 阿里 夸克 5 流浪地球     → 阿里+夸克，每类最多5条

支持的网盘关键词:
  百度、阿里、夸克、天翼、UC、115、PikPak、迅雷、123、移动、磁力"""


@register(
    name="astrbot_plugin_pansou",
    desc="PanSou 网盘搜索插件，对接自建 PanSou API 服务",
    version="1.2.3",
    author="you",
)
class PanSouPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.cfg = config
        self.api_base: str = str(self.cfg.get("api_base", "http://localhost:8888")).rstrip("/")
        self.max_results: int = int(self.cfg.get("max_results", 5))
        self.timeout: int = int(self.cfg.get("timeout", 30))
        self.auth_token: str = str(self.cfg.get("auth_token", ""))
        logger.info(f"[PanSou] 初始化完成，API 地址: {self.api_base}")

    def _strip_command_prefix(self, text: str) -> str:
        """去除可能残留的命令前缀（兼容 /搜索、搜索 等情况）"""
        text = text.strip()
        prefixes = ["/搜索", "搜索"]
        for prefix in prefixes:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                break
        return text

    def _parse_search_args(self, args_str: str) -> tuple[list, str, int | None]:
        """
        解析搜索参数。
        返回: (cloud_types, keyword, limit)
        """
        parts = args_str.split()
        cloud_types = []
        keyword_parts = []
        limit = None

        for part in parts:
            mapped = CLOUD_ALIAS.get(part) or CLOUD_ALIAS.get(part.lower())
            if mapped:
                if mapped not in cloud_types:
                    cloud_types.append(mapped)
            elif part.isdigit() and limit is None:
                limit = max(1, min(int(part), 50))
            else:
                keyword_parts.append(part)

        return cloud_types, " ".join(keyword_parts).strip(), limit

    @filter.command("搜索")
    async def search(self, event: AstrMessageEvent):
        """网盘搜索，支持指定网盘类型和数量。用法: /搜索 [网盘] [数量] <资源名>"""
        args_str = self._strip_command_prefix(event.message_str)
        cloud_types, keyword, limit = self._parse_search_args(args_str)

        if not keyword:
            yield event.plain_result("❌ 请输入要搜索的资源名称。\n" + HELP_TEXT)
            return

        max_results = limit if limit is not None else self.max_results

        type_hint = "、".join(CLOUD_NAMES.get(c, c) for c in cloud_types) if cloud_types else "全部网盘"
        limit_hint = f" (每类最多{max_results}条)" if max_results != self.max_results else ""
        yield event.plain_result(f"🔍 正在搜索 [{type_hint}] 中的「{keyword}」{limit_hint}，请稍候…")

        try:
            results = await self._call_pansou(keyword, cloud_types)
            results = self._deduplicate_items(results)
        except Exception as e:
            logger.error(f"[PanSou] 请求异常: {e}")
            yield event.plain_result(f"❌ 搜索失败，请检查 PanSou 服务是否正常。\n错误: {e}")
            return

        if not results:
            yield event.plain_result(f"😅 未找到「{keyword}」的相关资源，换个关键词试试？")
            return

        yield event.plain_result(self._format_results(keyword, results, max_results))

    @filter.command("搜索帮助")
    async def search_help(self, event: AstrMessageEvent):
        """显示网盘搜索帮助"""
        yield event.plain_result(HELP_TEXT)

    async def _call_pansou(self, keyword: str, cloud_types: list) -> list:
        payload = {"kw": keyword, "res": "merge"}
        if cloud_types:
            payload["cloud_types"] = cloud_types

        url = f"{self.api_base}/api/search"
        timeout = aiohttp.ClientTimeout(total=self.timeout)

        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        logger.debug(f"[PanSou] 请求 URL: {url}")
        logger.debug(f"[PanSou] 请求 Payload: {payload}")

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                text = await resp.text()
                logger.debug(f"[PanSou] 响应状态: {resp.status}")
                logger.debug(f"[PanSou] 响应内容: {text[:2000]}")

                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}: {text[:500]}")

                try:
                    data = await resp.json()
                except Exception as e:
                    raise RuntimeError(f"JSON 解析失败: {e}\n响应: {text[:500]}")

        return self._parse_response(data)

    def _parse_response(self, data: dict) -> list:
        items = []

        merged = None
        if isinstance(data, dict):
            inner = data.get("data") or data
            merged = inner.get("merged_by_type")
            if merged is None:
                merged = inner.get("results")

        if merged is None:
            merged = {}

        logger.debug(f"[PanSou] 解析到的 merged 类型: {type(merged)}, 内容预览: {str(merged)[:500]}")

        if isinstance(merged, dict):
            for cloud_type, entries in merged.items():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    item = self._extract_item(entry, cloud_type)
                    if item:
                        items.append(item)
        elif isinstance(merged, list):
            for entry in merged:
                item = self._extract_item(
                    entry, entry.get("cloud_type") or entry.get("type") or "others"
                )
                if item:
                    items.append(item)

        logger.info(f"[PanSou] 解析完成，共 {len(items)} 条原始结果")
        return items

    # ─────────────────────────────────────────────
    # 字段候选列表（根据 PanSou API 实际返回优化）
    # ─────────────────────────────────────────────

    NAME_CANDIDATES = [
        # PanSou 实际使用的字段（优先级最高）
        "note", "title", "name", "file_name", "resource_name", "filename",
        # 其他可能的字段
        "text", "content", "description", "summary", "subject",
        "resource_title", "share_title", "dir_name", "folder_name",
        "pan_name", "res_name", "share_name", "file_title",
        "main_title", "subtitle", "label", "tag", "subject_title",
        "resource", "fileTitle", "shareTitle", "resTitle",
    ]

    URL_CANDIDATES = [
        "url", "link", "share_url", "href", "download_url",
        "pan_url", "source_url", "redirect_url", "target_url",
        "share_link", "pan_link", "download_link", "surl",
    ]

    DATE_CANDIDATES = [
        "datetime", "date", "time", "created_at", "updated_at", "timestamp",
        "create_time", "update_time", "pub_date", "publish_time",
        "share_time", "add_time", "post_date", "shareDate",
    ]

    SOURCE_CANDIDATES = [
        "source", "from", "author", "provider", "origin",
        "share_user", "uploader", "publisher", "site",
    ]

    # 兜底逻辑中需要排除的字段（避免把 source/password 等元数据当成名称）
    EXCLUDE_NAME_KEYS = {
        "source", "password", "images", "url", "link", "href",
        "download_url", "pan_url", "share_url", "datetime", "date",
        "time", "created_at", "updated_at", "timestamp",
    }

    def _find_field(self, obj, candidates: list[str], max_depth: int = 4) -> str | None:
        """
        在对象中递归、大小写不敏感地查找指定字段。
        支持 dict / list 嵌套。
        """
        if max_depth <= 0 or obj is None:
            return None

        if isinstance(obj, dict):
            # 1) 先精确匹配（最快）
            for key in candidates:
                if key in obj:
                    val = obj[key]
                    if val is not None and isinstance(val, str) and val.strip():
                        return val.strip()

            # 2) 大小写不敏感匹配
            lower_map = {k.lower(): k for k in obj.keys() if isinstance(k, str)}
            for key in candidates:
                real_key = lower_map.get(key.lower())
                if real_key:
                    val = obj[real_key]
                    if val is not None and isinstance(val, str) and val.strip():
                        return val.strip()

            # 3) 递归进入子对象
            for v in obj.values():
                result = self._find_field(v, candidates, max_depth - 1)
                if result:
                    return result

        elif isinstance(obj, list):
            for item in obj:
                result = self._find_field(item, candidates, max_depth - 1)
                if result:
                    return result

        return None

    def _is_valid_date(self, val: str) -> bool:
        """判断日期字符串是否有效（排除 0001-01-01 等无效日期）"""
        if not val or not isinstance(val, str):
            return False
        invalid_patterns = [
            r"0000", r"0001", r"1970-01-01", r"0000-00-00",
        ]
        for pattern in invalid_patterns:
            if pattern in val:
                return False
        if not re.search(r"\d", val):
            return False
        return True

    def _extract_item(self, entry: dict, cloud_type: str) -> dict | None:
        """从单条结果中提取标准化字段（针对 PanSou API 结构优化）"""
        if not isinstance(entry, dict):
            return None

        logger.debug(f"[PanSou] 原始条目键名: {list(entry.keys())}")

        # ── 提取名称 ──
        name = self._find_field(entry, self.NAME_CANDIDATES)

        # 如果 note 存在但为空，且 _find_field 返回了其他字段（如 source），需要修正
        # 优先检查当前层级的 note 字段
        if not name or name in (entry.get("source", ""), entry.get("password", "")):
            note_val = entry.get("note")
            if isinstance(note_val, str) and note_val.strip():
                name = note_val.strip()

        # 最终兜底：遍历当前层，排除已知元数据字段
        if not name:
            str_vals = []
            for k, v in entry.items():
                if not isinstance(v, str) or not v.strip():
                    continue
                if k.lower() in self.EXCLUDE_NAME_KEYS:
                    continue
                v_strip = v.strip()
                # 排除 URL
                if v_strip.startswith("http") and len(v_strip) > 20:
                    continue
                # 排除看起来像日期的
                if re.match(r"^\d{4}-\d{2}-\d{2}", v_strip) or re.match(r"^\d{4}/\d{2}/\d{2}", v_strip):
                    continue
                if len(v_strip) > 1:  # note 可能很短，放宽到 1 字符
                    str_vals.append(v_strip)
            
            if str_vals:
                # 优先选最长的，但排除纯插件名（如 plugin:xxx）
                non_plugin = [s for s in str_vals if not s.startswith("plugin:") and not s.startswith("tg:")]
                if non_plugin:
                    name = max(non_plugin, key=len)
                else:
                    name = max(str_vals, key=len)
            else:
                name = "未知名称"

        # 最后防线：如果名称还是像元数据，强制替换
        if name.startswith(("http://", "https://")) and len(name) > 20:
            name = "未知名称"
        if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", name) or "0001-01-01" in name:
            name = "未知名称"

        # ── 提取 URL ──
        url = self._find_field(entry, self.URL_CANDIDATES)
        if not url:
            logger.debug(f"[PanSou] 跳过无 URL 的条目: {entry}")
            return None

        # ── 提取日期 ──
        date_raw = self._find_field(entry, self.DATE_CANDIDATES) or ""
        # 优先用当前层级的 datetime（PanSou 实际字段）
        if "datetime" in entry and isinstance(entry["datetime"], str):
            date_raw = entry["datetime"].strip()
        date = date_raw if self._is_valid_date(date_raw) else ""

        # ── 提取来源 ──
        source = self._find_field(entry, self.SOURCE_CANDIDATES) or ""
        # 优先用当前层级的 source
        if "source" in entry and isinstance(entry["source"], str) and entry["source"].strip():
            source = entry["source"].strip()

        # ── 提取密码 ──
        pwd = ""
        if "password" in entry and isinstance(entry["password"], str) and entry["password"].strip():
            pwd = entry["password"].strip()

        logger.debug(f"[PanSou] 提取结果: name={name[:40]}..., url={url[:60]}...")
        return {
            "name": name,
            "url": url,
            "type": cloud_type,
            "date": date,
            "source": source,
            "password": pwd,
        }

    # ─────────────────────────────────────────────
    # 去重逻辑（基于 URL 核心路径）
    # ─────────────────────────────────────────────

    def _normalize_url(self, url: str) -> str:
        """提取 URL 核心路径用于去重（忽略 query 参数、fragment、大小写）"""
        try:
            parsed = urllib.parse.urlparse(url.strip())
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".lower().rstrip("/")
        except Exception:
            return url.lower().strip()

    def _extract_pwd(self, url: str) -> str | None:
        """从 URL 的 query 或 fragment 中提取密码"""
        try:
            parsed = urllib.parse.urlparse(url)
            query = urllib.parse.parse_qs(parsed.query)
            for key in ("pwd", "password", "pass", "extract_code", "code"):
                if key in query and query[key][0]:
                    return query[key][0]
            fragment = parsed.fragment
            if "pwd=" in fragment:
                return fragment.split("pwd=")[-1].split("&")[0]
        except Exception:
            pass
        return None

    def _deduplicate_items(self, items: list) -> list:
        """基于 URL 去重，合并相同链接的不同密码"""
        seen: dict[str, dict] = {}

        for item in items:
            base_url = self._normalize_url(item["url"])

            if base_url in seen:
                # 合并 URL 中的密码
                pwd = self._extract_pwd(item["url"])
                if pwd:
                    existing = seen[base_url]
                    if "alt_pwds" not in existing:
                        existing["alt_pwds"] = []
                    if pwd not in existing["alt_pwds"]:
                        existing["alt_pwds"].append(pwd)
                # 合并独立 password 字段
                item_pwd = item.get("password", "")
                if item_pwd:
                    existing = seen[base_url]
                    if "alt_pwds" not in existing:
                        existing["alt_pwds"] = []
                    if item_pwd not in existing["alt_pwds"]:
                        existing["alt_pwds"].append(item_pwd)
            else:
                new_item = item.copy()
                pwd = self._extract_pwd(item["url"])
                if pwd:
                    new_item["main_pwd"] = pwd
                # 如果 URL 没密码但独立字段有
                item_pwd = item.get("password", "")
                if item_pwd and not pwd:
                    new_item["main_pwd"] = item_pwd
                seen[base_url] = new_item

        logger.info(f"[PanSou] 去重完成，{len(items)} 条 → {len(seen)} 条")
        return list(seen.values())

    # ─────────────────────────────────────────────
    # 格式化输出
    # ─────────────────────────────────────────────

    def _format_results(self, keyword: str, items: list, max_results: int | None = None) -> str:
        if max_results is None:
            max_results = self.max_results

        groups = {}
        for item in items:
            groups.setdefault(item["type"], []).append(item)

        lines = [f"🎯 「{keyword}」搜索结果 (去重后 {len(items)} 条)\n"]
        for cloud_type, group_items in groups.items():
            cloud_name = CLOUD_NAMES.get(cloud_type, cloud_type)
            display_items = group_items[:max_results]
            lines.append(f"━━━ {cloud_name} ({len(display_items)}/{len(group_items)} 条) ━━━")

            for idx, item in enumerate(display_items, 1):
                name = item["name"][:50] + ("…" if len(item["name"]) > 50 else "")
                date_str = f" [{item['date']}]" if item.get("date") else ""
                source_str = f" (来源: {item['source']})" if item.get("source") else ""

                # 构建 URL 显示，合并多密码
                url_display = item["url"]
                alt_pwds = item.get("alt_pwds", [])
                main_pwd = item.get("main_pwd", "")

                # 去重并排序密码，保持主密码在前
                all_pwds = []
                if main_pwd and main_pwd not in all_pwds:
                    all_pwds.append(main_pwd)
                for p in alt_pwds:
                    if p not in all_pwds:
                        all_pwds.append(p)

                if len(all_pwds) > 1:
                    url_display += f" (提取码: {' / '.join(all_pwds)})"
                elif len(all_pwds) == 1:
                    url_display += f" (提取码: {all_pwds[0]})"

                lines.append(f"{idx}. {name}{date_str}{source_str}")
                lines.append(f"   🔗 {url_display}")

            if len(group_items) > max_results:
                lines.append(f"   ... 还有 {len(group_items) - max_results} 条未显示")
            lines.append("")

        lines.append("⚠️ 资源由第三方提供，请自行甄别有效性。")
        return "\n".join(lines)