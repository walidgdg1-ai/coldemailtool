#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path
from typing import Any

import cv2
import imagehash
import numpy as np
from PIL import Image, ImageDraw, ImageFont

TARGET = int(os.environ.get("TARGET_PER_GAME", "15"))
MIN_WIDTH = int(os.environ.get("MIN_WIDTH", "960"))
MIN_HEIGHT = int(os.environ.get("MIN_HEIGHT", "540"))
SEARCH_RESULTS = int(os.environ.get("SEARCH_RESULTS", "30"))
MAX_VIDEOS = int(os.environ.get("MAX_VIDEOS", "5"))
SEGMENT_SECONDS = int(os.environ.get("SEGMENT_SECONDS", "360"))
ROOT = Path(os.environ.get("HARVEST_ROOT", "HD_EXTRA_REFERENCE_BANK")).resolve()

GAMES: list[dict[str, Any]] = [
    {"name":"Puppeteer","query":"Puppeteer PS3 1080p gameplay no commentary longplay","aliases":["puppeteer"]},
    {"name":"Gravity Rush","query":"Gravity Rush PS Vita PS4 1080p gameplay no commentary","aliases":["gravity rush","gravity daze"],"reject":["gravity rush 2"]},
    {"name":"Gravity Rush 2","query":"Gravity Rush 2 PS4 1080p gameplay no commentary","aliases":["gravity rush 2","gravity daze 2"]},
    {"name":"Solatorobo Red the Hunter","query":"Solatorobo Red the Hunter DS HD gameplay longplay","aliases":["solatorobo","red the hunter"]},
    {"name":"Kirby's Epic Yarn","query":"Kirby's Epic Yarn Wii HD gameplay no commentary","aliases":["kirby's epic yarn","kirbys epic yarn"]},
    {"name":"LittleBigPlanet 2","query":"LittleBigPlanet 2 PS3 1080p gameplay no commentary","aliases":["littlebigplanet 2","little big planet 2","lbp2"]},
    {"name":"Okami","query":"Okami HD gameplay no commentary PS4","aliases":["okami","ōkami"]},
    {"name":"Ghost Trick Phantom Detective","query":"Ghost Trick Phantom Detective HD gameplay no commentary","aliases":["ghost trick","phantom detective"]},
    {"name":"Fantasy Life","query":"Fantasy Life 3DS HD gameplay no commentary","aliases":["fantasy life"],"reject":["fantasy life i"]},
    {"name":"Yo-kai Watch 2","query":"Yo-kai Watch 2 3DS HD gameplay no commentary","aliases":["yo-kai watch 2","yokai watch 2","youkai watch 2"]},
    {"name":"Katamari Damacy","query":"Katamari Damacy Reroll 1080p gameplay no commentary","aliases":["katamari damacy"],"reject":["we love katamari"]},
    {"name":"We Love Katamari","query":"We Love Katamari Reroll 1080p gameplay no commentary","aliases":["we love katamari"]},
    {"name":"The World Ends with You","query":"The World Ends with You Final Remix HD gameplay no commentary","aliases":["the world ends with you","twewy"],"reject":["neo"]},
    {"name":"Muramasa The Demon Blade","query":"Muramasa Rebirth HD gameplay no commentary","aliases":["muramasa","the demon blade"]},
    {"name":"Viewtiful Joe","query":"Viewtiful Joe HD gameplay no commentary longplay","aliases":["viewtiful joe"]},
    {"name":"Sly 2 Band of Thieves","query":"Sly 2 Band of Thieves HD gameplay no commentary","aliases":["sly 2","band of thieves"]},
    {"name":"Dark Chronicle Dark Cloud 2","query":"Dark Cloud 2 PS4 HD gameplay no commentary","aliases":["dark chronicle","dark cloud 2"]},
    {"name":"Rogue Galaxy","query":"Rogue Galaxy PS4 HD gameplay no commentary","aliases":["rogue galaxy"]},
    {"name":"Klonoa 2 Lunatea's Veil","query":"Klonoa 2 Lunatea's Veil HD gameplay no commentary","aliases":["klonoa 2","lunatea's veil","lunateas veil"]},
    {"name":"Auto Modellista","query":"Auto Modellista HD gameplay no commentary longplay","aliases":["auto modellista"]},
    {"name":"No More Heroes","query":"No More Heroes HD remaster gameplay no commentary","aliases":["no more heroes"],"reject":["no more heroes 2","travis strikes again","no more heroes 3"]},
    {"name":"Fragile Dreams Farewell Ruins of the Moon","query":"Fragile Dreams Farewell Ruins of the Moon HD gameplay","aliases":["fragile dreams","farewell ruins of the moon"]},
    {"name":"Bravely Default","query":"Bravely Default 3DS HD gameplay no commentary","aliases":["bravely default"],"reject":["bravely default 2","bravely default ii","bravely second"]},
    {"name":"Ever Oasis","query":"Ever Oasis 3DS HD gameplay no commentary","aliases":["ever oasis"]},
    {"name":"Monster Hunter Stories","query":"Monster Hunter Stories HD gameplay no commentary","aliases":["monster hunter stories"],"reject":["stories 2"]},
    {"name":"Kirby Planet Robobot","query":"Kirby Planet Robobot 3DS HD gameplay no commentary","aliases":["kirby planet robobot","planet robobot"]},
    {"name":"Killer7","query":"Killer7 HD remaster gameplay no commentary","aliases":["killer7","killer 7"]},
    {"name":"MadWorld","query":"MadWorld Wii HD gameplay no commentary","aliases":["madworld","mad world"]},
    {"name":"Hotel Dusk Room 215","query":"Hotel Dusk Room 215 DS HD gameplay longplay","aliases":["hotel dusk","room 215"]},
    {"name":"The Unfinished Swan","query":"The Unfinished Swan 1080p gameplay no commentary","aliases":["the unfinished swan","unfinished swan"]},
    {"name":"Mirror's Edge","query":"Mirror's Edge 2008 1080p gameplay no commentary","aliases":["mirror's edge","mirrors edge"],"reject":["catalyst"]},
]

BAD_TERMS = {"review","reaction","retrospective","analysis","essay","trailer","teaser","ost","soundtrack","music","comparison","speedrun","ending","all cutscenes","movie","podcast","shorts","livestream","benchmark"}
GOOD_TERMS = {"gameplay":30,"no commentary":25,"longplay":20,"walkthrough":15,"playthrough":15,"full game":10,"1080p":18,"1440p":20,"4k":22,"60fps":8,"hd":8}


def run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()).strip()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", norm(text)).strip("_")


def search_videos(game: dict[str, Any]) -> list[dict[str, Any]]:
    queries = [game["query"], f"{game['name']} 1080p longplay no commentary", f"{game['name']} HD gameplay"]
    gathered: dict[str, dict[str, Any]] = {}
    for query in queries:
        proc = run(["yt-dlp","--dump-json","--skip-download","--flat-playlist","--playlist-end",str(SEARCH_RESULTS),"--no-warnings",f"ytsearch{SEARCH_RESULTS}:{query}"], timeout=300)
        for rank, line in enumerate(proc.stdout.splitlines()):
            if not line.lstrip().startswith("{"):
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            vid = str(row.get("id") or "")
            title = norm(str(row.get("title") or ""))
            if not vid or not title:
                continue
            if any(norm(x) in title for x in game.get("reject", [])):
                continue
            aliases = [norm(x) for x in game.get("aliases", [])]
            if aliases and not any(a in title for a in aliases):
                tokens = [t for t in re.findall(r"[a-z0-9]+", aliases[0]) if len(t) > 2]
                if not tokens or not all(t in title for t in tokens):
                    continue
            score = 100.0 - rank * 1.1
            for term, bonus in GOOD_TERMS.items():
                if term in title:
                    score += bonus
            for term in BAD_TERMS:
                if term in title:
                    score -= 75
            duration = row.get("duration")
            if isinstance(duration, (int, float)):
                if 600 <= duration <= 14400:
                    score += 18
                elif duration < 240:
                    score -= 70
            channel = norm(str(row.get("channel") or row.get("uploader") or ""))
            if any(x in channel for x in ["nintendocomplete","world of longplays","longplayarchive","gameplayarchive","shirrako","mkiceandfire"]):
                score += 15
            row.update({"score":score,"query_used":query,"webpage_url":f"https://www.youtube.com/watch?v={vid}"})
            if vid not in gathered or score > gathered[vid]["score"]:
                gathered[vid] = row
    rows = sorted(gathered.values(), key=lambda x: x["score"], reverse=True)
    if not rows:
        raise RuntimeError(f"No matched gameplay videos for {game['name']}")
    return rows[:12]


def segment_window(row: dict[str, Any], ordinal: int) -> tuple[float, float]:
    d = row.get("duration")
    duration = float(d) if isinstance(d, (int, float)) else 0.0
    if duration <= SEGMENT_SECONDS + 60:
        return 20.0, max(90.0, duration - 30.0) if duration else float(SEGMENT_SECONDS)
    fractions = [0.06, 0.23, 0.43, 0.63, 0.79]
    start = min(max(35.0, duration * fractions[ordinal % len(fractions)]), duration - SEGMENT_SECONDS - 15)
    return start, min(float(SEGMENT_SECONDS), duration - start - 8)


def probe(path: Path) -> dict[str, Any] | None:
    p = run(["ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=width,height,duration","-show_entries","format=duration","-of","json",str(path)], timeout=90)
    try:
        data = json.loads(p.stdout); s = data.get("streams", [{}])[0]
        return {"width":int(s.get("width") or 0),"height":int(s.get("height") or 0),"duration":float(s.get("duration") or data.get("format",{}).get("duration") or 0)}
    except Exception:
        return None


def download_segment(row: dict[str, Any], out: Path, ordinal: int) -> bool:
    start, length = segment_window(row, ordinal)
    tmpl = str(out.with_suffix(".%(ext)s"))
    cmd = ["yt-dlp","--no-playlist","--no-warnings","--retries","4","--fragment-retries","4","--socket-timeout","30","--extractor-args","youtube:player_client=tv,web_safari,android_vr","--impersonate","chrome","--format","bestvideo[height>=720][height<=1080]/best[height>=720][height<=1080]/bestvideo[height<=1080]/best[height<=1080]","--download-sections",f"*{start:.1f}-{start+length:.1f}","--force-keyframes-at-cuts","--output",tmpl,row["webpage_url"]]
    p = run(cmd, timeout=900)
    files = sorted(out.parent.glob(out.stem + ".*"), key=lambda x: x.stat().st_size, reverse=True)
    for f in files:
        if f.suffix.lower() in {".part",".ytdl",".json"}:
            continue
        info = probe(f)
        if info and info["width"] >= MIN_WIDTH and info["height"] >= MIN_HEIGHT and f.stat().st_size > 1_000_000:
            if out.exists(): out.unlink()
            f.rename(out)
            return True
    print("DOWNLOAD_FAILED", p.stdout[-2000:], flush=True)
    return False


def extract(video: Path, out_dir: Path, source_idx: int) -> list[Path]:
    info = probe(video) or {}
    duration = float(info.get("duration") or 0)
    interval = max(3.0, duration / 110.0) if duration else 4.0
    pattern = out_dir / f"s{source_idx:02d}_%04d.jpg"
    run(["ffmpeg","-hide_banner","-loglevel","error","-y","-i",str(video),"-vf",f"fps=1/{interval:.3f}","-q:v","2",str(pattern)], timeout=600)
    return sorted(out_dir.glob(f"s{source_idx:02d}_*.jpg"))


def metrics(path: Path) -> dict[str, Any] | None:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None: return None
    h,w = bgr.shape[:2]
    if w < MIN_WIDTH or h < MIN_HEIGHT: return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean()); contrast = float(gray.std()); sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if brightness < 12 or brightness > 245 or contrast < 18 or sharpness < 22: return None
    if float((gray < 12).mean()) > .58 or float((gray > 245).mean()) > .58: return None
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    edges = cv2.Canny(gray,70,150); edge_density=float((edges>0).mean())
    strip=np.concatenate([edges[:h//5].ravel(),edges[-h//5:].ravel()]); strip_edges=float((strip>0).mean())
    menu_penalty=max(0.0,strip_edges-edge_density*1.6)
    center=edges[h//5:4*h//5,w//5:4*w//5]; center_activity=float((center>0).mean())
    hist64=cv2.calcHist([gray],[0],None,[64],[0,256]).flatten(); p=hist64/max(float(hist64.sum()),1.0); entropy=float(-(p[p>0]*np.log2(p[p>0])).sum())
    saturation=float(hsv[:,:,1].mean()); colorfulness=float(np.std(bgr[:,:,0]-bgr[:,:,1])+np.std(bgr[:,:,2]-bgr[:,:,1]))
    quality=1.7*math.log1p(sharpness)+.025*contrast+.008*saturation+.012*colorfulness+2.2*entropy+8*center_activity-18*menu_penalty-2*abs(brightness-125)/125
    small=cv2.resize(hsv,(192,108)); hist=cv2.calcHist([small],[0,1],None,[16,8],[0,180,0,256]).flatten().astype(np.float32); hist/=max(float(np.linalg.norm(hist)),1e-8)
    return {"path":path,"width":w,"height":h,"quality":quality,"phash":imagehash.phash(Image.open(path).convert("RGB"),hash_size=12),"hist":hist,"brightness":brightness,"sharpness":sharpness,"center_activity":center_activity,"menu_penalty":menu_penalty}


def select_diverse(paths: list[Path]) -> list[dict[str, Any]]:
    rows=[r for p in paths if (r:=metrics(p))]; rows.sort(key=lambda r:r["quality"], reverse=True)
    unique=[]
    for row in rows:
        if any((row["phash"]-k["phash"]<=10 and float(np.dot(row["hist"],k["hist"]))>.90) for k in unique): continue
        unique.append(row)
    if len(unique)<=TARGET: return unique
    qs=np.array([r["quality"] for r in unique],dtype=np.float32); lo,hi=float(qs.min()),float(qs.max())
    for r in unique: r["qnorm"]=(r["quality"]-lo)/max(hi-lo,1e-8)
    chosen=[max(unique,key=lambda r:r["qnorm"])]; remaining=[r for r in unique if r is not chosen[0]]
    while remaining and len(chosen)<TARGET:
        def score(c):
            ds=[]
            for k in chosen:
                hd=(c["phash"]-k["phash"])/144.0; hist=max(0.0,1-float(np.dot(c["hist"],k["hist"])))
                ds.append(.55*hist+.45*hd)
            return .76*min(ds)+.24*c["qnorm"]
        x=max(remaining,key=score); chosen.append(x); remaining.remove(x)
    return chosen


def font(size: int):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]:
        if Path(p).exists(): return ImageFont.truetype(p,size=size)
    return ImageFont.load_default()


def make_contact(game: str, rows: list[dict[str, Any]], out: Path):
    cols,cell_w,image_h,label_h,header=5,360,220,42,70; rc=math.ceil(len(rows)/cols)
    canvas=Image.new("RGB",(cols*cell_w,header+rc*(image_h+label_h)),"#0d0d0d"); draw=ImageDraw.Draw(canvas)
    draw.text((18,18),f"{game} — {len(rows)} additional HD gameplay frames",fill="white",font=font(25))
    for i,row in enumerate(rows):
        rr,cc=divmod(i,cols); x,y=cc*cell_w,header+rr*(image_h+label_h)
        im=Image.open(row["output_path"]).convert("RGB"); im.thumbnail((cell_w,image_h),Image.Resampling.LANCZOS)
        frame=Image.new("RGB",(cell_w,image_h),"black"); frame.paste(im,((cell_w-im.width)//2,(image_h-im.height)//2)); canvas.paste(frame,(x,y))
        draw.rectangle((x,y+image_h,x+cell_w,y+image_h+label_h),fill="#1b1b1b"); draw.text((x+8,y+image_h+10),f"{i+16:02d} · {row['width']}×{row['height']}",fill="white",font=font(14))
    canvas.save(out,quality=92)


def main() -> int:
    index=int(os.environ.get("GAME_INDEX","1")); game=GAMES[index-1]; slug=slugify(game["name"])
    if ROOT.exists(): shutil.rmtree(ROOT)
    game_dir=ROOT/f"{index:02d}_{slug}"; image_dir=game_dir/"images_hd_extra"; cand_dir=game_dir/"candidates"; video_dir=game_dir/"source_segments"
    for d in [image_dir,cand_dir,video_dir]: d.mkdir(parents=True,exist_ok=True)
    started=time.time(); videos=search_videos(game); sources=[]; candidates=[]
    for ordinal,row in enumerate(videos[:MAX_VIDEOS]):
        segment=video_dir/f"source_{ordinal+1:02d}.mp4"; ok=download_segment(row,segment,ordinal)
        rec={"video_id":row.get("id"),"title":row.get("title"),"channel":row.get("channel") or row.get("uploader"),"url":row.get("webpage_url"),"query":row.get("query_used"),"search_score":row.get("score"),"downloaded":ok}
        if ok:
            rec["segment_info"]=probe(segment); frames=extract(segment,cand_dir,ordinal+1); rec["candidate_frames"]=len(frames); candidates.extend(frames)
        sources.append(rec)
        if len(candidates)>=170: break
    selected=select_diverse(candidates)
    if len(selected)<TARGET: raise RuntimeError(f"Only {len(selected)} acceptable frames for {game['name']} from {len(candidates)} candidates")
    out_rows=[]
    for number,row in enumerate(selected[:TARGET],16):
        fn=f"{slug}_{number:03d}_hd_gameplay.jpg"; dst=image_dir/fn; shutil.copy2(row["path"],dst)
        out_rows.append({"game":game["name"],"filename":fn,"relative_path":f"{index:02d}_{slug}/images_hd_extra/{fn}","width":row["width"],"height":row["height"],"quality_score":round(float(row["quality"]),4),"brightness":round(float(row["brightness"]),3),"sharpness":round(float(row["sharpness"]),3),"center_activity":round(float(row["center_activity"]),5),"menu_penalty":round(float(row["menu_penalty"]),5),"output_path":str(dst)})
    make_contact(game["name"],out_rows,game_dir/f"contact_sheet_{slug}_hd_extra.jpg")
    manifest={"game":game["name"],"ordinal":index,"target_count":TARGET,"selected_count":len(out_rows),"candidate_count":len(candidates),"minimum_resolution":f"{MIN_WIDTH}x{MIN_HEIGHT}","source":"native frames from title-matched public gameplay video streams","manual_review_required":True,"sources":sources,"elapsed_seconds":round(time.time()-started,2),"images":[{k:v for k,v in r.items() if k!="output_path"} for r in out_rows]}
    (game_dir/f"manifest_{slug}_hd_extra.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    shutil.rmtree(cand_dir,ignore_errors=True); shutil.rmtree(video_dir,ignore_errors=True)
    print(json.dumps({"game":game["name"],"selected":len(out_rows)},ensure_ascii=False)); return 0

if __name__ == "__main__": raise SystemExit(main())
