"""
ComfyUI 批量生成 SimLife 背景图
SDXL Turbo 4步出图，640x360
"""
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

COMFY_URL = "http://127.0.0.1:8188"
OUTPUT_DIR = Path(r"d:\AB方案\yount-AI-main\simlife\frontend\assets\bg")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

STYLE = "pixel art style, 16-bit game background, retro game, no characters, no text, clean illustration, vibrant colors"

SCENES = [
    ("home_sleeping.png", "Cozy bedroom at night, dark room, moonlight through window casting soft glow, bed with white sheets and pillows, nightstand with small lamp, potted plant in corner, wooden floor"),
    ("home_morning.png", "Bright cozy home interior morning, kitchen area with counter and stove, warm sunlight streaming through window, wooden floor, clean modern apartment"),
    ("home_evening.png", "Cozy living room evening, TV on wooden stand, comfortable sofa, floor lamp with warm glow, window showing night sky, wooden floor"),
    ("home_working.png", "Home office desk setup with monitor and laptop, bookshelf with colorful books, window with daylight, warm room, wooden desk and chair"),
    ("commute_subway.png", "Subway train interior daytime, large windows showing blue sky, metal handrails hanging from ceiling, passenger seats along walls, LED route display panel"),
    ("commute_subway_night.png", "Subway train interior nighttime, dark outside windows, warm interior lights on, metal handrails, passenger seats, evening commute"),
    ("office_working.png", "Modern bright office interior, large glass windows with city skyline view, rows of desks with computer monitors, white walls, fluorescent lighting"),
    ("office_meeting.png", "Corporate meeting room, large wooden conference table, whiteboard with charts, office chairs, bright overhead lighting, glass partition wall"),
    ("office_lunch.png", "Office cafeteria interior, food service counter with menu sign above, round dining tables, warm lighting, clean modern design"),
    ("cafe.png", "Cozy cafe interior, wooden counter with espresso machine, chalkboard menu, small round tables with coffee cups, pendant lights, window with plants"),
    ("cafe_warm.png", "Cozy cafe warm golden evening ambient, soft warm lighting from pendant lamps, wooden interior, intimate atmosphere, sunset glow through window"),
    ("cafe_working.png", "Cafe interior with wooden table, laptop and coffee cup on table, warm ambient lighting, window view, cozy workspace"),
    ("park.png", "Beautiful city park, green grass lawn, large shade trees, winding walking path, wooden bench, colorful flowers, blue sky with clouds"),
    ("supermarket.png", "Modern supermarket interior, tall shelves filled with colorful products, fluorescent ceiling lights, clean aisles, price signs"),
    ("street.png", "City street with buildings, shop signs and windows, crosswalk on road, street lamp, wide sidewalk, blue sky, urban downtown"),
    ("office_night.png", "Dark office at night, only desk lamp and computer monitor casting blue glow, city night lights through large window, empty workspace"),
    ("outdoor_working.png", "Outdoor nature scene, green meadow with camera on tripod, distant city buildings, trees, blue sky with clouds"),
    ("studio_working.png", "Creative studio room, desk with dual monitors and mixing console, speakers with LED lights, dark ambient, purple mood lighting"),
    ("airport.png", "Airport terminal interior, large glass windows showing sky, departure flight information board, gate signs, rows of seats, modern architecture"),
    ("touring.png", "Famous landmark temple pagoda with curved roof, blue sky, stone walking path, street lamp, green trees, tourist destination"),
    ("hotel.png", "Hotel room interior, large comfortable bed with white sheets, nightstand with lamp, window with city night view, desk area"),
    ("local_food.png", "Asian street food market, red and gold lanterns hanging, food stalls with wooden counters and steam rising, warm lighting"),
    ("scenic_drive.png", "Scenic mountain highway, winding road with lane markings, green rolling hills, blue sky with clouds, distant mountain peaks"),
    ("restaurant.png", "Elegant restaurant interior, wooden tables with settings and candles, menu board on wall, warm pendant lights, cozy atmosphere"),
    ("train_station.png", "Grand train station concourse, large round clock on wall, digital departure board with green text, wooden benches, high arched ceiling"),
]


def queue_prompt(workflow):
    data = json.dumps({"prompt": workflow}).encode("utf-8")
    req = urllib.request.Request(
        f"{COMFY_URL}/prompt", data=data,
        headers={"Content-Type": "application/json"}
    )
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
                    print(f"  Error: {status}")
                    return False
        except Exception:
            pass
        time.sleep(1.5)
    print(f"  Timeout ({timeout}s)")
    return False


def make_workflow(prompt_text, seed):
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_turbo_1.0_fp16.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": f"{prompt_text}, {STYLE}", "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "characters, people, person, text, watermark, blurry, low quality, 3d render, photo, realistic, ugly", "clip": ["1", 1]}},
        "4": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": 4, "cfg": 1.5, "sampler_name": "lcm", "scheduler": "normal", "denoise": 1.0, "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["5", 0]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 640, "height": 360, "batch_size": 1}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["4", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "simlife_bg", "images": ["6", 0]}}
    }


def main():
    print(f"=== SimLife 背景图批量生成 ===")
    print(f"模型: SDXL Turbo (4步 LCM) | 尺寸: 640x360 | 场景: {len(SCENES)}")

    ok = 0
    fail = 0
    for i, (filename, prompt) in enumerate(SCENES):
        save_path = OUTPUT_DIR / filename
        if save_path.exists():
            print(f"[{i+1}/{len(SCENES)}] {filename} - skip (exists)")
            ok += 1
            continue

        print(f"[{i+1}/{len(SCENES)}] {filename} ...", end=" ", flush=True)
        try:
            pid = queue_prompt(make_workflow(prompt, 42 + i))
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
