"""desktop モードの録画をホストから起動する（recorder イメージを対象アプリと同じ localhost に置く）。

ネットワークは環境変数で選ぶ:
  DEMO_NETWORK 未設定  → container:$DEMO_APP_CONTAINER（対象アプリのコンテナに相乗り。既定 audit-demo-app）
  DEMO_NETWORK=host    → ホストのネットワークをそのまま使う（Linux 向け。アプリが Docker 外でも可）
どちらもコンテナ内から http://localhost:<port> で対象アプリに届く。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

IMAGE = os.environ.get("DEMO_RECORDER_IMAGE", "demo-recorder:latest")
APP_CONTAINER = os.environ.get("DEMO_APP_CONTAINER", "audit-demo-app")
NETWORK = os.environ.get("DEMO_NETWORK") or f"container:{APP_CONTAINER}"


def host_path(p: Path) -> str:
    """Docker に渡すホスト側の実パス。

    Claude デスクトップアプリ（MSIX）配下では %APPDATA% への書き込みが
    %LOCALAPPDATA%\\Packages\\<pkg>\\LocalCache\\Roaming に振り替えられており、Docker からは元のパスが空に見える。
    その場合は振り替え先の実パスを返す。通常の VM では何もしない。
    """
    p = p.resolve()
    roaming = Path(os.environ.get("APPDATA", "")).resolve()
    if os.name == "nt" and roaming.parts and p.is_relative_to(roaming):
        pkgs = Path(os.environ["LOCALAPPDATA"]) / "Packages"
        for pkg in pkgs.glob("Claude_*"):
            cand = pkg / "LocalCache" / "Roaming" / p.relative_to(roaming)
            if cand.exists():
                return str(cand)
    return str(p)


def record_desktop(scene: Path, out: Path, workdir: Path = Path("."), vnc: bool = False) -> int:
    # resolve() は MSIX の振り替え先を返すことがあり作業フォルダと食い違うため、相対パスは absolute() で求める
    work = workdir.absolute()
    rel_scene = Path(os.path.relpath(scene.absolute(), work)).as_posix()
    rel_out = Path(os.path.relpath(out.absolute(), work)).as_posix()
    # 作業フォルダ（シーンと出力）を /work に、ツール本体を /opt/demo-kit/demo に読み取り専用で渡す。
    # これでシーンをキットの外（利用者のリポジトリなど）に置いても desktop 録画できる。
    pkg = Path(__file__).parent
    cmd = ["docker", "run", "--rm", "--name", "demo-rec", "--network", NETWORK, "--shm-size=1g",
           "-v", f"{host_path(work)}:/work", "-v", f"{host_path(pkg)}:/opt/demo-kit/demo:ro",
           "-e", "PYTHONPATH=/opt/demo-kit"]
    if hasattr(os, "getuid"):
        # Linux では出力ファイルが root 所有にならないよう、ホストの uid/gid で動かす
        cmd += ["--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp/home"]
    # noVNC(6080): host ネットワークならそのまま見える。container: 相乗りのときは対象アプリ側で 6080 を公開しておく
    cmd += [IMAGE, rel_scene, "--out", rel_out] + (["--vnc"] if vnc else [])
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    return subprocess.run(cmd, env=env).returncode
