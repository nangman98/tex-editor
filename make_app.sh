#!/bin/zsh
# ~/Applications/TeX 편집기.app 을 만든다(더블클릭 → 서버 켜기 → Chrome 앱 창).
# 저장소 폴더를 옮기거나 python3 경로가 바뀌면 다시 실행한다.
set -e
HERE="${0:A:h}"
PY="$(command -v python3)"
[ -n "$PY" ] || { echo "python3를 찾지 못했습니다"; exit 1; }
command -v tectonic >/dev/null || echo "주의: tectonic이 PATH에 없습니다 (brew install tectonic)"

B="$HOME/Applications/TeX 편집기.app/Contents"
mkdir -p "$B/MacOS"
cat > "$B/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>TeX 편집기</string>
  <key>CFBundleDisplayName</key><string>TeX 편집기</string>
  <key>CFBundleIdentifier</key><string>local.texview</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
EOF
cat > "$B/MacOS/launcher" <<'EOF'
#!/bin/zsh
# 서버(127.0.0.1:8765)가 없으면 켜고, Chrome 앱 창(없으면 기본 브라우저)으로 연다.
APP="@APP@"
PY="@PY@"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
URL="http://127.0.0.1:8765/"
if ! /usr/bin/curl -s -o /dev/null "${URL}api/ping"; then
  nohup "$PY" "$APP/texview.py" >> "$APP/server.log" 2>&1 &
  for i in {1..50}; do /usr/bin/curl -s -o /dev/null "${URL}api/ping" && break; sleep 0.1; done
fi
if [ -d "/Applications/Google Chrome.app" ]; then
  open -na "Google Chrome" --args --app="$URL"
else
  open "$URL"
fi
EOF
sed -i '' -e "s|@APP@|$HERE|" -e "s|@PY@|$PY|" "$B/MacOS/launcher"
chmod +x "$B/MacOS/launcher"
echo "만듦: $HOME/Applications/TeX 편집기.app  (서버 $HERE/texview.py, python $PY)"
