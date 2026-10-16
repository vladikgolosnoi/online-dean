"""Encode a narrated walkthrough of genuine UI screenshots, not a live recording.

Requires imageio-ffmpeg==0.6.0 and captured scenes/audio in output/demo-v3.
"""
import argparse
import json
import shutil
import subprocess
import wave
from pathlib import Path
import imageio_ffmpeg


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=Path('output/demo-v3'))
    source = (root / parser.parse_args().source).resolve()
    work = root / 'tmp' / 'video'
    work.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path('C:/Windows/Fonts/arial.ttf'), work / 'font.ttf')
    scenes = json.loads((source / 'scenes.json').read_text(encoding='utf-8'))
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    duration = 0
    for i, scene in enumerate(scenes):
        with wave.open(str(source / f'audio-{i}.wav')) as audio:
            seconds = audio.getnframes() / audio.getframerate() + 1
        duration += seconds
        (work / 'title.txt').write_text(scene['title'], encoding='utf-8', newline='\n')
        (work / 'caption.txt').write_text(scene['caption'], encoding='utf-8', newline='\n')
        (work / 'footer.txt').write_text('Версия 3.0\nРеальные экраны приложения\nДемонстрационный сценарий', encoding='utf-8', newline='\n')
        filters = (
            'scale=1240:1040:force_original_aspect_ratio=decrease:force_divisible_by=2,'
            'pad=1920:1080:20:(oh-ih)/2:color=white,setsar=1,'
            "drawbox=x=1290:y=0:w=630:h=1080:color=0xf3f3f5:t=fill,"
            "drawtext=fontfile=font.ttf:text='ОНЛАЙН-ДЕКАНАТ':fontsize=24:fontcolor=0x50b848:x=1330:y=90,"
            'drawtext=fontfile=font.ttf:textfile=title.txt:expansion=none:fontsize=38:fontcolor=0x202020:x=1330:y=220,'
            'drawtext=fontfile=font.ttf:textfile=caption.txt:expansion=none:fontsize=29:line_spacing=15:fontcolor=0x555555:x=1330:y=330,'
            'drawtext=fontfile=font.ttf:textfile=footer.txt:expansion=none:fontsize=20:line_spacing=10:fontcolor=0x888888:x=1330:y=810,'
            f"drawtext=fontfile=font.ttf:text='{i+1:02d} / {len(scenes):02d}':fontsize=22:fontcolor=0x50b848:x=1330:y=1000"
        )
        command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-loop', '1', '-framerate', '24',
                   '-i', str(source / scene['image']), '-i', str(source / f'audio-{i}.wav'),
                   '-vf', filters, '-af', 'apad', '-t', str(seconds), '-c:v', 'libx264', '-preset', 'veryfast',
                   '-tune', 'stillimage', '-crf', '23', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
                   '-ar', '48000', '-ac', '2', str(work / f'scene-{i}.mp4')]
        subprocess.run(command, cwd=work, check=True)
        print(f'Scene {i+1}: {seconds:.1f}s', flush=True)
    assert duration <= 180, duration
    (work / 'concat.txt').write_text(''.join(f"file 'scene-{i}.mp4'\n" for i in range(len(scenes))), encoding='ascii')
    final = source / 'online-dean-demo.mp4'
    subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0',
                    '-i', 'concat.txt', '-c', 'copy', '-movflags', '+faststart', str(final)], cwd=work, check=True)
    subprocess.run([ffmpeg, '-v', 'error', '-i', str(final), '-f', 'null', '-'], check=True)
    (source / 'video-info.json').write_text(json.dumps({'seconds': round(duration, 2), 'width': 1920, 'height': 1080,
        'fps': 24, 'type': 'Narrated genuine UI stills; not a live screen recording', 'voice': 'Microsoft Irina Desktop',
        'decoded_without_errors': True}, indent=2), encoding='utf-8')
    print(str(final), flush=True)


if __name__ == '__main__':
    main()
