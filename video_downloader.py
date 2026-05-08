#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频解析下载工具
功能：输入腾讯视频URL，解析m3u8地址，播放或下载视频
依赖：pip install playwright && playwright install
      需要安装 ffmpeg 并添加到环境变量
"""

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import tkinter.ttk as ttk
import subprocess
import threading
import webbrowser
import re
import os
import sys
import glob
from urllib.parse import quote

def get_chromium_path():
    user_path = os.path.expanduser("~")
    base = os.path.join(user_path, "AppData", "Local", "ms-playwright")
    pattern = os.path.join(base, "chromium_headless_shell-*", "chrome-headless-shell-win64", "chrome-headless-shell.exe")
    matches = glob.glob(pattern)
    if matches:
        matches.sort(reverse=True)
        return matches[0]
    pattern2 = os.path.join(base, "chromium-*", "chrome-win64", "chrome.exe")
    matches = glob.glob(pattern2)
    if matches:
        matches.sort(reverse=True)
        return matches[0]
    pattern3 = os.path.join(base, "chromium", "chrome-win", "chrome.exe")
    if os.path.exists(pattern3):
        return pattern3
    return None

# ========== 配置 ==========
解析接口列表 = [
    "https://jx.m3u8.tv/jiexi/?url=",
    "https://jx.xmflv.com/?url="
]

# 获取脚本所在目录的 Videos 文件夹
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEOS_FOLDER = os.path.join(SCRIPT_DIR, "Videos")

# 确保 Videos 文件夹存在
if not os.path.exists(VIDEOS_FOLDER):
    os.makedirs(VIDEOS_FOLDER)


class VideoDownloaderApp:
    """视频解析下载工具主类"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("视频解析下载工具")
        self.root.geometry("700x500")
        self.root.resizable(True, True)
        
        # 变量
        self.m3u8_url = ""
        self.save_path = VIDEOS_FOLDER  # 默认保存到 Videos 文件夹
        self.playwright = None
        self.browser = None
        
        # 创建界面
        self.create_widgets()
        
    def create_widgets(self):
        """创建界面组件"""
        # 标题
        title_label = tk.Label(self.root, text="视频解析下载工具", 
                              font=("微软雅黑", 18, "bold"))
        title_label.pack(pady=10)
        
        # URL 输入区域
        input_frame = tk.Frame(self.root)
        input_frame.pack(fill=tk.X, padx=20, pady=5)
        
        tk.Label(input_frame, text="输入腾讯视频 URL:", font=("微软雅黑", 11)).pack(anchor=tk.W)
        
        self.url_entry = tk.Entry(input_frame, font=("微软雅黑", 10), width=50)
        self.url_entry.pack(fill=tk.X, pady=5)
        
        # 按钮区域
        button_frame = tk.Frame(self.root)
        button_frame.pack(fill=tk.X, padx=20, pady=10)
        
        self.play_btn = tk.Button(button_frame, text="播放", 
                                   command=self.play_video,
                                   font=("微软雅黑", 10),
                                   bg="#4CAF50", fg="white",
                                   width=12, height=1)
        self.play_btn.pack(side=tk.LEFT, padx=5)
        
        self.download_btn = tk.Button(button_frame, text="下载", 
                                       command=self.download_video,
                                       font=("微软雅黑", 10),
                                       bg="#2196F3", fg="white",
                                       width=12, height=1)
        self.download_btn.pack(side=tk.LEFT, padx=5)
        
        self.select_btn = tk.Button(button_frame, text="选择保存目录", 
                                     command=self.select_save_path,
                                     font=("微软雅黑", 10),
                                     width=12, height=1)
        self.select_btn.pack(side=tk.LEFT, padx=5)
        
        # 保存路径显示
        path_frame = tk.Frame(self.root)
        path_frame.pack(fill=tk.X, padx=20, pady=5)
        
        tk.Label(path_frame, text="保存目录 (Videos 文件夹):", font=("微软雅黑", 10)).pack(anchor=tk.W)
        self.path_label = tk.Label(path_frame, text=self.save_path, 
                                   font=("微软雅黑", 9), fg="gray",
                                   anchor=tk.W, bg="#f0f0f0", relief=tk.SUNKEN)
        self.path_label.pack(fill=tk.X, pady=2)
        
        # 清理临时文件按钮
        cleanup_frame = tk.Frame(self.root)
        cleanup_frame.pack(fill=tk.X, padx=20, pady=5)
        
        self.cleanup_btn = tk.Button(cleanup_frame, text="清理临时文件", 
                                      command=self.cleanup_temp_files,
                                      font=("微软雅黑", 9),
                                      width=15, height=1)
        self.cleanup_btn.pack(anchor=tk.W)
        
        # 下载进度条
        progress_frame = tk.Frame(self.root)
        progress_frame.pack(fill=tk.X, padx=20, pady=5)
        
        # 进度条样式 - 使用ttk主题
        style = ttk.Style()
        style.theme_use('default')
        style.configure("Horizontal.TProgressbar", thickness=20, background='#4CAF50')
        
        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate', 
                                          length=300, style="Horizontal.TProgressbar")
        self.progress_bar.pack(fill=tk.X, pady=5)
        
        # 进度详细信息标签
        self.progress_label = tk.Label(progress_frame, text="等待下载...", 
                                    font=("微软雅黑", 10), fg="#666")
        self.progress_label.pack(anchor=tk.W)
        
        # 状态显示区域
        status_frame = tk.Frame(self.root)
        status_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        tk.Label(status_frame, text="解析状态:", font=("微软雅黑", 11)).pack(anchor=tk.W)
        
        self.status_text = scrolledtext.ScrolledText(status_frame, 
                                                      font=("Consolas", 9),
                                                      height=12)
        self.status_text.pack(fill=tk.BOTH, expand=True)
        
    def log(self, message):
        """在状态窗口显示消息"""
        self.status_text.insert(tk.END, message + "\n")
        self.status_text.see(tk.END)
        self.root.update()
        
    def update_status(self, message):
        """更新状态（线程安全）"""
        self.root.after(0, lambda: self.log(message))
        
    def select_save_path(self):
        """选择保存目录"""
        path = filedialog.askdirectory(initialdir=self.save_path)
        if path:
            self.save_path = path
            self.path_label.config(text=self.save_path)
            
    def cleanup_temp_files(self):
        """清理临时文件 (.ts 片段和 .m3u8 文件)"""
        try:
            count = 0
            for file in os.listdir(self.save_path):
                if file.endswith('.ts') or file.endswith('.m3u8'):
                    file_path = os.path.join(self.save_path, file)
                    try:
                        os.remove(file_path)
                        count += 1
                    except Exception as e:
                        self.update_status(f"清理失败 {file}: {str(e)}")
            
            if count > 0:
                messagebox.showinfo("清理完成", f"已清理 {count} 个临时文件")
            else:
                messagebox.showinfo("清理完成", "没有临时文件需要清理")
                
        except Exception as e:
            messagebox.showerror("清理失败", f"清理失败: {str(e)}")

    def parse_video(self, video_url):
        """解析视频 URL，获取 m3u8 地址"""
        from urllib.parse import quote
        from playwright.sync_api import sync_playwright

        found_m3u8 = None

        # 需要排除的解析接口域名
        exclude_domains = ["jx.m3u8.tv", "yemu.xyz", "xmflv.com", "jx.xmflv.com"]

        def on_request(request):
            nonlocal found_m3u8
            url = request.url.lower()
            # 排除解析接口域名
            if any(domain in url for domain in exclude_domains):
                return
            # 查找 m3u8 或 mp4 URL
            if ".m3u8" in url or url.endswith(".mp4"):
                if ".m3u8" in url or ".mp4" in url:
                    self.update_status(f"[请求] {url[:100]}")
                    found_m3u8 = url

        def on_response(response):
            nonlocal found_m3u8
            url = response.url.lower()
            # 排除解析接口域名
            if any(domain in url for domain in exclude_domains):
                return
            # 查找 m3u8 或 mp4 URL
            content_type = response.headers.get("content-type", "").lower()
            if ".m3u8" in url or "application/vnd.apple.mpegurl" in content_type or "audio" in content_type:
                self.update_status(f"[响应] {url[:100]}")
                found_m3u8 = url

        for parser_url in 解析接口列表:
            self.update_status(f"尝试解析接口: {parser_url}")
            try:
                encoded_url = quote(video_url, safe='/:')
                full_url = parser_url + encoded_url

                chromium_path = get_chromium_path()

                browser = None
                page = None
                try:
                    with sync_playwright() as p:
                        if chromium_path:
                            browser = p.chromium.launch(
                                headless=True,
                                executable_path=chromium_path,
                                slow_mo=100
                            )
                        else:
                            browser = p.chromium.launch(headless=True, slow_mo=100)

                        page = browser.new_page()
                        page.set_default_timeout(60000)

                        page.on("request", on_request)
                        page.on("response", on_response)

                        page.goto(full_url, timeout=45000)
                        page.wait_for_load_state("domcontentloaded", timeout=20000)

                        for _ in range(3):
                            page.evaluate("window.scrollBy(0, 500)")
                            page.wait_for_timeout(1000)

                        page.wait_for_timeout(5000)

                        if found_m3u8:
                            self.update_status(f"找到 m3u8: {found_m3u8[:100]}")
                            return found_m3u8
                finally:
                    if page:
                        try:
                            page.close()
                        except:
                            pass
                    if browser:
                        try:
                            browser.close()
                        except:
                            pass

            except Exception as e:
                self.update_status(f"接口解析失败: {str(e)}")
                continue

        return None

    def parse_video_thread(self, video_url):
        """在后台线程中解析视频"""
        try:
            self.update_status("开始解析视频...")
            self.update_status(f"输入URL: {video_url}")
            
            m3u8_url = self.parse_video(video_url)
            
            if m3u8_url:
                self.m3u8_url = m3u8_url
                self.update_status(f"解析成功!")
                self.update_status(f"m3u8地址: {m3u8_url[:80]}...")
                messagebox.showinfo("解析成功", "视频解析成功！可以播放或下载。")
            else:
                self.update_status("解析失败: 未能获取m3u8地址")
                messagebox.showerror("解析失败", "无法解析视频，请检查URL是否正确。")
                
        except Exception as e:
            self.update_status(f"解析出错: {str(e)}")
            messagebox.showerror("错误", f"解析出错: {str(e)}")
        finally:
            self.play_btn.config(state=tk.NORMAL)
            self.download_btn.config(state=tk.NORMAL)
            self.progress_bar['value'] = 0
            self.progress_label.config(text="")
            
    def play_video(self):
        """播放视频"""
        video_url = self.url_entry.get().strip()
        
        if not video_url:
            messagebox.showwarning("提示", "请输入视频URL")
            return
            
        # 先解析视频
        self.play_btn.config(state=tk.DISABLED)
        self.download_btn.config(state=tk.DISABLED)
        self.update_status("=" * 40)
        
        # 在新线程中解析
        thread = threading.Thread(target=self.parse_video_thread, 
                                  args=(video_url,),
                                  daemon=True)
        thread.start()
        
        # 等待解析完成后再播放（带超时，最多等待60秒）
        self._play_check_count = 0
        self.root.after(100, self._check_and_play)
        
    def _check_and_play(self):
        """检查解析是否完成，然后播放"""
        self._play_check_count = getattr(self, '_play_check_count', 0) + 1
        
        if self.m3u8_url:
            self.update_status("正在打开浏览器播放...")
            webbrowser.open(self.m3u8_url)
            self.update_status("浏览器已打开，如果未播放请检查URL")
            self.play_btn.config(state=tk.NORMAL)
            self.download_btn.config(state=tk.NORMAL)
        elif self._play_check_count > 120:
            # 超时（60秒）
            self.update_status("解析超时")
            self.play_btn.config(state=tk.NORMAL)
            self.download_btn.config(state=tk.NORMAL)
        else:
            # 继续等待
            self.root.after(500, self._check_and_play)
            
    def download_video(self):
        """下载视频"""
        video_url = self.url_entry.get().strip()
        
        if not video_url:
            messagebox.showwarning("提示", "请输入视频URL")
            return
            
        # 检查ffmpeg是否可用
        try:
            result = subprocess.run(["ffmpeg", "-version"], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                raise Exception("ffmpeg not found")
        except Exception:
            messagebox.showerror("错误", "未找到 ffmpeg，请确保已安装并添加到环境变量")
            return
            
        # 先解析视频
        self.play_btn.config(state=tk.DISABLED)
        self.download_btn.config(state=tk.DISABLED)
        self.update_status("=" * 40)
        
        # 在新线程中解析和下载
        thread = threading.Thread(target=self.download_video_thread, 
                                  args=(video_url,),
                                  daemon=True)
        thread.start()
        
    def download_video_thread(self, video_url):
        """在后台线程中下载视频"""
        try:
            self.progress_bar['value'] = 0
            self.progress_label.config(text="下载进度: 0%")
            self.update_status("开始解析视频...")
            m3u8_url = self.parse_video(video_url)
            
            if not m3u8_url:
                self.update_status("解析失败，无法获取m3u8地址")
                return
                
            self.m3u8_url = m3u8_url
            
            # 生成输出文件名
            video_name = self._extract_video_name(video_url)
            output_file = os.path.join(self.save_path, f"{video_name}.mp4")
            
            self.update_status(f"保存到: {output_file}")
            self.update_status("开始下载...")
            
            # 使用yt-dlp下载（直接用原始视频URL）
            from yt_dlp import YoutubeDL
            
            def progress_hook(d):
                if d['status'] == 'downloading':
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    downloaded = d.get('downloaded_bytes', 0)
                    speed = d.get('speed', 0)
                    eta = d.get('eta', 0)
                    
                    if total > 0:
                        percent = int(downloaded * 100 / total)
                        self.root.after(0, lambda p=percent: self.progress_bar.config(value=p))
                        
                        # 格式化进度信息
                        downloaded_mb = downloaded / 1024 / 1024
                        total_mb = total / 1024 / 1024
                        speed_kb = speed / 1024 if speed else 0
                        
                        # 构建详细进度文本
                        progress_text = f"{percent}% ({downloaded_mb:.1f}/{total_mb:.1f} MB)"
                        if speed_kb > 0:
                            progress_text += f" - {speed_kb:.1f} KB/s"
                        if eta and eta > 0:
                            progress_text += f" - 剩余{eta//60}分{eta%60}秒"
                        
                        self.root.after(0, lambda p=progress_text: self.progress_label.config(text=p))
                    elif downloaded > 0:
                        downloaded_mb = downloaded / 1024 / 1024
                        self.root.after(0, lambda m=downloaded_mb: self.progress_label.config(
                            text=f"已下载: {m:.1f} MB ({speed_kb:.1f} KB/s)"))
                        
                elif d['status'] == 'finished':
                    self.root.after(0, lambda: self.progress_label.config(
                        text=f"✓ 下载完成!"))
            
            ydl_opts = {
                'format': 'best',
                'outtmpl': output_file,
                'quiet': False,
                'no_warnings': False,
                'progress_hooks': [progress_hook],
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Referer': 'https://v.qq.com/',
                },
            }
            
            try:
                self.update_status("正在下载...")
                with YoutubeDL(ydl_opts) as ydl:
                    # 添加详细日志
                    self.update_status(f"下载URL: {video_url[:80]}...")
                    ydl.download([video_url])
                    
                if os.path.exists(output_file):
                    file_size = os.path.getsize(output_file)
                    self.update_status(f"下载完成，文件大小: {file_size} bytes")
                    if file_size > 1000:
                        self.update_status("下载完成!")
                        messagebox.showinfo("完成", f"视频已保存到:\n{output_file}")
                    else:
                        # 文件太小，可能是错误页面，读取内容诊断
                        try:
                            with open(output_file, 'r', encoding='utf-8', errors='ignore') as f:
                                content_preview = f.read(500)
                            self.update_status(f"下载失败: 文件太小({file_size} bytes)，可能是错误页面")
                            self.update_status(f"文件内容预览: {content_preview[:200]}")
                        except:
                            self.update_status(f"下载失败，文件不完整: {file_size} bytes")
                        if os.path.exists(output_file):
                            os.remove(output_file)
                        messagebox.showerror("下载失败", f"下载的文件太小({file_size} bytes)，可能是解析接口限制")
            except Exception as e:
                if os.path.exists(output_file):
                    os.remove(output_file)
                self.update_status(f"下载出错: {str(e)[:80]}")
                messagebox.showerror("下载失败", f"下载出错: {str(e)}")
                
        except Exception as e:
            self.update_status(f"下载出错: {str(e)}")
            messagebox.showerror("错误", f"下载出错: {str(e)}")
        finally:
            # 恢复进度条和按钮状态
            self.progress_bar['value'] = 0
            self.progress_label.config(text="")
            self.root.after(0, lambda: self.play_btn.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.download_btn.config(state=tk.NORMAL))
            
    def _extract_video_name(self, url):
        """从URL提取视频名称"""
        # 腾讯视频 URL 模式
        # 例如: https://v.qq.com/x/cover/mcv8hkc8zk8lnov/e4102pfd88z.html
        # 或: https://v.qq.com/x/page/c1234567890.html
        
        patterns = [
            # 匹配 /cover/xxx/yyy.html 或 /page/xxx.html
            r'/cover/[^/]+/([^/.]+)\.html',
            r'/page/[^/]+/([^/.]+)\.html',
            r'/cover/([^/.]+)\.html',
            r'/page/([^/.]+)\.html',
            # 匹配视频ID
            r'vid=([a-zA-Z0-9]+)',
            # 备用方案
            r'/([^/]+)\.html',
            r'[?&]id=([^&]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                name = match.group(1)
                # 清理文件名：只保留字母数字中文和短横线
                name = re.sub(r'[^\w\u4e00-\u9fff\-]', '', name)
                # 防止路径遍历攻击
                name = name.replace('..', '').replace('/', '').replace('\\', '')
                if name:
                    return name[:50]
                
        return "video"


def check_dependencies():
    """检查依赖是否已安装"""
    missing = []
    
    # 检查playwright
    try:
        import playwright
    except ImportError:
        missing.append("playwright")
        
    # 检查ffmpeg
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
    except Exception:
        missing.append("ffmpeg")
        
    return missing


def main():
    """主函数"""
    # 检查依赖
    missing = check_dependencies()
    if missing:
        print("缺少必要的依赖，请运行以下命令安装:")
        if "playwright" in missing:
            print("  pip install playwright")
            print("  playwright install")
        if "ffmpeg" in missing:
            print("  请安装 ffmpeg 并添加到环境变量")
        print("\n缺少的依赖:", ", ".join(missing))
        input("按回车键退出...")
        return
        
    # 创建GUI
    root = tk.Tk()
    app = VideoDownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()