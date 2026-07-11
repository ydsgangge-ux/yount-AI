"""
ComfyUI 生成 SimLife 异世界角色立绘
二次元风格，256x512，纯白背景
"""
import json
import os
import time
import urllib.request
from pathlib import Path

COMFY_URL = "http://127.0.0.1:8188"
OUTPUT_DIR = Path(r"d:\AB方案\yount-AI-main\simlife\frontend\assets\char\fantasy")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

QUALITY = "masterpiece, best quality, highly detailed, anime style, 2d illustration, fantasy RPG character, vibrant colors, beautiful, white background, full body, facing viewer"

CHARACTERS = [
    # 女性冒险者
    ("char_female_idle.png", "1girl, cute anime girl, long brown hair braided, green eyes, fantasy adventurer outfit, leather armor with cape, belt with pouches, standing idle pose, arms at sides, gentle smile"),
    ("char_female_walk.png", "1girl, cute anime girl, long brown hair braided, green eyes, fantasy adventurer outfit, leather armor with cape, walking pose, one foot forward, dynamic movement"),
    ("char_female_sit.png", "1girl, cute anime girl, long brown hair braided, green eyes, fantasy adventurer outfit, leather armor with cape, sitting on bench pose, relaxed posture"),
    ("char_female_talk.png", "1girl, cute anime girl, long brown hair braided, green eyes, fantasy adventurer outfit, leather armor with cape, talking pose, hand gesture, cheerful expression"),
    ("char_female_think.png", "1girl, cute anime girl, long brown hair braided, green eyes, fantasy adventurer outfit, leather armor with cape, thinking pose, hand on chin, contemplative"),
    # 男性冒险者
    ("char_male_idle.png", "1boy, handsome anime boy, short dark blue hair, blue eyes, fantasy warrior outfit, light plate armor with sword at hip, standing idle pose, cool expression"),
    ("char_male_walk.png", "1boy, handsome anime boy, short dark blue hair, blue eyes, fantasy warrior outfit, light plate armor with sword at hip, walking pose, confident stride"),
    ("char_male_sit.png", "1boy, handsome anime boy, short dark blue hair, blue eyes, fantasy warrior outfit, light plate armor with sword at hip, sitting on bench pose, relaxed"),
    ("char_male_talk.png", "1boy, handsome anime boy, short dark blue hair, blue eyes, fantasy warrior outfit, light plate armor with sword at hip, talking pose, friendly smile"),
    ("char_male_think.png", "1boy, handsome anime boy, short dark blue hair, blue eyes, fantasy warrior outfit, light plate armor with sword at hip, thinking pose, serious expression"),
]


def make_workflow(prompt_text, seed):
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_turbo_1.0_fp16.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": f"{prompt_text}, {QUALITY}", "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "3d, realistic, photo, western cartoon, ugly, deformed, blurry, low quality, bad anatomy, multiple characters, text, watermark, dark background, landscape, scene, nsfw, modern clothes", "clip": ["1", 1]}},
        "4": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": 4, "cfg": 1.5, "sampler_name": "lcm", "scheduler": "normal", "denoise": 1.0, "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["5", 0]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 256, "height": 512, "batch_size": 1}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["4", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "simlife_fantasy_char", "images": ["6", 0]}}
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
    print(f"=== SimLife 异世界角色立绘生成 ===")
    print(f"模型: SDXL Turbo | 风格: anime/fantasy RPG | 尺寸: 256x512 | 角色: {len(CHARACTERS)}")

    ok = 0
    fail = 0
    for i, (filename, prompt) in enumerate(CHARACTERS):
        save_path = OUTPUT_DIR / filename
        if save_path.exists():
            print(f"[{i+1}/{len(CHARACTERS)}] {filename} - skip")
            ok += 1
            continue

        print(f"[{i+1}/{len(CHARACTERS)}] {filename} ...", end=" ", flush=True)
        try:
            pid = queue_prompt(make_workflow(prompt, 400 + i))
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
