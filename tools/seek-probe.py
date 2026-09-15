#!/usr/bin/env python3
"""Headless HLS seek-accuracy probe against the LIVE jellyfin, as a client would do it.

usage: seek-probe.py <ItemId> [--start <sec>] <segIndex>|s<seconds> ...   (sN = sleep N seconds, i.e. "the viewer watched for N s")
For each segment index: GET the segment exactly as the playlist spells it, time it,
then ffprobe the served bytes (first packet in FILE ORDER, no min()) and compare
against the playlist's declared runtimeTicks.
"""
import json, sys, time, os, subprocess, urllib.request, urllib.parse, re, glob
# secrets live outside the repo (public): ~/.config/jellyfin-api.env, 0600
def _env():
    d={}
    for line in open(os.path.expanduser("~/.config/jellyfin-api.env")):
        if "=" in line and not line.startswith("#"):
            k,v=line.strip().split("=",1); d[k]=v
    return d
_E=_env(); KEY=_E["JELLYFIN_API_KEY"]; U=_E["JELLYFIN_USER_ID"]
BASE="http://localhost:8096"
H={"Authorization":f'MediaBrowser Token="{KEY}", Client="seektest", Device="cli", DeviceId="seektest", Version="1"'}
OUTDIR_HOST="/mnt/data/docker-data/jellyfin/cache/seektest"
OUTDIR_CONT="/config/cache/seektest"
LOGDIR="/mnt/data/docker-data/jellyfin/log"

def get(url, timeout=300):
    req=urllib.request.Request(BASE+url, headers=H)
    t0=time.monotonic()
    r=urllib.request.urlopen(req, timeout=timeout)
    ttfb=None; data=b""
    while True:
        chunk=r.read(65536)
        if ttfb is None: ttfb=time.monotonic()-t0
        if not chunk: break
        data+=chunk
    return r.status, data, ttfb, time.monotonic()-t0

def playback_info(item, start):
    profile={"Name":"seektest","MaxStreamingBitrate":120000000,
     "DirectPlayProfiles":[{"Container":"mp4","Type":"Video","VideoCodec":"h264","AudioCodec":"aac"}],
     "TranscodingProfiles":[{"Container":"ts","Type":"Video","VideoCodec":"h264","AudioCodec":"aac,eac3,ac3","Protocol":"hls","Context":"Streaming","MaxAudioChannels":"6","MinSegments":1,"BreakOnNonKeyFrames":True}],
     "CodecProfiles":[],"SubtitleProfiles":[],"ContainerProfiles":[]}
    body={"UserId":U,"DeviceProfile":profile,"MaxStreamingBitrate":120000000,"StartTimeTicks":int(start*10000000),
          "AutoOpenLiveStream":False,"EnableDirectPlay":True,"EnableDirectStream":True,"EnableTranscoding":True}
    req=urllib.request.Request(f"{BASE}/Items/{item}/PlaybackInfo",data=json.dumps(body).encode(),headers={**H,"Content-Type":"application/json"},method="POST")
    j=json.load(urllib.request.urlopen(req,timeout=20))
    return j["PlaySessionId"], j["MediaSources"][0]["TranscodingUrl"]

def ffprobe(cont_path):
    cmd=["docker","exec","jellyfin","/usr/lib/jellyfin-ffmpeg/ffprobe","-v","error","-show_entries",
         "packet=stream_index,codec_type,pts_time,dts_time,flags,size","-of","json",cont_path]
    p=subprocess.run(cmd,capture_output=True,text=True)
    if p.returncode!=0: raise SystemExit(f"ffprobe failed rc={p.returncode}: {p.stderr}")
    return json.loads(p.stdout)["packets"]

def newest_ffmpeg_log(after_ts):
    logs=sorted(glob.glob(f"{LOGDIR}/FFmpeg.Transcode-*.log"), key=os.path.getmtime)
    logs=[l for l in logs if os.path.getmtime(l)>=after_ts-1]
    if not logs: return None
    txt=open(logs[-1],errors="replace").read()
    m=re.search(r"-ss (\S+)",txt); n=re.search(r"-start_number (\d+)",txt)
    return os.path.basename(logs[-1])[17:36], (m.group(1) if m else "-"), (n.group(1) if n else "-")

def main():
    a=sys.argv[1:]; item=a.pop(0); start=0.0
    if a and a[0]=="--start": a.pop(0); start=float(a.pop(0))
    idx=a
    os.makedirs(OUTDIR_HOST,exist_ok=True)
    psid, turl = playback_info(item,start)
    st,master,_,_=get(turl)
    main_url=[l for l in master.decode().splitlines() if l.startswith("main.m3u8")][0]
    main_url=turl.rsplit("/",1)[0]+"/"+main_url
    st,pl,_,_=get(main_url)
    segs=[]; cur=None
    for line in pl.decode().splitlines():
        if line.startswith("#EXTINF:"): cur=float(line[8:].split(",")[0])
        elif line and not line.startswith("#"):
            q=urllib.parse.parse_qs(urllib.parse.urlparse(line).query)
            n=int(re.search(r"hls1/main/(-?\d+)\.",line).group(1))
            segs.append((n, int(q["runtimeTicks"][0])/1e7, cur, turl.rsplit("/",1)[0]+"/"+line))
    print(f"playsession={psid} start={start}s segments={len(segs)} first EXTINF={segs[0][2]} last={segs[-1][2]}")
    print(f"{'seg':>4} {'declared':>9} {'ffmpeg -ss':>12} {'#start':>6} {'ttfb':>6} {'total':>6} {'bytes':>9} {'v0.pts':>9} {'v0.dts':>9} {'v0.key':>6} {'a0.pts':>9} {'vN.pts':>9} {'vpk':>4} {'keys':>4} {'a<decl':>6}")
    for tok in idx:
        if tok.startswith("s"): print(f"  (sleep {tok[1:]}s)"); time.sleep(float(tok[1:])); continue
        n=int(tok); seg=segs[n]; t0=time.time()
        st,data,ttfb,tot=get(seg[3])
        host=f"{OUTDIR_HOST}/seg{n}.ts"; cont=f"{OUTDIR_CONT}/seg{n}.ts"
        if os.path.exists(host): os.remove(host)
        open(host,"wb").write(data)
        pk=ffprobe(cont)
        v=[p for p in pk if p["codec_type"]=="video"]; au=[p for p in pk if p["codec_type"]=="audio"]
        v0=v[0] if v else {}; a0=au[0] if au else {}
        keys=sum(1 for p in v if "K" in p.get("flags",""))
        early_audio=sum(1 for p in au if float(p["pts_time"])<seg[1])
        lg=newest_ffmpeg_log(t0) or ("(no new ffmpeg)","-","-")
        print(f"{n:>4} {seg[1]:>9.3f} {lg[1]:>12} {lg[2]:>6} {ttfb:>6.2f} {tot:>6.2f} {len(data):>9} {float(v0.get('pts_time',0)):>9.3f} {float(v0.get('dts_time',0)):>9.3f} {('K' in v0.get('flags','')):>6} {float(a0.get('pts_time',0)):>9.3f} {float(v[-1]['pts_time']) if v else 0:>9.3f} {len(v):>4} {keys:>4} {early_audio:>6}")
    # stop our transcode
    req=urllib.request.Request(f"{BASE}/Videos/ActiveEncodings?deviceId=seektest&playSessionId={psid}",headers=H,method="DELETE")
    try: urllib.request.urlopen(req,timeout=20); print("stopped")
    except Exception as e: print("stop:",e)
main()
