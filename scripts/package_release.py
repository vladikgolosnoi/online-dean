"""Package an explicit source allowlist, evidence reports and defense slides."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]


def main():
    files = []
    for folder in ('app', 'config', 'docs', 'samples', 'scripts', 'tests', 'web', 'official'):
        files.extend(p for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    files.extend(ROOT / name for name in ('README.md', 'results.json', 'requirements.txt', 'requirements-dev.txt', 'requirements-lock.txt', 'requirements-media.txt', 'pytest.ini',
                                         'Dockerfile', 'compose.yaml', 'start.ps1', '.gitignore', '.dockerignore'))
    for name in ('official/evaluation.json', 'official/evaluation-pdf.json', 'official/classification.json', 'official/results-pdf.json',
                 'defense-v3/online-dean-defense-v3.pptx', 'demo-v3/online-dean-demo.mp4', 'demo-v3/scenes.json', 'demo-v3/video-info.json'):
        path = ROOT / 'output' / name
        if path.exists():
            files.append(path)
    target = ROOT / 'output' / 'release'
    target.mkdir(parents=True, exist_ok=True)
    manifest = {'name': 'online-dean', 'version': '3.0.0', 'official_submission': True,
                'excluded': ['environments', 'OCR model binaries', 'uploaded documents', 'temporary files'],
                'files': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}}
    archive = target / 'online-dean-v3.0.zip'
    with ZipFile(archive, 'w', ZIP_DEFLATED) as package:
        for path in files:
            package.write(path, path.relative_to(ROOT).as_posix())
        package.writestr('MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    with ZipFile(archive) as package:
        assert package.testzip() is None
        for name, expected in manifest['files'].items():
            assert hashlib.sha256(package.read(name)).hexdigest() == expected, name
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(checksum + '  ' + archive.name + '\n', encoding='ascii')
    print(json.dumps({'archive': str(archive), 'files': len(files), 'bytes': archive.stat().st_size, 'sha256': checksum}))


if __name__ == '__main__':
    main()
