"""Compose one continuous Unreal tour with authentic manipulation and detection feeds."""
import argparse,hashlib,json,math,subprocess
from pathlib import Path
from PIL import Image,ImageDraw,ImageFilter

FRANKA='1c6fe0b0953adacba8a105452afb2f756d04a6bd0d34cb927d92992dcde0f466'
DETECTION='9649e3d6f42b9591d8dfdbb7b99ef796abc4dbb3e5da712afa5b24dba104c354'
def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
def run(cmd,log):
    with Path(log).open('w') as f:subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True)
def ass_time(t):
    c=round(t*100);return f'{c//360000}:{c//6000%60:02}:{c//100%60:02}.{c%100:02}'
def badge(tour,path):
    text='[Script Info]\nScriptType: v4.00+\nPlayResX: 3840\nPlayResY: 2160\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Rate,DejaVu Sans,42,&H00FFFFFF,&H00FFFFFF,&H80201810,&H80201810,0,0,0,0,100,100,1,0,3,12,0,1,100,100,100,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    runs=[]
    for f in range(0,tour['frames'],3):
        t=f/30;s=next((s for s in tour['clock'] if s['videoStart']+s['duration']>t),tour['clock'][-1]);u=max(0,min(1,(t-s['videoStart'])/s['duration']));r=s['rateStart']+(s['rateEnd']-s['rateStart'])*u*u*(3-2*u)
        label=('TIMELAPSE ×'+(str(round(r)) if abs(r-round(r))<.05 else f'{r:.1f}')) if r>1.05 else ''
        if runs and runs[-1][2]==label:runs[-1][1]=min(tour['frames']/30,(f+3)/30)
        else:runs.append([t,min(tour['frames']/30,(f+3)/30),label])
    for a,b,label in runs:
        if label:text+=f'Dialogue: 0,{ass_time(a)},{ass_time(b)},Rate,,0,0,0,,{label}\n'
    path.write_text(text)
def card_assets(root,name,w,h):
    margin=48;mask=Image.new('L',(w*2,h*2),0);ImageDraw.Draw(mask).rounded_rectangle((0,0,w*2-1,h*2-1),radius=64,fill=255);mask=mask.resize((w,h),Image.Resampling.LANCZOS);mask.save(root/f'{name}-mask.png')
    alpha=Image.new('L',(w+96,h+96),0);ImageDraw.Draw(alpha).rounded_rectangle((48,56,w+48,h+56),radius=32,fill=130);alpha=alpha.filter(ImageFilter.GaussianBlur(24));shadow=Image.new('RGBA',alpha.size,(0,0,0,0));shadow.putalpha(alpha);shadow.save(root/f'{name}-shadow.png')
def compose(tour,concat,franka,detection,output,gpu,preview=False):
    output.mkdir(parents=True,exist_ok=True)
    assert digest(franka)==FRANKA and digest(detection)==DETECTION,'Real source recording changed'
    badge(tour,output/'speed.ass');card_assets(output,'franka',924,1642);card_assets(output,'detection',1536,1192)
    cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','warning','-y','-filter_complex_threads','2','-f','concat','-safe','0','-i',str(concat),'-i',str(franka),'-i',str(detection)]
    for name in ['franka-mask','franka-shadow','detection-mask','detection-shadow']:cmd+=['-loop','1','-framerate','30','-i',str(output/(name+'.png'))]
    graph='[0:v]fps=30,setsar=1,setpts=PTS-STARTPTS,format=yuv420p[base];'
    for name,idx,mask,shadow,w,h in [('franka',1,3,4,924,1642),('detection',2,5,6,1536,1192)]:
        o=tour['overlays'][name];a=o['fadeIn']-o['start'];b=o['fadeOut']-o['start'];end=o['end']-o['start']
        graph+=f'[{idx}:v]fps=30,trim=duration={o["clipSeconds"]},setpts=PTS-STARTPTS,scale={w}:{h}:flags=lanczos,setsar=1,tpad=stop_mode=clone:stop_duration=20,trim=duration={end},format=rgba[{name}feed];'
        graph+=f'[{mask}:v]format=gray[{name}mask];[{name}feed][{name}mask]alphamerge[{name}masked];'
        graph+=f'[{shadow}:v][{name}masked]overlay=48:48:shortest=1:format=auto,fade=t=in:st={a}:d=1.2:alpha=1,fade=t=out:st={b}:d={end-b}:alpha=1,setpts=PTS+{o["start"]}/TB[{name}card];'
    graph+='[base][frankacard]overlay=2717:211:eof_action=pass:format=auto[first];[first][detectioncard]overlay=86:49:eof_action=pass:format=auto,'
    graph+=f'ass=filename={output/"speed.ass"},format=yuv420p[out]'
    (output/'filtergraph.txt').write_text(graph)
    master=output/'tour-4k.mp4';partial=output/'tour-4k.partial.mp4'
    cmd+=['-filter_complex',graph,'-map','[out]','-frames:v',str(tour['frames']),'-an','-map_metadata','-1','-c:v','h264_nvenc','-gpu',str(gpu),'-preset','p7','-tune','hq','-rc','vbr','-cq','15','-b:v','0','-spatial-aq','1','-temporal-aq','1','-pix_fmt','yuv420p','-color_range','tv','-colorspace','bt709','-color_primaries','bt709','-color_trc','iec61966-2-1','-movflags','+faststart',str(partial)]
    run(cmd,output/'composite.log');partial.replace(master)
    previewfile=output/'tour-1080p.mp4';partial=output/'tour-1080p.partial.mp4'
    run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y','-i',str(master),'-vf','scale=1920:1080:flags=lanczos','-an','-c:v','h264_nvenc','-gpu',str(gpu),'-preset','p7','-rc','vbr','-cq','18','-b:v','0','-pix_fmt','yuv420p','-movflags','+faststart',str(partial)],output/'preview.log');partial.replace(previewfile)
    run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y','-ss','4','-i',str(previewfile),'-frames:v','1',str(output/'poster.jpg')],output/'poster.log')
    return [master,previewfile,output/'poster.jpg']
def main():
    p=argparse.ArgumentParser();p.add_argument('--tour',type=Path,required=True);p.add_argument('--concat',type=Path,required=True);p.add_argument('--franka',type=Path,required=True);p.add_argument('--detection',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--gpu',type=int,required=True);a=p.parse_args();compose(json.loads(a.tour.read_text()),a.concat,a.franka,a.detection,a.output,a.gpu)
if __name__=='__main__':main()
