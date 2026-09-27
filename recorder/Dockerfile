# P3 デスクトップ録画環境。computer-use-demo の Dockerfile を参考に、撮影に要る部品だけを入れる。
#   Xvfb（仮想画面） + openbox（WM） + xdotool（実カーソル） + ffmpeg x11grab（画面録画）
#   + LibreOffice Calc（ダウンロードしたファイルを開く） + x11vnc/noVNC（撮影中の目視）
# ブラウザ操作は P2 と同じ Playwright ランナーを headed で使う。
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

ENV DEBIAN_FRONTEND=noninteractive LANG=ja_JP.UTF-8 LC_ALL=ja_JP.UTF-8 TZ=Asia/Tokyo
RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb openbox xdotool wmctrl x11-xserver-utils x11-utils dmz-cursor-theme \
      ffmpeg \
      libreoffice-calc libreoffice-l10n-ja libreoffice-gtk3 \
      fonts-noto-cjk locales \
      x11vnc novnc websockify \
    && sed -i 's/# ja_JP.UTF-8/ja_JP.UTF-8/' /etc/locale.gen && locale-gen \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
# ベースイメージはブラウザ同梱だが Python パッケージは入っていない
RUN pip install --no-cache-dir --break-system-packages playwright==1.63.0 pyyaml jsonschema numpy pillow openpyxl \
    && python -m playwright install chromium

WORKDIR /work
ENV DISPLAY=:99 XCURSOR_THEME=DMZ-Black XCURSOR_SIZE=32
ENTRYPOINT ["python", "-m", "demo.desktop"]
