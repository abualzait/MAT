import os
import sys
import math
import json
import time
import random
import urllib.request
import urllib.error
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Setup directories
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
TILES_DIR = os.path.join(WORKSPACE_DIR, "tiles")
SCRATCH_DIR = os.path.join(WORKSPACE_DIR, "scratch")

os.makedirs(TILES_DIR, exist_ok=True)

# Helper for coordinates to tile numbers
def deg2num(lat_deg, lon_deg, zoom):
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return (xtile, ytile)

# Gather points from dataset files
def get_amman_coordinates():
    points = []
    for fn in ["amman_areas_database.json", "fetched_stations.json", "fetched_landmarks.json", "fetched_neighborhoods.json"]:
        fp = os.path.join(SCRATCH_DIR, fn)
        if os.path.exists(fp):
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                    items = data if isinstance(data, list) else data.get("elements", [])
                    for item in items:
                        lat = item.get("lat") or (item.get("center", {}).get("lat"))
                        lon = item.get("lon") or (item.get("center", {}).get("lon"))
                        if lat and lon and (31.5 <= float(lat) <= 32.3) and (35.5 <= float(lon) <= 36.4):
                            points.append((float(lat), float(lon)))
            except Exception as e:
                print(f"Notice: Could not load coordinates from {fn}: {e}")
    # Always ensure central Amman coordinates are included
    points.append((31.9515694, 35.9239625)) # Abdali / Central Amman
    return points

def build_tile_set():
    print("Calculating optimized tile coverage for Amman...")
    points = get_amman_coordinates()
    print(f"Loaded {len(points)} reference location points across Amman.")
    
    tiles = set()
    
    for z in range(10, 17):
        zoom_tiles = set()
        if z <= 13:
            # Full Greater Amman bounding box for lower zooms
            x_min, y_min = deg2num(32.20, 35.65, z)
            x_max, y_max = deg2num(31.65, 36.30, z)
            for x in range(x_min, x_max + 1):
                for y in range(y_min, y_max + 1):
                    zoom_tiles.add((z, x, y))
        elif z == 14:
            # Full central Amman box + buffered points
            x_min, y_min = deg2num(32.08, 35.75, z)
            x_max, y_max = deg2num(31.85, 36.05, z)
            for x in range(x_min, x_max + 1):
                for y in range(y_min, y_max + 1):
                    zoom_tiles.add((z, x, y))
            for lat, lon in points:
                cx, cy = deg2num(lat, lon, z)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        zoom_tiles.add((z, cx + dx, cy + dy))
        elif z in (15, 16):
            # 3x3 tile grid (1 tile buffer) around every station and neighborhood point
            for lat, lon in points:
                cx, cy = deg2num(lat, lon, z)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        zoom_tiles.add((z, cx + dx, cy + dy))
        
        tiles.update(zoom_tiles)
        print(f"  Zoom {z}: {len(zoom_tiles)} unique tiles planned.")
        
    print(f"Total offline tiles to secure: {len(tiles)} (~{len(tiles) * 20 / 1024:.1f} MB estimated)")
    return sorted(list(tiles))

def create_offline_placeholders():
    print("Generating offline fallback placeholder tiles...")
    # 1. Create offline_tile.svg with Arabic messaging
    svg_content = '''<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
        <rect width="256" height="256" fill="#F1F5F9" stroke="#E2E8F0" stroke-width="2"/>
        <circle cx="128" cy="100" r="28" fill="#CBD5E1"/>
        <path d="M116 100 L140 100 M128 88 L128 112" stroke="#64748B" stroke-width="3" stroke-linecap="round"/>
        <text x="128" y="150" font-family="sans-serif" font-weight="bold" font-size="13" fill="#475569" text-anchor="middle">الخريطة غير محملة</text>
        <text x="128" y="172" font-family="sans-serif" font-size="11" fill="#64748B" text-anchor="middle">(خارج نطاق الأوفلاين)</text>
    </svg>'''
    svg_path = os.path.join(TILES_DIR, "offline_tile.svg")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(svg_content)
        
    # 2. Create a minimal 256x256 transparent/grey PNG fallback via base64
    png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHGGJ/PchI7wAAAABJRU5ErkJggg=="
    png_path = os.path.join(TILES_DIR, "offline_tile.png")
    with open(png_path, "wb") as f:
        f.write(base64.b64decode(png_b64))
    print("Offline placeholder images created successfully.")

def clean_blocked_osm_tiles():
    print("Scanning for and cleaning previously blocked OSM error tiles (6987 bytes)...")
    removed = 0
    for root, dirs, files in os.walk(TILES_DIR):
        for file in files:
            if file.endswith(".png") and file != "offline_tile.png":
                fp = os.path.join(root, file)
                try:
                    if os.path.getsize(fp) == 6987: # Known OSM 403 error image size
                        os.remove(fp)
                        removed += 1
                except Exception:
                    pass
    if removed > 0:
        print(f"Removed {removed} invalid 'Access blocked' error tiles from local storage.")

def download_single_tile(tile):
    z, x, y = tile
    # Secure path construction with integer validation
    zoom_dir = os.path.join(TILES_DIR, str(int(z)), str(int(x)))
    file_path = os.path.join(zoom_dir, f"{int(y)}.png")
    
    # Check if already exists and valid (6987 bytes is known OSM blocked error graphic)
    if os.path.exists(file_path):
        size = os.path.getsize(file_path)
        if size == 6987:
            try:
                os.remove(file_path)
            except Exception:
                pass
        elif size > 200:
            return (tile, True, "skipped")
        
    os.makedirs(zoom_dir, exist_ok=True)
    
    # CartoDB Voyager tile servers (high performance, no 403 blocks)
    subdomains = ['a', 'b', 'c', 'd']
    subdomain = subdomains[(x + y) % len(subdomains)]
    url = f"https://{subdomain}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png"
    
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'image/png,image/*;q=0.8,*/*;q=0.5'
    })
    
    for attempt in range(3):
        try:
            time.sleep(random.uniform(0.05, 0.2))
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    content = response.read()
                    with open(file_path, "wb") as f:
                        f.write(content)
                    return (tile, True, "downloaded")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2.0 * (attempt + 1))
            elif e.code == 404:
                return (tile, False, "404")
            else:
                time.sleep(1.0)
        except Exception as e:
            time.sleep(1.0)
            
    return (tile, False, "failed")

def main():
    print("=== Amman Police Stations Offline Map Tile Downloader ===")
    clean_blocked_osm_tiles()
    create_offline_placeholders()
    
    tiles_to_download = build_tile_set()
    total = len(tiles_to_download)
    
    print(f"\nStarting multi-threaded download (4 workers)...")
    start_time = time.time()
    downloaded = 0
    skipped = 0
    failed = 0
    completed = 0
    last_print = time.time()
    
    # We use 4 threads to remain polite to OSM servers while achieving ~15-25 tiles/sec
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(download_single_tile, tile): tile for tile in tiles_to_download}
        for future in as_completed(futures):
            tile, success, status = future.result()
            completed += 1
            if status == "downloaded":
                downloaded += 1
            elif status == "skipped":
                skipped += 1
            else:
                failed += 1
                
            # Print progress every 200 tiles or every 5 seconds
            current_time = time.time()
            if completed % 200 == 0 or completed == total or (current_time - last_print) >= 5.0:
                elapsed = current_time - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                rem_seconds = (total - completed) / rate if rate > 0 else 0
                rem_mins = int(rem_seconds // 60)
                rem_secs = int(rem_seconds % 60)
                
                print(f"[{completed:5d}/{total:5d}] ({completed/total*100:5.1f}%) | "
                      f"New: {downloaded} | Skipped: {skipped} | Failed: {failed} | "
                      f"Speed: {rate:4.1f} tiles/s | ETA: {rem_mins}m {rem_secs}s")
                last_print = current_time

    elapsed = time.time() - start_time
    print(f"\n=== Download Complete in {int(elapsed // 60)}m {int(elapsed % 60)}s ===")
    print(f"Total Tiles: {total} | Downloaded: {downloaded} | Skipped (Existing): {skipped} | Failed: {failed}")
    print(f"Offline maps are stored in: {TILES_DIR}")

if __name__ == "__main__":
    main()
