"""Run the actual ARM64 frozen protocol backend without opening device transports."""
import json
from pathlib import Path
import subprocess
import tempfile

artifact = Path(__file__).resolve().parents[1]/'artifacts/macos-arm64'
backend = artifact/'tools/macos/backend/openwrt-backend'
gui = artifact/'OpenWrt-Installer.app/Contents/MacOS/openwrt-installer'
assert subprocess.check_output(['lipo','-archs',str(gui)],text=True).strip() == 'arm64'
subprocess.run(['codesign','--verify','--deep','--strict',str(artifact/'OpenWrt-Installer.app')],check=True)
assert 'arm64' in subprocess.check_output(['lipo','-archs',str(backend)],text=True)
with tempfile.TemporaryDirectory() as folder:
    request = json.dumps({'protocol':1,'id':1,'command':'hello','params':{}})+'\n'
    result = subprocess.run([str(backend),'--package-root',folder,'--data-dir',str(Path(folder)/'state')],
                            input=request,text=True,capture_output=True,timeout=30)
    assert result.returncode == 0,result.stderr
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    reply = next(row for row in replies if row.get('type')=='response')
    assert reply['data']['ok'],reply
    print(json.dumps(reply))
subprocess.run([str(artifact/'tools/macos/adb'),'version'],check=True)
print('Native ARM64 backend/ADB smoke passed; no device connection opened.')
