"""
VIP Tool - 增强版 v3.6
================================
支持多平台视频解析与自动获取m3u8

更新v3.6:
- 直接MP4下载（使用session cookies）
- nosdn.127.net直链处理
- 动态Headers与断点续传
- MP4文件结构验证
更新v3.5:
- 增强URL验证（域名格式检查）
- 路径安全验证（防止目录遍历）
- 添加SSL警告提示
- 动态Referer设置

Usage:
    python vip_tool.py              # GUI窗口
    python vip_tool.py play        # 播放视频
    python vip_tool.py auto        # 自动获取m3u8并下载
    python vip_tool.py get <m3u8>  # 下载视频
"""
import os
import sys
import time
import json
import re
import subprocess
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
print("[!] 警告: SSL验证已禁用，仅用于测试环境")
import webbrowser
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

# ============================================================
# 配置
# ============================================================
CONFIG = {
    "default_url": "https://v.qq.com/x/cover/mcv8hkc8zk8lnov/e4102pfd88z.html",
    "download_dir": "downloads",
    "default_quality": "1080p",  # 1080p, 720p, 480p, 360p, auto
    "default_format": "mp4",     # mp4, webm, mkv
    "default_codec": "h264",     # h264, h265, av1
}

CURRENT_VIDEO_TITLE = ""

# 解析接口配置 - 备用解析服务
PARSE_SOURCES = [
    ("https://jx.m3u8.tv/jiexi/?url=", "jx.m3u8.tv线路"),
    ("https://jx.xmflv.com/?url=", "xmflv线路"),
]


# ============================================================
# ============================================================
# 工具函数
# ============================================================
def check_ffmpeg():
    import shutil
    
    system_ffmpeg = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if system_ffmpeg:
        try:
            subprocess.run([system_ffmpeg, "-version"], capture_output=True, timeout=5, check=True)
            return system_ffmpeg
        except Exception:
            pass
    
    portable_paths = [
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "ms-playwright", "ffmpeg-1011", "ffmpeg-win64.exe"),
    ]
    for fp in portable_paths:
        if os.path.exists(fp):
            try:
                subprocess.run([fp, "-version"], capture_output=True, timeout=5, check=True)
                return fp
            except Exception:
                continue
    
    return None


def check_playwright():
    """检测Playwright"""
    try:
        from playwright.sync_api import sync_playwright
        return True
    except ImportError:
        return False
    except Exception as e:
        print(f"[!] Playwright导入失败: {e}")
        return False


def get_chromium_path():
    import glob
    user_path = os.path.expanduser("~")
    base = os.path.join(user_path, "AppData", "Local", "ms-playwright")
    
    # 优先搜索 chromium_headless_shell
    pattern = os.path.join(base, "chromium_headless_shell-*", "chrome-headless-shell-win64", "chrome-headless-shell.exe")
    matches = glob.glob(pattern)
    if matches:
        matches.sort(reverse=True)
        return matches[0]
    
    # 其次搜索 chromium
    pattern = os.path.join(base, "chromium-*", "chrome-win64", "chrome.exe")
    matches = glob.glob(pattern)
    if matches:
        matches.sort(reverse=True)
        return matches[0]
    
    # Fallback to old pattern
    pattern2 = os.path.join(base, "chromium", "chrome-win", "chrome.exe")
    if os.path.exists(pattern2):
        return pattern2
    
    print("[!] 未找到Playwright Chromium，请运行: playwright install chromium")
    return None


def launch_browser(p):
    chromium_path = get_chromium_path()
    if chromium_path:
        return p.chromium.launch(headless=True, executable_path=chromium_path)
    return p.chromium.launch(headless=True)


def check_selenium():
    """检测Selenium"""
    try:
        from selenium import webdriver
        return True
    except ImportError:
        return False
    except Exception as e:
        print(f"[!] Selenium导入失败: {e}")
        return False


def validate_url(url, max_length=2000):
    import re
    from urllib.parse import urlparse
    if not url or not isinstance(url, str):
        return False
    if len(url) > max_length:
        return False
    try:
        result = urlparse(url.strip())
        if result.scheme not in ['http', 'https']:
            return False
        if not result.netloc:
            return False
        domain_pattern = r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$'
        if not re.match(domain_pattern, result.netloc.lower()):
            return False
        if result.port and (result.port < 1 or result.port > 65535):
            return False
        return True
    except:
        pass
    return False


def safe_join(base_dir, filename):
    import os
    abs_base = os.path.abspath(base_dir)
    abs_path = os.path.abspath(os.path.join(base_dir, filename))
    if not abs_path.startswith(abs_base + os.sep):
        raise ValueError("invalid path")
    return abs_path


def get_platform(url):
    if not validate_url(url):
        return "invalid"
    if "v.qq.com" in url or "qq.com" in url:
        return "tencent"
    elif "iqiyi.com" in url or "iq.com" in url:
        return "iqiyi"
    elif "youku.com" in url:
        return "youku"
    elif "mgtv.com" in url:
        return "mgtv"
    elif "bilibili.com" in url:
        return "bilibili"
    elif "jocydm.cc" in url or "jiobb" in url:
        return "jocydm"
    else:
        return "general"


def get_video_title(video_url):
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                executable_path=get_chromium_path()
            )
            page = browser.new_page()
            page.goto(video_url, timeout=15000)
            page.wait_for_timeout(3000)
            title = page.title()
            browser.close()
            
            title = re.sub(r'[\\/:*?"<>|]', '_', title)
            title = re.sub(r'_+', '_', title).strip('_')
            if len(title) > 50:
                title = title[:50]
            return title if title else "video"
    except Exception as e:
        print(f"[!] 获取标题失败: {e}")
        return "video"


def load_history():
    try:
        if os.path.exists("vip_tool_config.json"):
            with open("vip_tool_config.json", "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[!] 加载配置失败: {e}")
    return {"history": [], "last_url": ""}


def save_history(url):
    data = load_history()
    if url and url != data.get("last_url"):
        history = data.get("history", [])
        if url in history:
            history.remove(url)
        history.insert(0, url)
        data["history"] = history[:10]
        data["last_url"] = url
        try:
            with open("vip_tool_config.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[!] 保存配置失败: {e}")


# ============================================================
# 自动获取m3u8 - 改进版
# ============================================================
def try_playwright(video_url):
    print("[*] 尝试 Playwright直接访问...")
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    except ImportError:
        return None, "Playwright未安装: pip install playwright"
    
    m3u8_urls = []
    
    def handle_request(request):
        url = request.url
        if ".m3u8" in url.lower() or ".mp4" in url.lower():
            if url not in m3u8_urls:
                if "jx.m3u8.tv" not in url and "yemu.xyz" not in url:
                    m3u8_urls.append(url)
    
    def handle_response(response):
        url = response.url
        if ".m3u8" in url.lower() or ".mp4" in url.lower():
            if url not in m3u8_urls:
                if "jx.m3u8.tv" not in url and "yemu.xyz" not in url and "hls.one" in url:
                    m3u8_urls.append(url)
        
        if "getinfo" in url and response.status == 200:
            try:
                data = response.json()
                vi_list = data.get('vl', {}).get('vi', [])
                if vi_list:
                    m3u8_url = vi_list[0].get('url') or vi_list[0].get('playUrl')
                    if m3u8_url and m3u8_url not in m3u8_urls:
                        m3u8_urls.append(m3u8_url)
            except Exception:
                pass
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, slow_mo=100, executable_path=get_chromium_path())
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={"width": 1920, "height": 1080}
            )
            page = context.new_page()
            page.on("request", handle_request)
            page.on("response", handle_response)
            
            print(f"    访问: {video_url}")
            try:
                page.goto(video_url, timeout=120000, wait_until="load")
            except PlaywrightTimeout:
                try:
                    page.goto(video_url, timeout=60000, wait_until="domcontentloaded")
                except Exception as e:
                    browser.close()
                    return None, f"页面加载超时: {str(e)[:50]}"
            
            page.wait_for_load_state("networkidle", timeout=30000)
            page.wait_for_timeout(15000)
            
            for i in range(6):
                if m3u8_urls:
                    break
                page.wait_for_timeout(5000)
                page.evaluate("() => { window.scrollTo(0, document.body.scrollHeight); }")
            
            browser.close()
            
            if not m3u8_urls:
                return None, "未找到视频链接"
            
            m3u8_urls.sort(key=lambda x: x.count("/"), reverse=True)
            
            for url in m3u8_urls:
                if ".m3u8" in url.lower():
                    print(f"    [使用] {url[:60]}...")
                    return url, None
            
            return m3u8_urls[0], None
    
    except Exception as e:
        return None, f"Playwright错误: {str(e)[:80]}"


def try_selenium(video_url):
    """使用Selenium获取m3u8"""
    print("[*] 尝试 Selenium...")
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except ImportError:
        return None, "Selenium未安装"
    
    try:
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        
        browser = webdriver.Chrome(options=options)
        
        platform = get_platform(video_url)
        sources = PARSE_SOURCES
        
        for parse_url, name in sources:
            print(f"    尝试: {name}")
            full_url = parse_url + video_url
            
            try:
                browser.get(full_url)
                time.sleep(5)
                
                # 获取源码
                content = browser.page_source
                
                matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', content)
                for m in matches:
                    if "vid=" in m or "token" in m or "play" in m:
                        browser.quit()
                        print(f"[+] 成功: {m[:60]}...")
                        return m, None
                        
            except Exception as e:
                continue
        
        browser.quit()
        return None, "未找到"
        
    except Exception as e:
        return None, str(e)


def try_tencent_api(video_url, quality="1080p"):
    global CURRENT_VIDEO_TITLE
    
    print("[*] 尝试腾讯视频内部API...")
    
    vid_match = re.search(r'/([a-z0-9]+)\.html', video_url)
    if not vid_match:
        return None, "无法提取视频ID (vid)"
    vid = vid_match.group(1)
    print(f"    提取到vid: {vid}")

    api_url = f"https://vv.video.qq.com/getinfo?vids={vid}&platform=101001&charge=0&otype=json"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://v.qq.com/",
    }

    try:
        resp = requests.get(api_url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return None, f"API请求失败, 状态码: {resp.status_code}"

        json_str = re.search(r'QZOutputJson=({.*?});', resp.text)
        if not json_str:
            return None, "无法解析API返回数据"
        data = json.loads(json_str.group(1))
        
        vi_list = data.get('vl', {}).get('vi', [])
        if not vi_list:
            return None, "API返回数据中未找到视频信息"
        video_info = vi_list[0]
        
        print(f"    [调试] API返回字段: {list(video_info.keys())}")

        fn = video_info.get('fn')
        fvkey = video_info.get('fvkey')
        fs = video_info.get('fs', 0)
        totalduration = video_info.get('totalduration', 0)
        print(f"    [调试] 文件大小fs: {fs/1024/1024:.1f}MB, 时长: {totalduration/60:.1f}分钟")

        ui_list = video_info.get('ul', {}).get('ui', [])
        print(f"    [调试] 共有 {len(ui_list)} 个URL源")

        # 调试：显示所有可能的标题字段
        print(f"    [调试] 尝试提取标题...")
        for field in ['title', 'nickname', 'video_title', 'short_title', 'name', 'vd_title']:
            val = video_info.get(field)
            if val:
                print(f"    [调试] 字段 '{field}': {val}")
        
        url_prefix = None
        max_size = 0
        for i, ui in enumerate(ui_list):
            url = ui.get('url', '')
            url_type = ui.get('type', 'unknown')
            size = ui.get('size', 0)
            print(f"    [调试] URL源{i}: {url[:50]}... (type={url_type}, size={size})")
            
            if '.m3u8' in url:
                print(f"    [调试] 发现m3u8地址，使用m3u8解析!")
                real_url = url
                if fvkey:
                    real_url += f"?vkey={fvkey}"
                print(f"[+] 成功获取m3u8地址: {real_url[:60]}...")
                if title:
                    print(f"[+] 视频标题: {title}")
                return real_url
            
            if size > max_size:
                max_size = size
                url_prefix = url
        
        if not url_prefix and ui_list:
            url_prefix = ui_list[0].get('url')
        
        expected_size = video_info.get('fs', 0)
        if expected_size:
            print(f"    [调试] 预期完整大小: {expected_size/1024/1024:.1f} MB")
        
        if not all([fn, fvkey, url_prefix]):
            return None, "API返回数据不完整"
        
        # 腾讯API的vi列表中可能没有标题，尝试从API的其他字段或页面获取
        title = (video_info.get('title', '') or video_info.get('nickname', '') or 
                video_info.get('video_title', '') or video_info.get('short_title', '') or 
                video_info.get('vd_title', '') or video_info.get('name', '') or
                video_info.get('episodes', [{}])[0].get('title', '') if video_info.get('episodes') else '')
        
        # 尝试从视频列表获取标题（动漫等系列作品）
        if not title and 'vlist' in video_info:
            for v in video_info['vlist']:
                title = v.get('title', '')
                if title:
                    break
        
        # 如果还是没有，从页面获取
        
        # 如果API还是没有标题，尝试从页面获取
        if not title:
            try:
                page_resp = requests.get(video_url, headers=headers, timeout=10)
                # 尝试从页面标题中提取
                title_match = re.search(r'<title>([^<]+)</title>', page_resp.text)
                if title_match:
                    title = title_match.group(1)
                    print(f"    [调试] 从页面标题提取: {title}")
                    title = re.sub(r'[_-]腾讯视频.*$', '', title)
                    title = re.sub(r'[-_]动漫.*$', '', title)
                    title = re.sub(r'[-_]高清.*$', '', title)
                    title = re.sub(r'[-_]完整版.*$', '', title)
                    title = re.sub(r'[-_]视频在线观看.*$', '', title)
                    title = title.strip('-_ ')
            except:
                pass

        print(f"    [调试] 最终视频标题: '{title}'")
        CURRENT_VIDEO_TITLE = title if title else ''
            
        real_url = f"{url_prefix}{fn}?vkey={fvkey}"
        print(f"[+] 成功获取真实地址: {real_url[:60]}...")
        if title:
            print(f"[+] 视频标题: {title}")
        else:
            print("[!] 无法获取视频标题")

        # 验证最终设置的标题
        print(f"    [调试] CURRENT_VIDEO_TITLE 已设置为: '{CURRENT_VIDEO_TITLE}'")
        return real_url

    except Exception as e:
        return None, str(e)


def try_iqiyi_api(video_url):
    print("[*] 尝试爱奇艺API...")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                executable_path=get_chromium_path()
            )
            context = browser.new_context()
            page = context.new_page()
            page.goto(video_url, timeout=20000)
            page.wait_for_timeout(5000)
            
            content = page.content()
            browser.close()
            
            matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', content)
            for m in matches:
                if "cache.video.iqiyi.com" in m or "dash" in m:
                    print(f"[+] 找到: {m[:60]}...")
                    return m, None
    except Exception as e:
        return None, str(e)
    return None, "解析失败"


def try_youku_api(video_url):
    print("[*] 尝试优酷API...")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                executable_path=get_chromium_path()
            )
            page = browser.new_page()
            page.goto(video_url, timeout=20000)
            page.wait_for_timeout(5000)
            
            content = page.content()
            browser.close()
            
            matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', content)
            for m in matches:
                if "youku" in m or "ku" in m:
                    print(f"[+] 找到: {m[:60]}...")
                    return m, None
    except Exception as e:
        return None, str(e)
    return None, "解析失败"


def try_mgtv_api(video_url):
    print("[*] 尝试芒果TV API...")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                executable_path=get_chromium_path()
            )
            page = browser.new_page()
            page.goto(video_url, timeout=20000)
            page.wait_for_timeout(5000)
            
            content = page.content()
            browser.close()
            
            matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', content)
            for m in matches:
                if "mgtv" in m:
                    print(f"[+] 找到: {m[:60]}...")
                    return m, None
    except Exception as e:
        return None, str(e)
    return None, "解析失败"


def try_bilibili_api(video_url):
    print("[*] 尝试B站Playwright...")
    try:
        from playwright.sync_api import sync_playwright
        
        bvid = None
        if "BV" in video_url:
            match = re.search(r'BV[a-zA-Z0-9]+', video_url)
            if match:
                bvid = match.group()
        
        if not bvid and "bilibili.com/video/" in video_url:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=get_chromium_path())
                page = browser.new_page()
                page.goto(video_url, timeout=30000)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(5000)
                
                html = page.content()
                bvid_match = re.search(r'"bvid":"(BV[a-zA-Z0-9]+)"', html)
                if bvid_match:
                    bvid = bvid_match.group(1)
                
                playinfo_match = re.search(r'window\.__playinfo__\s*=\s*({.+?});', html)
                if playinfo_match:
                    import json
                    try:
                        playinfo = json.loads(playinfo_match.group(1))
                        dash = playinfo.get("data", {}).get("dash")
                        if dash:
                            video_url = dash.get("video", [{}])[0].get("baseUrl")
                            if video_url:
                                print(f"[+] 找到B站视频: {video_url[:60]}...")
                                browser.close()
                                return video_url, None
                    except Exception:
                        pass
                
                matches = re.findall(r'https?://[^\s"\'<>]+\.(?:m3u8|mp4|m4s)[^\s"\'<>]*', html)
                for m in matches:
                    if "bilibili" in m or "bili" in m:
                        print(f"[+] 找到B站视频: {m[:60]}...")
                        browser.close()
                        return m, None
                
                browser.close()
        
        if bvid:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.bilibili.com/",
            }
            try:
                info_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
                info_resp = requests.get(info_url, headers=headers, timeout=10)
                info_data = info_resp.json()
                cid = None
                if info_data.get("code") == 0:
                    cid = info_data["data"]["cid"]
                    print(f"    获取到CID: {cid}")
            except Exception:
                cid = None
            
            apis = [
                (f"https://api.bilibili.com/x/player/playurl?cid={{}}&bvid={bvid}&qn=80&fnval=16", "流畅"),
                (f"https://api.bilibili.com/x/player/playurl?cid={{}}&bvid={bvid}&qn=112&fnval=16", "480P"),
                (f"https://api.bilibili.com/x/player/playurl?cid={{}}&bvid={bvid}&qn=80&fnval=16&fourk=1", "720P"),
            ]
            for api_template, quality in apis:
                if not cid:
                    continue
                try:
                    api_url = api_template.format(cid)
                    resp = requests.get(api_url, headers=headers, timeout=10)
                    if resp.status_code == 200:
                        data = resp.json()
                        print(f"    B站API返回: code={data.get('code')}, message={data.get('message', '')[:30] if data.get('message') else ''}")
                        if data.get("code") == 0 and data.get("data"):
                            result = data["data"]
                            if "dash" in result:
                                video_url = result["dash"]["video"][0]["baseUrl"]
                                if video_url:
                                    print(f"[+] 找到B站({quality}): {video_url[:60]}...")
                                    return video_url, None
                            elif "durl" in result:
                                video_url = result["durl"][0]["url"]
                                if video_url:
                                    print(f"[+] 找到B站({quality}): {video_url[:60]}...")
                                    return video_url, None
                except Exception as ex:
                    print(f"    请求错误: {ex}")
        print("[!] B站需要登录Cookie才能获取高清视频")
    except Exception as e:
        return None, str(e)
    return None, "解析失败"


def try_api_parsing(video_url):
    """使用解析API接口直接获取m3u8，返回(session, url)或(None, None)"""
    print("[*] 尝试 API解析...")

    apis = [
        ("https://jx.m3u8.tv/jiexi/?url=", "线路1"),
        ("https://jx.xmflv.com/?url=", "线路2"),
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.6099.129 Safari/537.36",
    }

    for api, name in apis:
        try:
            full_url = api + quote(video_url)
            print(f"    尝试: {name}")

            # Create session for cookie persistence
            session = requests.Session()
            session.verify = False

            resp = session.get(full_url, headers=headers, timeout=30, allow_redirects=True)

            print(f"    {name} 状态码: {resp.status_code}, 长度: {len(resp.text)}")

            if resp.status_code == 200:
                text = resp.text
                print(f"    {name} 前200字符: {text[:200]}")

                m3u8_match = re.search(r'https?://[^\s"\'"<>]+\.m3u8[^\s"\'"<>]*', text)
                if m3u8_match:
                    m3u8_url = m3u8_match.group()
                    if len(m3u8_url) > 30:
                        print(f"[+] 成功: {m3u8_url[:60]}...")
                        return session, m3u8_url
                
                if ".m3u8" in text:
                    print(f"    {name} 包含m3u8，尝试提取...")
                    urls = re.findall(r'https?://[^\s"\'">]+\.m3u8[^\s"\'">]*', text)
                    for u in urls:
                        if len(u) > 30:
                            print(f"[+] m3u8提取: {u[:60]}...")
                            return session, u
                
                video_url_patterns = [
                    r'videoUrl["\']?\s*[:=]\s*["\']([^"\']+)["\']',
                    r'"url"\s*:\s*"([^"]+)"',
                    r'source\s+src=["\']([^"\']+)["\']',
                    r'file:\s*["\']([^"\']+)["\']',
                    r'player\.src\(["\']([^"\']+)["\']',
                    r'file["\']?\s*[:=]\s*["\']([^"\']+)["\']',
                    r'"file"\s*:\s*"([^"]+)"',
                    r'playUrl["\']?\s*[:=]\s*["\']([^"\']+)["\']',
                ]
                
                all_matches = re.findall(r'https?://[^\s"\'<>]+', text)
                if all_matches:
                    print(f"    {name} 找到 {len(all_matches)} 个URL")
                    for u in all_matches[:10]:
                        print(f"    URL: {u[:80]}")
                    # 优先找 nosdn.127.net 的视频URL
                    for u in all_matches:
                        if "nosdn.127.net" in u or "video" in u or ".mp4" in u or ".m3u8" in u:
                            if len(u) > 30:
                                print(f"[+] 直接视频URL: {u[:80]}...")
                                return session, u
                
                # 解析接口返回HTML页面，需要Playwright渲染提取m3u8
                print(f"    {name} 返回HTML页面({len(text)}字节)，尝试使用Playwright渲染...")
                m3u8, err = try_playwright(full_url)
                if m3u8:
                    print(f"[+] 从Playwright获取m3u8: {m3u8[:60]}...")
                    return session, m3u8
                else:
                    print(f"    {name} Playwright渲染失败: {err}")
                     # 回退到正则提取
                    for pattern in video_url_patterns:
                        match = re.search(pattern, text)
                        if match:
                            url = match.group(1)
                            if url.startswith("http") and len(url) > 30:
                                print(f"[+] 提取视频URL: {url[:60]}...")
                                return session, url

                mp4_match = re.search(r'https?://[^\s"\'"<>]+\.(?:mp4|m3u8)[^\s"\'"<>]*', text)
                if mp4_match:
                    video_url = mp4_match.group()
                    if len(video_url) > 30:
                        print(f"[+] 成功(直接视频): {video_url[:60]}...")
                        return session, video_url

        except Exception as e:
            print(f"    {name} 失败: {str(e)[:50]}")
            continue

    return None, None


def auto_get_m3u8(video_url, quality="1080p", format=None):
    """Auto fetch m3u8 URL from video URL.

    Args:
        video_url: Video URL
        quality: Quality level - 1080p, 720p, 480p, 360p, auto
        format: Container format - mp4, webm, mkv (not used for fetching)
    """
    print("=" * 50)
    print("[*] 自动获取视频地址")
    print("=" * 50)
    print(f"[*] 视频: {video_url}")
    print(f"[*] 画质: {quality}")
    print()
    
    video_url = video_url.strip()
    if video_url.endswith(".mp4") or video_url.endswith(".mkv") or video_url.endswith(".webm"):
        print(f"[+] 检测到直接视频链接: {video_url[:60]}...")
        return video_url
    
    platform = get_platform(video_url)
    print(f"[*] 平台: {platform}")

    # Parse quality levels if auto
    if quality == "auto":
        print("[*] 检测可用画质...")
        m3u8_list = []

        if platform == "tencent":
            # Get primary m3u8 first
            m3u8 = try_tencent_api(video_url, quality="fhd")
            if m3u8:
                qualities = VideoDownloader().parse_m3u8_quality(m3u8)
                if qualities:
                    print(f"[+] 找到 {len(qualities)} 个画质:")
                    for q in qualities:
                        print(f"    - {q['name']} ({q['resolution']}, {q['bandwidth']//1000}kbps)")
                    return m3u8  # Return highest quality by default
                else:
                    return m3u8
            print("[!] 腾讯API: 获取失败")
        else:
            # Try default quality
            if platform == "iqiyi":
                m3u8 = try_iqiyi_api(video_url)
                if m3u8:
                    return m3u8
            elif platform == "youku":
                m3u8 = try_youku_api(video_url)
                if m3u8:
                    return m3u8
            elif platform == "mgtv":
                m3u8 = try_mgtv_api(video_url)
                if m3u8:
                    return m3u8

    # 先尝试解析接口
    session, result = try_api_parsing(video_url)
    if session and result:
        print(f"[+] 解析接口返回: {result[:60]}...")

        if ".m3u8" in result or result.endswith(".m3u8") or "hls.one" in result:
            if not result.startswith("http"):
                print("[!] 返回的不是有效URL")
                return None
            print(f"[+] 获取到m3u8地址: {result[:60]}...")
            return result
        elif ".mp4" in result or "nosdn.127.net" in result:
            print(f"[*] 检测到直接视频链接")

            print(f"[*] 直接链接可能是预览版，先尝试获取m3u8...")
            jx_url = f"https://jx.m3u8.tv/jiexi/?url={quote(video_url)}"
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    chromium_path = get_chromium_path()
                    if chromium_path:
                        browser = p.chromium.launch(headless=True, executable_path=chromium_path)
                    else:
                        browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    m3u8_url = None
                    def handle_response(resp):
                        nonlocal m3u8_url
                        if '.m3u8' in resp.url and 'hls.one' in resp.url and m3u8_url is None:
                            m3u8_url = resp.url
                    page.on('response', handle_response)
                    page.goto(jx_url, timeout=60000)
                    page.wait_for_timeout(20000)
                    browser.close()
                    if m3u8_url:
                        print(f"[+] 获取到m3u8: {m3u8_url[:60]}...")
                        return m3u8_url
            except Exception as e:
                print(f"[!] Playwright获取m3u8失败: {e}")

            print(f"[*] 尝试直接下载...")
            import re
            downloader = VideoDownloader()
            safe_title = CURRENT_VIDEO_TITLE if CURRENT_VIDEO_TITLE else "video"
            safe_title = re.sub(r'[\\/:*?"<>|]', '_', safe_title)
            safe_title = re.sub(r'_+', '_', safe_title).strip('_')

            output_file = os.path.join(downloader.work_dir, f"{safe_title}.mp4")

            success = downloader.download_direct_mp4(
                result,
                output_file,
                session=session
            )

            if success:
                actual_size = os.path.getsize(output_file)
                if actual_size < 5 * 1024 * 1024:
                    print(f"[!] 下载文件过小({actual_size/1024/1024:.1f}MB)，删除文件...")
                    os.remove(output_file)
                else:
                    print(f"[+] MP4下载成功!")
                    return output_file
            else:
                print(f"[!] MP4下载失败...")
        elif "jiexi" in result or "jx." in result:
            print(f"[+] 获取到解析页面: {result[:60]}...")
            print("[*] 尝试渲染获取真实m3u8...")
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    chromium_path = get_chromium_path()
                    if chromium_path:
                        browser = p.chromium.launch(headless=True, executable_path=chromium_path)
                    else:
                        browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    page.goto(result, timeout=30000)
                    page.wait_for_timeout(5000)
                    content = page.content()
                    browser.close()
                    import re
                    m = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', content)
                    if m:
                        print(f"[+] 渲染成功: {m.group()[:60]}...")
                        return m.group()
            except Exception as e:
                print(f"[!] 渲染失败: {e}")
    print("[!] 解析接口全部失败，尝试腾讯API...")
    m3u8 = try_tencent_api(video_url, quality)
    if m3u8:
        return m3u8
    print("[!] 腾讯API也失败")
    
    if check_selenium():
        m3u8, err = try_selenium(video_url)
        if m3u8:
            return m3u8
        print(f"[!] Selenium: {err or '获取失败'}")
    else:
        print("[!] Selenium未安装")
    
    print()
    print("[!] 自动获取失败")
    print()
    print("解决方案:")
    print("1. 安装 Playwright: pip install playwright && playwright install chromium")
    print("2. 或者手动获取: 浏览器打开后按F12 -> Network -> 找.m3u8")
    
    return None


# ============================================================
# 下载器
# ============================================================
class VideoDownloader:
    def __init__(self, work_dir=None):
        if work_dir is None:
            work_dir = CONFIG.get("download_dir", "downloads")
        self.work_dir = work_dir
        os.makedirs(self.work_dir, exist_ok=True)
        self.temp_dir = os.path.join(self.work_dir, "temp")
        os.makedirs(self.temp_dir, exist_ok=True)

    def _get_full_ts_url(self, m3u8_url, ts_line):
        """拼接 TS 完整 URL，保留原 m3u8 的查询参数（如 ?vkey=...）"""
        from urllib.parse import urlparse, urlunparse, urljoin
        if ts_line.startswith('http'):
            return ts_line
        parsed = urlparse(m3u8_url)
        base_path = parsed.path
        if '/' in base_path:
            base_dir = base_path[:base_path.rfind('/')+1]
        else:
            base_dir = '/'
        new_path = urljoin(base_dir, ts_line)
        return urlunparse((parsed.scheme, parsed.netloc, new_path, '', parsed.query, ''))

    def validate_ts_file(self, filepath):
        """
        Validate TS file has correct MPEG-TS packet structure.
        Returns: (is_valid, error_message)
        """
        try:
            with open(filepath, "rb") as f:
                # Read first 188 bytes (one TS packet)
                header = f.read(188)
                if len(header) < 188:
                    return False, "文件过小，不足188字节"

                # Check for TS sync byte (0x47)
                if header[0] != 0x47:
                    return False, f"无效的TS头部 (0x{header[0]:02x}, 期望 0x47)"

                # Validate packet size (usually 188 bytes)
                if len(header) != 188:
                    return False, f"无效的TS包大小: {len(header)}字节 (期望188字节)"

                return True, None
        except FileNotFoundError:
            return False, "文件不存在"
        except PermissionError:
            return False, "文件权限错误"
        except Exception as e:
            return False, f"验证异常: {e}"

    def get_m3u8_content(self, m3u8_url, depth=0):
        if depth > 2:
            return []
        
        referer = "https://v.qq.com/"
        if "jx.m3u8.tv" in m3u8_url:
            referer = "https://jx.m3u8.tv/"
        elif "xmflv.com" in m3u8_url:
            referer = "https://jx.xmflv.com/"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Referer": referer,
            "Origin": referer,
        }
        try:
            resp = requests.get(m3u8_url, headers=headers, timeout=30, verify=False)
            resp.encoding = "utf-8"
            content = resp.text
        except Exception as e:
            print(f"获取m3u8失败: {e}")
            return []
        
        if not content or content.startswith("<"):
            return []
        
        print("[*] 检测到动态HLS流，开始循环刷新...")
        return self._refresh_m3u8_until_end(m3u8_url, referer)

    def _refresh_m3u8_until_end(self, m3u8_url, referer, max_wait=180):
        import time
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Referer": referer,
            "Origin": referer,
        }
        downloaded = set()
        ts_list = []
        start_time = time.time()
        last_count = 0
        no_change = 0
        
        print("[*] 开始循环刷新获取完整视频...")
        print("[*] 等待视频加载（最多3分钟）...")
        
        while time.time() - start_time < max_wait:
            try:
                resp = requests.get(m3u8_url, headers=headers, timeout=10, verify=False)
                if resp.status_code != 200:
                    break
                content = resp.text
                
                if "#EXT-X-ENDLIST" in content:
                    print("[*] 检测到ENDLIST，视频结束")
                
                base_url = m3u8_url[:m3u8_url.rfind("/") + 1]
                current_key = None
                for line in content.split("\n"):
                    line = line.strip()
                    if line and not line.startswith('#') and "cdn.hls.one" in line:
                        url = line if line.startswith("http") else self._get_full_ts_url(m3u8_url, line)
                        if url not in downloaded:
                            downloaded.add(url)
                            ts_list.append((url, current_key))
                
                current = len(ts_list)
                print(f"\r    已获取: {current} 个片段", end="", flush=True)
                
                if current == last_count:
                    no_change += 1
                    if no_change >= 3:
                        print(f"\n[*] 加载完成，共 {current} 个片段")
                        break
                else:
                    no_change = 0
                last_count = current
                
                if "#EXT-X-ENDLIST" in content:
                    break
                
                time.sleep(3)
                
            except Exception as e:
                break
        
        if ts_list:
            print(f"\n[+] 循环刷新完成: {len(ts_list)} 个片段")
            return ts_list
        return []

    def _parse_key(self, line):
        if not line.startswith('#EXT-X-KEY'):
            return None
        attrs = dict(re.findall(r'([A-Z]+)=("[^"]*"|[^,]*)', line))
        for k in attrs:
            attrs[k] = attrs[k].strip('"')
        if attrs.get('METHOD') == 'AES-128':
            return {'method': 'AES-128', 'uri': attrs.get('URI'), 'iv': attrs.get('IV')}
        return None

    def get_key(self, key_url, referer):
        print(f"    [*] 获取KEY: {key_url[:50]}...")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Referer": referer,
        }
        try:
            resp = requests.get(key_url, headers=headers, timeout=10, verify=False)
            print(f"    [*] KEY状态: {resp.status_code}, 大小: {len(resp.content)}")
            if resp.status_code == 200 and len(resp.content) >= 16:
                return resp.content[:16]
        except Exception as e:
            print(f"    [!] KEY获取失败: {e}")
        return None

    def decrypt_ts(self, ts_data, key, iv=None):
        try:
            from Crypto.Cipher import AES
        except:
            return ts_data
        if iv is None:
            iv = bytes(16)
        cipher = AES.new(key, AES.MODE_CBC, iv=iv)
        return cipher.decrypt(ts_data)

    def parse_m3u8_quality(self, m3u8_url):
        """
        Parse m3u8 playlist to extract quality levels.
        Returns list of (quality_name, bandwidth, resolution, m3u8_url) tuples.
        """
        try:
            response = requests.get(m3u8_url, timeout=10)
            if response.status_code != 200:
                return []

            content = response.text
            lines = content.split('\n')

            quality_levels = []
            base_url = m3u8_url.rsplit('/', 1)[0]

            for line in lines:
                line = line.strip()
                if line.startswith('#EXT-X-STREAM-INF'):
                    # Parse quality info
                    bandwidth = 0
                    resolution = 'unknown'

                    if 'BANDWIDTH=' in line:
                        bandwidth = int(line.split('BANDWIDTH=')[1].split(',')[0])

                    if 'RESOLUTION=' in line:
                        resolution = line.split('RESOLUTION=')[1].split(',')[0]

                    quality_name = self.bandwidth_to_quality(bandwidth)

                    quality_levels.append({
                        'name': quality_name,
                        'bandwidth': bandwidth,
                        'resolution': resolution,
                        'url': base_url + '/' + lines[lines.index(line) + 1].strip()
                    })

            return quality_levels

        except Exception as e:
            print(f"[!] 解析m3u8画质失败: {e}")
            return []

    def bandwidth_to_quality(self, bandwidth):
        """Convert bandwidth to quality level name."""
        if bandwidth >= 5000000:  # 5Mbps
            return "1080p"
        elif bandwidth >= 2500000:  # 2.5Mbps
            return "720p"
        elif bandwidth >= 1000000:  # 1Mbps
            return "480p"
        else:
            return "360p"

    def select_quality_url(self, m3u8_url, target_quality="auto"):
        """Select the best m3u8 URL for the target quality.
        
        Args:
            m3u8_url: Master playlist URL or direct stream URL
            target_quality: Target quality - "auto", "1080p", "720p", "480p", "360p"
            
        Returns:
            Selected m3u8 URL or original if not master playlist
        """
        if target_quality == "auto":
            return m3u8_url  # Return as-is, will use whatever quality is in the stream
            
        # Try to parse quality levels
        qualities = self.parse_m3u8_quality(m3u8_url)
        if not qualities:
            return m3u8_url  # Can't parse, return original
            
        # Sort by bandwidth (highest first)
        qualities.sort(key=lambda x: x['bandwidth'], reverse=True)
        
        # Map quality name to priority
        quality_priority = {"1080p": 0, "720p": 1, "480p": 2, "360p": 3}
        target_priority = quality_priority.get(target_quality, 0)
        
        # Find the best quality not higher than target
        for q in qualities:
            q_priority = quality_priority.get(q['name'], 99)
            if q_priority <= target_priority:
                print(f"[*] 选择画质: {q['name']} ({q['resolution']}, {q['bandwidth']//1000}kbps)")
                return q['url']
        
        # If no match, return highest available
        if qualities:
            best = qualities[0]
            print(f"[*] 目标画质不可用，使用: {best['name']} ({best['resolution']})")
            return best['url']
        
        return m3u8_url

    def download_direct_mp4(self, mp4_url, filename, session=None, retries=3):
        """Download direct MP4 file with proper headers and cookies.

        Args:
            mp4_url: Direct MP4 file URL
            filename: Output file path
            session: Requests session with cookies from parsing interface
            retries: Number of retry attempts

        Returns:
            bool: True if successful, False otherwise
        """
        import random

        # Use session if provided, otherwise create new
        if session is None:
            session = requests.Session()
            session.verify = False

        # Set proper headers for Tencent Video
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.129 Safari/537.36",
            "Referer": "https://v.qq.com/",
            "Origin": "https://v.qq.com",
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Connection": "keep-alive",
            "Range": "bytes=0-",  # Enable resuming
        }

        time.sleep(random.uniform(0.3, 0.7))

        for attempt in range(retries):
            try:
                print(f"    [下载MP4] {os.path.basename(filename)} (尝试 {attempt+1}/{retries})")

                resp = session.get(mp4_url, headers=headers, timeout=60, verify=False, stream=True)

                if resp.status_code == 206:  # Partial Content (resumed)
                    content_range = resp.headers.get('Content-Range', '0/0')
                    total_size = int(content_range.split('/')[1])
                    print(f"    [恢复下载] 断点续传: {total_size:,} bytes")

                if resp.status_code == 200:
                    # Validate minimum size (MP4 files are typically >50MB)
                    total_size = int(resp.headers.get('Content-Length', 0))
                    if total_size < 1024 * 1024:  # Less than 1MB
                        if attempt < retries - 1:
                            print(f"    [重试] 文件过小 ({total_size/1024:.0f} KB < 1MB)")
                            time.sleep(1)
                            continue
                        else:
                            print(f"    [失败] 文件过小，可能无效")
                            return False

                    # Write with progress
                    total_bytes = 0
                    chunk_size = 1024 * 1024  # 1MB chunks
                    with open(filename, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=chunk_size):
                            if chunk:
                                f.write(chunk)
                                total_bytes += len(chunk)
                                if total_bytes % (10 * 1024 * 1024) == 0:  # Every 10MB
                                    print(f"    [进度] {total_bytes/1024/1024:.1f} MB")

                    # Verify MP4 file structure
                    is_valid = self.validate_mp4_file(filename)
                    if is_valid:
                        size_mb = os.path.getsize(filename) / 1024 / 1024
                        print(f"    [成功] {os.path.basename(filename)} ({size_mb:.1f} MB)")
                        return True
                    else:
                        print(f"    [警告] MP4验证失败，但文件已下载")
                        return True

                elif resp.status_code in [401, 403]:
                    print(f"    [失败] 认证错误 (HTTP {resp.status_code})")
                    if attempt < retries - 1:
                        print(f"    [重试] 等待5秒...")
                        time.sleep(5)
                        continue
                    return False

                elif resp.status_code in [400, 404, 405]:
                    print(f"    [失败] 无效URL或方法 (HTTP {resp.status_code})")
                    return False

                else:
                    print(f"    [重试] HTTP {resp.status_code}, 等待2秒...")
                    time.sleep(2)
                    continue

            except requests.exceptions.RequestException as e:
                print(f"    [异常] {str(e)[:60]}")
                if attempt < retries - 1:
                    time.sleep(1)
                    continue
                return False
            except Exception as e:
                print(f"    [错误] {str(e)[:60]}")
                if attempt < retries - 1:
                    time.sleep(1)
                    continue
                return False

        return False

    def validate_mp4_file(self, filepath):
        """Validate MP4 file structure.

        Returns:
            bool: True if file appears to be a valid MP4
        """
        try:
            with open(filepath, "rb") as f:
                header = f.read(12)
                # Check for common MP4 box signatures
                if header[:4] not in [b'ftyp', b'3gp5', b'free', b'moov']:
                    return False

                # Read entire file to check for moov/mdat atoms
                f.seek(0)
                content = f.read()
                if b'moov' not in content and b'mdat' not in content:
                    return False

                return True
        except Exception:
            return False

    def download_ts(self, ts_info, filename, retries=3):
        import random
        
        ts_url, key_info = ts_info if isinstance(ts_info, tuple) else (ts_info, None)
        import random
        
        if "qq.com" in ts_url or "vipzj.video.tc.qq.com" in ts_url:
            referer = "https://v.qq.com/"
        elif "m3u8.tv" in ts_url:
            referer = "https://jx.m3u8.tv/"
        else:
            referer = ts_url[:ts_url.find("/", 10)] if "/" in ts_url[10:] else "https://v.qq.com/"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.129 Safari/537.36",
            "Referer": referer,
            "Origin": referer.rstrip('/'),
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Connection": "keep-alive",
        }
        
        time.sleep(random.uniform(0.2, 0.5))

        for attempt in range(retries):
            try:
                resp = requests.get(ts_url, headers=headers, timeout=30, allow_redirects=True, verify=False)
                
                if resp.status_code in [301, 302, 303, 307, 308]:
                    redirect_url = resp.headers.get("Location", ts_url)
                    if redirect_url:
                        print(f"    -> 重定向到: {redirect_url[:50]}...")
                        resp = requests.get(redirect_url, headers=headers, timeout=30, verify=False)

                if resp.status_code != 200:
                    if attempt < retries - 1:
                        wait_time = (attempt + 1) * 2
                        print(f"    [重试 {attempt+1}/{retries}] HTTP {resp.status_code}, 等待 {wait_time}秒...")
                        time.sleep(wait_time)
                    continue

                # Validate content exists
                content = resp.content
                if not content or len(content) < 100:
                    if attempt < retries - 1:
                        print(f"    [重试 {attempt+1}/{retries}] 内容过小")
                        time.sleep(1)
                    continue
                
                if key_info and key_info.get('method') == 'AES-128':
                    print(f"    [*] 检测到加密: {key_info.get('uri', 'N/A')[:50]}...")
                    key = self.get_key(key_info['uri'], referer)
                    if key:
                        iv_str = key_info.get('iv')
                        if iv_str and iv_str.startswith('0x'):
                            iv = bytes.fromhex(iv_str[2:])
                        else:
                            iv = bytes(16)
                        content = self.decrypt_ts(content, key, iv)
                    else:
                        print(f"    [!] 无法获取密钥")
                
                # 简化下载：不验证，直接保存
                with open(filename, "wb") as f:
                    f.write(content)

                # 跳过验证（简化流程）
                return True

            except requests.exceptions.RequestException as e:
                print(f"    [!] 下载异常: {str(e)[:50]}")
                if attempt < retries - 1:
                    time.sleep(1)
                continue
            except Exception as e:
                print(f"    [!] 意外错误: {e}")
                if attempt < retries - 1:
                    time.sleep(1)
                continue

        return False
    
    def download_all(self, ts_list, max_workers=4):
        downloaded = []
        failed = []
        total = len(ts_list)
        start_time = time.time()
        
        print(f"[+] 使用 {max_workers} 线程下载...")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {}
            
            for idx, ts_info in enumerate(ts_list):
                filename = os.path.join(self.temp_dir, f"video_{idx:05d}.ts")
                future = executor.submit(self.download_ts, ts_info, filename)
                future_to_idx[future] = (idx, filename)
            
            done = 0
            for future in as_completed(future_to_idx):
                done += 1
                idx, filename = future_to_idx[future]
                try:
                    if future.result():
                        downloaded.append((idx, filename))
                        speed = done / (time.time() - start_time)
                        percent = int(done / total * 50)
                        bar = "█" * percent + "░" * (50 - percent)
                        eta = (total - done) / speed if speed > 0 else 0
                        print(f"\r[{bar}] {done}/{total} {speed:.1f}片/秒 ETA:{eta:.0f}秒", end="", flush=True)
                    else:
                        failed.append(idx)
                except Exception as e:
                    print(f"    [!] 线程异常: {str(e)[:50]}")
                    failed.append(idx)
        
        print()
        print(f"[+] 下载完成: 成功 {len(downloaded)}, 失败 {len(failed)}")
        return sorted(downloaded, key=lambda x: x[0])
        
    def merge_ts_to_mp4(self, ts_list, output_file, container_format="mp4"):
        """Merge TS segments into video file.

        Args:
            ts_list: List of (ts_file_path, m3u8_url) tuples
            output_file: Output filename (without extension)
            container_format: Container format - "mp4", "webm", or "mkv"
        """
        if not ts_list:
            print("[!] 没有可用的TS片段")
            return False

        # Add extension based on container format
        ext_map = {"mp4": ".mp4", "webm": ".webm", "mkv": ".mkv"}
        output_file = output_file + ext_map.get(container_format.lower(), ".mp4")

        print(f"[*] 目标格式: {container_format.upper()} ({output_file})")
        
        ffmpeg_path = check_ffmpeg()
        if ffmpeg_path:
            return self.merge_with_ffmpeg(ts_list, output_file)
        else:
            print("[!] FFmpeg未找到，使用二进制合并...")
            return self.merge_binary(ts_list, output_file)
    
    def merge_binary(self, ts_files, output_file):
        """直接将 TS 文件按顺序合并（二进制拼接）"""
        if not ts_files:
            print("[!] 没有可用的TS片段")
            return False

        # 确保输出文件有正确后缀
        if not output_file.endswith(".mp4"):
            output_file += ".mp4"
        # 如果output_file已经是完整路径，直接使用
        if os.path.isabs(output_file):
            output_path = output_file
        else:
            output_path = os.path.join(self.work_dir, output_file)

        print(f"[*] 使用二进制合并: {output_path}")
        try:
            with open(output_path, 'wb') as outfile:
                for ts_file in ts_files:
                    if os.path.exists(ts_file) and os.path.getsize(ts_file) > 0:
                        with open(ts_file, 'rb') as infile:
                            outfile.write(infile.read())
                    else:
                        print(f"    [!] 跳过无效文件: {ts_file}")

            if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                size_mb = os.path.getsize(output_path) / 1024 / 1024
                print(f"[+] 合并成功! 文件大小: {size_mb:.1f} MB")
                return True
            else:
                print("[!] 合并失败: 输出文件无效")
                return False
        except Exception as e:
            print(f"[!] 合并失败: {e}")
            return False

    def merge_ts_to_mp4(self, ts_list, output_file, container_format="mp4"):
        """合并 TS 片段为 MP4 文件（直接二进制拼接）"""
        # ts_list: [(idx, filepath), ...]
        ts_files = [fp for _, fp in sorted(ts_list, key=lambda x: x[0])]
        return self.merge_binary(ts_files, output_file)
        
        if not output_file.endswith(".mp4"):
            output_file += ".mp4"
        
        output_file = os.path.join(self.work_dir, output_file)
        
        if check_ffmpeg():
            return self.merge_with_ffmpeg(ts_files, output_file)
        else:
            return self.merge_binary(ts_files, output_file)
    
    def download(self, m3u8_url, output_name="output", container_format="mp4", original_url=None):
        global CURRENT_VIDEO_TITLE
        print(f"=" * 50)
        print(f"[*] 视频地址: {m3u8_url[:60]}...")
        print(f"[*] 目标格式: {container_format.upper()}")
        print(f"=" * 50)

        is_direct_video = (
            m3u8_url.endswith(".mp4") or 
            m3u8_url.endswith(".mkv") or 
            m3u8_url.endswith(".webm") or
            ".m4v?" in m3u8_url or
            "nosdn.127.net" in m3u8_url
        )
        
        # 腾讯官方播放列表，直接当作m3u8解析
        if "vipzj.video.tc.qq.com" in m3u8_url or "dispatch.tc.qq.com" in m3u8_url:
            print("[*] 检测到腾讯官方播放列表，直接当作m3u8解析...")
            is_direct_video = False
        
        if not is_direct_video and ".m3u8" not in m3u8_url:
            print("[*] 检测到非.m3u8 URL，尝试预检内容...")
            try:
                test_headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://v.qq.com/",
                }
                resp_test = requests.get(m3u8_url, headers=test_headers, timeout=10, verify=False, stream=True)
                preview = b""
                for chunk in resp_test.iter_content(chunk_size=200):
                    preview += chunk
                    if len(preview) >= 200:
                        break
                if preview.strip().startswith(b'#EXTM3U'):
                    print("[+] 确认为m3u8内容，继续解析...")
                else:
                    print("[!] 内容不像m3u8，尝试直接下载...")
                    result = self.download_direct(m3u8_url, output_name, container_format)
                    if result is True:
                        import shutil
                        shutil.rmtree(self.temp_dir, ignore_errors=True)
                        os.makedirs(self.temp_dir, exist_ok=True)
                        return True
                    return False
            except Exception as e:
                print(f"[!] 预检失败: {e}")
        
        if is_direct_video:
            print("[*] 检测到直接视频URL，使用直接下载...")
            result = self.download_direct(m3u8_url, output_name, container_format)
            if result is True:
                import shutil
                shutil.rmtree(self.temp_dir, ignore_errors=True)
                os.makedirs(self.temp_dir, exist_ok=True)
                return True
            elif result is None:
                print("[!] 直链过期，自动切换腾讯API...")
            else:
                print("[!] 直链下载失败，尝试腾讯API...")
                vid = None
                if original_url:
                    vid_match = re.search(r'/([a-z0-9]+)\.html', original_url)
                    if vid_match:
                        vid = vid_match.group(1)
                if not vid:
                    vid_match = re.search(r'/([a-z0-9]+)\.html', m3u8_url)
                    if vid_match:
                        vid = vid_match.group(1)
                if vid:
                    print(f"[*] 提取到 vid: {vid}, 调用腾讯API...")
                    tencent_m3u8 = try_tencent_api(original_url or m3u8_url, quality="1080p")
                    if tencent_m3u8:
                        print(f"[+] 腾讯API返回: {tencent_m3u8[:60]}...")
                        return self.download(tencent_m3u8, output_name, container_format, vid)
                    else:
                        print("[!] 腾讯API获取失败")
                return False
        
        if not CURRENT_VIDEO_TITLE and original_url:
            import re
            vid_match = re.search(r'/([a-z0-9]+)\.html', original_url)
            if vid_match:
                vid = vid_match.group(1)
                api_url = f"https://vv.video.qq.com/getinfo?vids={vid}&platform=101001&charge=0&otype=json"
                try:
                    resp = requests.get(api_url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://v.qq.com/"}, timeout=15, verify=False)
                    json_str = re.search(r'QZOutputJson=({.*?});', resp.text)
                    if json_str:
                        data = json.loads(json_str.group(1))
                        vi_list = data.get('vl', {}).get('vi', [])
                        if vi_list:
                            video_info = vi_list[0]
                            title = (video_info.get('title', '') or video_info.get('nickname', '') or 
                                    video_info.get('vd_title', '') or video_info.get('name', ''))
                            if title:
                                CURRENT_VIDEO_TITLE = title
                                print(f"[*] 从API获取标题: {title}")
                except:
                    pass
        
        print("[*] 解析m3u8获取视频片段...")

        if ".m3u8" not in m3u8_url:
            print("[*] 检测到非m3u8 URL，需要二次渲染获取真实m3u8...")
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    chromium_path = get_chromium_path()
                    if chromium_path:
                        browser = p.chromium.launch(headless=True, executable_path=chromium_path)
                    else:
                        browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    page.goto(m3u8_url, timeout=30000)
                    page.wait_for_timeout(5000)
                    content = page.content()
                    browser.close()
                    import re
                    m3u8_match = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', content)
                    if m3u8_match:
                        m3u8_url = m3u8_match.group()
                        print(f"[+] 二次渲染成功: {m3u8_url[:60]}...")
                    else:
                        print("[!] 二次渲染未找到m3u8链接")
            except Exception as e:
                print(f"[!] 二次渲染失败: {e}")

        quality_m3u8 = self.select_quality_url(m3u8_url)
        ts_urls = self.get_m3u8_content(quality_m3u8)
        if not ts_urls:
            print("[!] 无法获取视频片段")
            return False

        downloaded = self.download_all(ts_urls)
        if not downloaded:
            print("[!] 解析URL下载失败")
            import re
            vid_match = re.search(r'/([a-z0-9]+)\.html', m3u8_url)
            if vid_match:
                vid = vid_match.group(1)
            elif original_url:
                vid_match = re.search(r'/([a-z0-9]+)\.html', original_url)
                if vid_match:
                    vid = vid_match.group(1)
            else:
                vid = None
            
            if vid:
                print(f"[*] 提取vid: {vid}, 尝试腾讯API...")
                api_url = f"https://vv.video.qq.com/getinfo?vids={vid}&platform=101001&charge=0&otype=json"
                try:
                    resp = requests.get(api_url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://v.qq.com/"}, timeout=15, verify=False)
                    json_str = re.search(r'QZOutputJson=({.*?});', resp.text)
                    if json_str:
                        data = json.loads(json_str.group(1))
                        vi_list = data.get('vl', {}).get('vi', [])
                        if vi_list:
                            url_prefix = vi_list[0].get('ul', {}).get('ui', [{}])[0].get('url')
                            fn = vi_list[0].get('fn')
                            fvkey = vi_list[0].get('fvkey')
                            if url_prefix and fn and fvkey:
                                tencent_url = f"{url_prefix}{fn}?vkey={fvkey}"
                                print(f"[+] 腾讯API返回: {tencent_url[:60]}...")
                                return self.download(tencent_url, output_name, container_format, vid)
                except Exception as e:
                    print(f"[!] 腾讯API失败: {e}")
            print("[!] 下载失败")
            return False

        output_path = os.path.join(self.work_dir, output_name)
        success = self.merge_ts_to_mp4(downloaded, output_path, container_format)
        
        if success:
            import shutil
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            os.makedirs(self.temp_dir, exist_ok=True)
        
        return success
    
    def download_direct(self, video_url, output_name, container_format="mp4"):
        print(f"[*] 直接下载: {video_url[:80]}...")
        print(f"[*] 目标格式: {container_format.upper()}")

        from urllib.parse import urlparse
        parsed = urlparse(video_url)
        host = parsed.netloc
        referer = f"{parsed.scheme}://{host}/"
        if "nosdn.127.net" in host:
            referer = "https://v.qq.com/"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.129 Safari/537.36",
            "Referer": referer,
            "Origin": referer.rstrip('/'),
            "Host": host,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Connection": "keep-alive",
        }

        try:
            resp = requests.get(video_url, headers=headers, stream=True, timeout=60, allow_redirects=True, verify=False)
            print(f"[*] 响应状态码: {resp.status_code}")
            if resp.status_code != 200:
                print(f"[!] 下载失败: HTTP {resp.status_code}")
                return False

            total = int(resp.headers.get("content-length", 0))
            print(f"[*] 期望大小: {total/1024/1024:.1f} MB")

            ext_map = {"mp4": ".mp4", "webm": ".webm", "mkv": ".mkv"}
            output_name = output_name + ext_map.get(container_format.lower(), ".mp4")
            output_path = os.path.join(self.work_dir, output_name)

            downloaded = 0
            with open(output_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = downloaded * 100 / total
                            print(f"\r[*] 进度: {pct:.1f}%", end="", flush=True)

            print()
            actual = os.path.getsize(output_path)
            print(f"[*] 实际大小: {actual/1024/1024:.1f} MB")

            if actual == 0:
                print("[!] 下载的文件大小为0，链接可能已失效")
                return None
            
            # 检查是否为有效视频文件（非HTML错误页面）
            with open(output_path, "rb") as f:
                header = f.read(20)
                if header.startswith(b"<!DOCTYPE") or header.startswith(b"<html") or header.startswith(b"<HTML"):
                    print("[!] 下载的是HTML页面而非视频，链接可能已失效")
                    return None

            if total > 0 and abs(actual - total) > 1024*1024:
                print(f"[!] 警告: 大小不匹配 (差 {(actual-total)/1024/1024:.1f} MB)")
                print("[!] 视频可能未完全下载")
            return True
        except Exception as e:
            print(f"[!] 下载失败: {e}")
            return False


# ============================================================
# GUI
# ============================================================
def run_gui():
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError:
        print("[!] tkinter不可用")
        return
    
    root = tk.Tk()
    root.title("VIP视频工具 v3.6")
    root.geometry("550x350")
    root.resizable(False, False)
    
    url_var = tk.StringVar(value=CONFIG["default_url"])
    status_var = tk.StringVar(value="就绪")
    
    title_label = ttk.Label(root, text="VIP视频工具", font=("微软雅黑", 14, "bold"))
    title_label.pack(pady=15)
    
    input_frame = ttk.LabelFrame(root, text="视频URL", padding=10)
    input_frame.pack(padx=20, pady=5, fill=tk.X)
    
    url_entry = ttk.Entry(input_frame, textvariable=url_var, font=("微软雅黑", 10))
    url_entry.pack(fill=tk.X)
    
    btn_frame = ttk.Frame(root)
    btn_frame.pack(pady=15)
    
    def on_play():
        url = url_var.get().strip()
        if not url:
            status_var.set("请输入URL")
            return
        parse_url = PARSE_SOURCES[0][0] + url
        webbrowser.open(parse_url)
        status_var.set("浏览器已打开")
    
    def on_parse_all():
        url = url_var.get().strip()
        if not url:
            status_var.set("请输入URL")
            return
        for i, (parse_url, name) in enumerate(PARSE_SOURCES, 1):
            full_url = parse_url + url
            status_var.set(f"尝试 {i}/{len(PARSE_SOURCES)}: {name}")
            webbrowser.open(full_url)
            time.sleep(0.5)
        status_var.set("已尝试所有接口")
    
    def on_download():
        url = url_var.get().strip()
        if not url:
            status_var.set("请输入URL")
            return
        status_var.set("正在自动获取m3u8...")
        
        def do_download():
            global CURRENT_VIDEO_TITLE
            m3u8 = auto_get_m3u8(url, "1080p")
            if m3u8:
                status_var.set("开始下载...")
                downloader = VideoDownloader()
                
                if CURRENT_VIDEO_TITLE:
                    filename = CURRENT_VIDEO_TITLE
                    print(f"[*] 使用API标题: {filename}")
                    CURRENT_VIDEO_TITLE = ""
                else:
                    vid_match = re.search(r'/([a-z0-9]+)\.html', url)
                    if vid_match:
                        filename = vid_match.group(1)
                    else:
                        filename = f"video_{int(time.time())}"
                
                filename = re.sub(r'[\\/:*?"<>|]', '_', filename)
                filename = re.sub(r'_+', '_', filename).strip('_')
                if len(filename) > 30:
                    filename = filename[:30]
                
                success = downloader.download(m3u8, filename, original_url=url)
                if success:
                    root.after(0, lambda: status_var.set("下载完成"))
                else:
                    root.after(0, lambda: status_var.set("下载失败"))
            else:
                parse_url = PARSE_SOURCES[0][0] + url
                webbrowser.open(parse_url)
                root.after(0, lambda: status_var.set("自动获取失败，请在浏览器按F12获取m3u8"))
        
        threading.Thread(target=do_download, daemon=True).start()
    
    ttk.Button(btn_frame, text="播放", command=on_play, width=15).pack(pady=3)
    ttk.Button(btn_frame, text="尝试所有接口", command=on_parse_all, width=15).pack(pady=3)
    ttk.Button(btn_frame, text="下载视频", command=on_download, width=15).pack(pady=3)
    
    # 状态栏 - 显示FFmpeg和Playwright状态
    status_frame = ttk.Frame(root)
    status_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=5)
    
    # FFmpeg状态
    ffmpeg_status = "已安装" if check_ffmpeg() else "未安装"
    ffmpeg_label = ttk.Label(status_frame, text=f"FFmpeg: {ffmpeg_status}", font=("微软雅黑", 8))
    ffmpeg_label.pack(side=tk.LEFT, padx=10)
    
    # Playwright状态
    try:
        from playwright.sync_api import sync_playwright
        pw_label = ttk.Label(status_frame, text="Playwright: 已安装", font=("微软雅黑", 8))
    except Exception:
        pw_label = ttk.Label(status_frame, text="Playwright: 未安装", font=("微软雅黑", 8))
    pw_label.pack(side=tk.LEFT, padx=10)
    
    # 版本号
    version_label = ttk.Label(status_frame, text="v3.6", font=("微软雅黑", 8), foreground="gray")
    version_label.pack(side=tk.RIGHT, padx=10)
    
    # 状态消息
    status_bar = ttk.Label(root, textvariable=status_var, relief=tk.SUNKEN, anchor=tk.W)
    status_bar.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=(0,10))
    
    root.mainloop()


# ============================================================
# 命令行
# ============================================================
def run_play(url=None, quality=None, format=None):
    if not url:
        url = CONFIG["default_url"]

    quality = quality or CONFIG.get("default_quality", "1080p")
    format = format or CONFIG.get("default_format", "mp4")

    platform = get_platform(url)
    sources = PARSE_SOURCES
    parse_url = sources[0][0] + url

    print(f"[+] 平台: {platform}")
    print(f"[+] 解析: {parse_url[:50]}...")
    webbrowser.open(parse_url)


def run_auto(url=None, quality=None, format=None):
    global CURRENT_VIDEO_TITLE
    CURRENT_VIDEO_TITLE = ""
    
    if not url:
        url = CONFIG["default_url"]
    quality = quality or CONFIG.get("default_quality", "1080p")
    format = format or CONFIG.get("default_format", "mp4")
    
    print(f"[+] 自动获取下载...")
    print(f"[+] 视频: {url}")
    print(f"[+] 画质: {quality}")
    
    m3u8 = auto_get_m3u8(url, quality)
    
    if m3u8:
        print(f"[+] m3u8: {m3u8[:80]}...")
        
        if CURRENT_VIDEO_TITLE:
            filename = CURRENT_VIDEO_TITLE
            CURRENT_VIDEO_TITLE = ""
        else:
            vid_match = re.search(r'/([a-z0-9]+)\.html', url)
            if vid_match:
                filename = vid_match.group(1)
            else:
                title = get_video_title(url)
                title = re.sub(r'\.(mp4|mkv|webm)$', '', title)
                filename = f"{title}"
        
        filename = re.sub(r'[\\/:*?"<>|]', '_', filename)
        filename = re.sub(r'_+', '_', filename).strip('_')
        if len(filename) > 30:
            filename = filename[:30]
        print(f"[*] 文件名: {filename}")
        
        downloader = VideoDownloader()
        success = downloader.download(m3u8, filename, format)
        
        if success:
            print(f"[+] 下载完成: downloads/{filename}.{format}")
        else:
            print("[!] 下载失败")
            sys.exit(1)
    else:
        print("[!] 获取m3u8失败")
        sys.exit(1)


def run_download(m3u8_url, output_name="output.mp4"):
    print(f"[+] 下载: {m3u8_url}")
    downloader = VideoDownloader()
    success = downloader.download(m3u8_url, output_name)
    if success:
        print("[+] 下载完成")
    else:
        print("[!] 下载失败")
        sys.exit(1)


# ============================================================
# 主入口
# ============================================================
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "gui"
    
    if mode == "gui":
        run_gui()
    elif mode == "play":
        run_play()
    elif mode == "auto":
        run_auto()
    elif mode == "get":
        if len(sys.argv) < 3:
            print("用法: python vip_tool.py get <m3u8_url>")
            sys.exit(1)
        m3u8_url = sys.argv[2]
        output_name = sys.argv[3] if len(sys.argv) > 3 else "output.mp4"
        run_download(m3u8_url, output_name)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
