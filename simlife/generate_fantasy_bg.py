"""
ComfyUI 生成 SimLife 异世界通用场景图
二次元风格，640x360
"""
import json
import os
import time
import urllib.request
from pathlib import Path

COMFY_URL = "http://127.0.0.1:8188"
OUTPUT_DIR = Path(r"d:\AB方案\yount-AI-main\simlife\frontend\assets\bg\fantasy")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

QUALITY = "masterpiece, best quality, highly detailed, anime style, 2d illustration, fantasy world, vibrant colors, beautiful scenery, no characters, no text"

SCENES = [
    # (文件名, prompt)
    ("town_square", "Medieval fantasy town square, cobblestone streets, merchant stalls with colorful awnings, fountain in center, half-timbered buildings, warm sunlight, anime background, no characters"),
    ("tavern", "Cozy medieval fantasy tavern interior, wooden tables and benches, fireplace with warm glow, bar counter with bottles, candlelit atmosphere, anime background, no characters"),
    ("forest", "Enchanted forest, tall ancient trees with glowing leaves, sunbeams through canopy, mossy ground, magical flowers, mystical atmosphere, anime background, no characters"),
    ("castle", "Grand fantasy castle interior, stone walls with banners, arched corridors, ornate chandeliers, red carpet, anime background, no characters"),
    ("magic_academy", "Magic academy classroom, floating books, purple crystal orbs, desks with potions, arcane symbols on chalkboard, magical ambient light, anime background, no characters"),
    ("dungeon", "Dark underground dungeon corridor, stone brick walls, torch lights, iron doors, mysterious glowing runes, ominous atmosphere, anime background, no characters"),
    ("market", "Fantasy marketplace, colorful tents and stalls, magical items on display, hanging lanterns, bustling street, warm evening light, anime background, no characters"),
    ("plains", "Wide fantasy grasslands, rolling green hills, distant mountains, clear blue sky with clouds, wildflowers, peaceful countryside, anime background, no characters"),
    ("lakeside", "Serene fantasy lake, crystal clear water reflecting mountains, small wooden dock, weeping willows, cherry blossom petals on water, anime background, no characters"),
    ("mountain_pass", "Mountain pass with snow-capped peaks, narrow winding path, stone bridge over gorge, eagles soaring, dramatic clouds, anime background, no characters"),
    ("shrine", "Ancient fantasy shrine, torii gate, stone lanterns, sacred tree with paper charms, moss-covered steps, spiritual atmosphere, anime background, no characters"),
    ("night_camp", "Fantasy campsite at night, campfire with sparks, tents under starry sky, full moon, fireflies, peaceful wilderness, anime background, no characters"),
]


def make_workflow(prompt_text, seed):
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_turbo_1.0_fp16.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": f"{prompt_text}, {QUALITY}", "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "characters, people, text, watermark, ugly, blurry, low quality, dark background, photo, realistic, 3d render, nsfw", "clip": ["1", 1]}},
        "4": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": 4, "cfg": 1.5, "sampler_name": "lcm", "scheduler": "normal", "denoise": 1.0, "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["5", 0]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 640, "height": 360, "batch_size": 1}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["4", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "simlife_fantasy", "images": ["6", 0]}}
    }


def queue_prompt(workflow):
    data = json.dumps({"prompt": workflow}).encode("utf-8")
    req = urllib.request.Request(f"{COMFY_URL}/prompt", data=data, headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read()).get("prompt_id")


def wait_and_download(prompt_id, save_path, timeout=90):
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = urllib.request.urlopen(f"{COMFY_URL}/history/{prompt_id}")
            history = json.loads(resp.read())
            if prompt_id in history:
                status = history[prompt_id].get("status", {})
                if status.get("completed") or status.get("status_str") == "success":
                    for nid, nout in history[prompt_id].get("outputs", {}).items():
                        if "images" in nout:
                            for img in nout["images"]:
                                params = f"filename={img['filename']}&subfolder={img.get('subfolder','')}&type=output"
                                r2 = urllib.request.urlopen(f"{COMFY_URL}/view?{params}")
                                with open(save_path, "wb") as f:
                                    f.write(r2.read())
                                return True
                    return False
                if status.get("status_str") == "error":
                    print(f"Error: {status}")
                    return False
        except Exception:
            pass
        time.sleep(1.5)
    print(f"Timeout ({timeout}s)")
    return False


def main():
    print(f"=== SimLife 异世界场景图生成 ===")
    print(f"模型: SDXL Turbo | 风格: anime/fantasy | 尺寸: 640x360 | 场景: {len(SCENES)}")

    ok = 0
    fail = 0
    for i, (name, prompt) in enumerate(SCENES):
        save_path = OUTPUT_DIR / f"{name}.png"
        if save_path.exists():
            print(f"[{i+1}/{len(SCENES)}] {name}.png - skip")
            ok += 1
            continue

        print(f"[{i+1}/{len(SCENES)}] {name}.png ...", end=" ", flush=True)
        try:
            pid = queue_prompt(make_workflow(prompt, 300 + i))
            if wait_and_download(pid, str(save_path)):
                sz = os.path.getsize(str(save_path)) // 1024
                print(f"OK ({sz}KB)")
                ok += 1
            else:
                print("FAIL")
                fail += 1
        except Exception as e:
            print(f"ERROR: {e}")
            fail += 1

    print(f"\n=== Done: {ok} ok, {fail} fail ===")


if __name__ == "__main__":
    main()
