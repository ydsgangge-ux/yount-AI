"""
import_model.py — Live2D 模型一键导入

用法：
  python import_model.py 模型文件夹路径

或者直接把模型文件夹拖到本文件上（Windows）。
"""

import sys
import os
import shutil
import re

if sys.stdout.encoding.lower() in ("gbk", "gb2312"):
    sys.stdout.reconfigure(encoding="utf-8")

# ── 路径配置 ──
STATIC_DIR = os.path.join(os.path.dirname(__file__), "vrm_module", "static")
HTML_FILE  = os.path.join(STATIC_DIR, "live2d_pet.html")


# ── 工具函数 ──

def find_model_json(folder: str) -> str | None:
    """在文件夹中查找 .model3.json 或 .model.json（优先取根目录的）"""
    candidates = []
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if f.endswith(".model3.json") or f.endswith(".model.json"):
                candidates.append(os.path.join(root, f))
    if not candidates:
        return None
    # 优先选深度最浅的（越靠近根目录越好）
    depths = [len(p.replace(folder, "").split(os.sep)) for p in candidates]
    return candidates[depths.index(min(depths))]


def pick_name(folder: str) -> str:
    """从文件夹名生成模型名"""
    raw = os.path.basename(os.path.normpath(folder))
    # 去掉常见的后缀 _free _t02 _m01 _v1.0 等
    raw = re.sub(r"_(?:free|t\d{2}|m\d{2}|sp_\d+|v[\d.]+)$", "", raw, flags=re.IGNORECASE)
    if not raw:
        raw = "MyModel"
    return raw[0].upper() + raw[1:]  # 首字母大写


def add_to_html(name: str, url: str) -> None:
    """在 MODELS 数组末尾插入一条新记录"""
    with open(HTML_FILE, encoding="utf-8") as f:
        html = f.read()

    entry = f"""    {{
      name: "{name}",
      url: "{url}",
    }},
  ];

  // ── 互动台词 ──"""

    # 用可靠锚点替换
    old = """  ];

  // ── 互动台词 ──"""
    if old not in html:
        print("错误: 无法在 live2d_pet.html 中找到 MODELS 数组末尾，请手动添加。")
        print(f"   将以下内容加到 MODELS 数组最后：")
        print(f'    {{ name: "{name}", url: "{url}", }},')
        return False

    html = html.replace(old, entry)
    with open(HTML_FILE, "w", encoding="utf-8", newline="") as f:
        f.write(html)
    print(f"已注册到模型列表: {name}")
    return True


# ── 主流程 ──

def main():
    if len(sys.argv) < 2:
        print("用法: python import_model.py 模型文件夹路径")
        print("或者直接把模型文件夹拖到本文件上。\n")
        input("按回车退出…")
        return 1

    src = sys.argv[1].strip()
    if not os.path.isdir(src):
        print(f"❌ 路径不存在或不是文件夹: {src}")
        input("按回车退出…")
        return 1

    src = os.path.abspath(src)
    print(f"[文件夹] {src}")

    # 1. 找模型清单文件
    model_json = find_model_json(src)
    if not model_json:
        print("[错误] 未找到 .model3.json 或 .model.json 文件")
        print("  常见 Live2D 模型应包含 model3.json 文件。")
        input("按回车退出…")
        return 1
    print(f"[模型文件] {os.path.basename(model_json)}")

    # 2. 确定模型名
    name = pick_name(src)
    dest = os.path.join(STATIC_DIR, name)

    if os.path.exists(dest):
        print(f"[警告] 目标文件夹已存在: {dest}")
        ch = input("  覆盖? (y/n): ").strip().lower()
        if ch == "y":
            shutil.rmtree(dest)
        else:
            print("[取消]")
            input("按回车退出…")
            return 1

    # 3. 复制
    print(f"[复制中] ...")
    shutil.copytree(src, dest)
    print(f"[完成] 复制到 {dest}")

    # 4. 计算相对 URL（相对于 HTML 文件）
    dest_model_json = os.path.join(dest, os.path.relpath(model_json, src))
    rel_url = os.path.relpath(dest_model_json, STATIC_DIR).replace("\\", "/")

    # 5. 注册到 HTML
    ok = add_to_html(name, rel_url)
    if not ok:
        pass

    print(f"\n[导入完成] 模型名: {name}")
    print(f"  刷新浏览器 http://127.0.0.1:8900/live2d_pet.html")
    print(f"  点右下角 [↻] 按钮切换到 {name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())