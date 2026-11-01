#!/usr/bin/env python3
"""Download Debian MoveIt dependencies into a local prefix, without sudo or system installation."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

PACKAGES = [
    'ros-humble-moveit-resources-panda-moveit-config',
    'ros-humble-moveit-ros-move-group',
    'ros-humble-moveit-ros-visualization',
    'ros-humble-moveit-kinematics',
    'ros-humble-moveit-planners-ompl',
    'ros-humble-joint-state-publisher',
    'ros-humble-xacro',
    'ros-humble-moveit-configs-utils',
]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix',default='.deps/moveit')
    args=parser.parse_args()
    prefix=Path(args.prefix).resolve()
    downloads=prefix/'downloads'
    downloads.mkdir(parents=True,exist_ok=True)
    lists=prefix/'apt-lists'
    (lists/'partial').mkdir(parents=True,exist_ok=True)
    apt=['apt-get','-o',f'Dir::State::lists={lists}', '-o',f'Dir::Cache::pkgcache={prefix}/pkgcache.bin','-o',f'Dir::Cache::srcpkgcache={prefix}/srcpkgcache.bin','-o','Debug::NoLocking=true', '-o','APT::Get::List-Cleanup=false','-o','APT::Update::Error-Mode=any','-o','Acquire::Languages=none']
    subprocess.run([*apt,'update'],check=True)
    plan=subprocess.run([*apt,'-s','install','--no-install-recommends',*PACKAGES],check=True,text=True,capture_output=True).stdout
    installs=[]
    for line in plan.splitlines():
        if line.startswith('Remv '):raise RuntimeError('dependency plan removes packages; refusing local extraction')
        if not line.startswith('Inst '):continue
        match=re.match(r'Inst (\S+) \((\S+) ',line)
        if match is None:raise RuntimeError('dependency plan upgrades an installed package; inspect before continuing')
        installs.append(f'{match[1]}={match[2]}')
    if not installs:
        print('Requested dependencies are already installed system-wide.')
        return
    (prefix/'apt-plan.txt').write_text(plan)
    subprocess.run([*apt,'download',*installs],cwd=downloads,check=True)
    selected=set(installs)
    manifest=[]
    for package in sorted(downloads.glob('*.deb')):
        identity=subprocess.run(['dpkg-deb','--show','--showformat=${Package}=${Version}',str(package)],check=True,text=True,capture_output=True).stdout
        if identity not in selected:continue
        subprocess.run(['dpkg-deb','--extract',str(package),str(prefix)],check=True)
        manifest.append(dict(package=identity,file=package.name,sha256=hashlib.sha256(package.read_bytes()).hexdigest()))
    (prefix/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'Local dependency prefix: {prefix}\nPackages extracted: {len(manifest)}')


if __name__=='__main__':main()
