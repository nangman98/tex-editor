# TeX 편집기

**tex 파일을 고치면 1–3초 안에 옆의 PDF가 바뀌는 macOS용 로컬 편집기다.** 왼쪽에 폴더의 tex 파일 목록, 가운데에 편집기, 오른쪽에 PDF가 있다. 컴파일은 [tectonic](https://tectonic-typesetting.github.io)(XeTeX)이 맡는다. 서버는 Python 표준 라이브러리만 쓴다.

A local, single-window TeX editor for macOS: edit `.tex` on the left, see the PDF update on the right a few seconds after you stop typing. Files changed by other programs (another editor, a script, an AI assistant) also show up live.

## 필요한 것

| 항목 | 비고 |
|---|---|
| macOS | 앱 런처(`make_app.sh`)가 macOS 앱 묶음을 만든다. 서버 자체는 Python만 있으면 돈다 |
| Python 3.8 이상 | 추가 패키지 없음 |
| tectonic | `brew install tectonic`. 처음 컴파일할 때 필요한 TeX 패키지를 내려받는다 |
| Google Chrome (선택) | 있으면 주소창 없는 앱 창으로 연다. 없으면 기본 브라우저로 연다 |
| 인터넷 | 화면이 CodeMirror 5.65.16과 PDF.js 3.11.174를 cdnjs에서 불러온다. 없으면 일반 입력칸과 브라우저 PDF 보기로 바뀐다 |

## 설치

```sh
git clone https://github.com/nangman98/tex-editor.git ~/TeX편집기
zsh ~/TeX편집기/make_app.sh      # ~/Applications/TeX 편집기.app 생성
```

`~/Applications/TeX 편집기.app`을 더블클릭하거나 Dock에 올려 둔다. 저장소를 옮기거나 python3 경로가 바뀌면 `make_app.sh`를 다시 실행한다.

앱 없이 쓰려면 `python3 texview.py [폴더]` 후 브라우저에서 http://127.0.0.1:8765 를 연다.

## 쓰는 법

| 동작 | 결과 |
|---|---|
| 위쪽 경로 칸에 폴더 경로 + "폴더 열기" | 그 폴더의 `.tex/.sty/.bib/.cls`가 왼쪽에 나온다. 최근 폴더는 경로 칸 목록에 남는다 |
| 왼쪽 파일 클릭 | 가운데에서 편집 |
| 입력 후 1.2초 멈춤(자동 저장 켬) 또는 ⌘S | 저장 → 컴파일 → PDF 갱신, 보던 위치 유지 |
| 다른 프로그램이 tex를 고침 | 편집기 내용과 PDF가 따라 바뀐다. 저장하지 않은 내 편집이 있으면 어느 쪽을 남길지 묻는 줄이 뜬다 |
| 위쪽 "본판" | `\documentclass`가 있는 파일 중 PDF로 볼 것. 폴더마다 마지막 선택을 기억 |
| 오른쪽 위 −/+ · 새 창 · 로그 | PDF 확대, 인쇄·저장용 PDF 창, 컴파일 로그. 컴파일 오류가 나면 로그가 자동으로 열림 |

PDF는 폴더에 `컴파일_PDF/`가 있으면 그 안에, 없으면 폴더 바로 아래에 본판 이름(`thesis.tex` → `thesis.pdf`)으로 생긴다.

## 동작 방식

| 부분 | 내용 |
|---|---|
| `texview.py` | 127.0.0.1:8765 HTTP 서버. 1초마다 폴더 안 소스 파일의 수정 시각을 보고 바뀌면 보고 있는 본판을 `tectonic --outdir`로 컴파일한다. 컴파일 중에 또 바뀌면 끝난 뒤 한 번 더 돈다 |
| `index.html` | 화면. 1초마다 컴파일 상태를, 2초마다 열린 파일의 수정 시각을 묻는다. PDF.js로 쪽마다 그린 뒤 한 번에 바꿔 깜빡임 없이 스크롤 위치를 유지한다 |
| `make_app.sh` | `~/Applications/TeX 편집기.app` 생성. 서버가 꺼져 있으면 켜고 창을 연다 |
| `config.json` (자동 생성, git 제외) | 마지막 폴더, 최근 폴더, 폴더별 마지막 본판 |
| `server.log` (git 제외) | 서버 출력과 화면 쪽 JavaScript 오류 |

환경 변수 `TEXVIEW_PORT`, `TEXVIEW_CONFIG`로 포트와 설정 파일 위치를 바꿀 수 있다.

## 안전장치

- **접속 범위** — 서버는 127.0.0.1에만 열린다. 같은 컴퓨터의 브라우저만 접속할 수 있다.
- **파일 범위** — 열어 둔 폴더 밖 경로는 읽기·쓰기 모두 403으로 거절한다.
- **덮어쓰기 방지** — 편집기가 파일을 연 뒤 디스크에서 먼저 바뀐 파일은 저장하지 않고 409로 알린다. 화면에서 디스크 내용을 받을지, 내 편집으로 덮을지 고른다.

## 끄기

앱 창을 닫아도 서버는 남는다. 끄려면 `lsof -ti tcp:8765 | xargs kill`.

## 한계

- Finder에서 tex 파일을 더블클릭해도 이 앱으로 열리지 않는다. 폴더 경로를 넣어 연다.
- 본판 하나만 감시해 컴파일한다. 다른 본판은 "본판"에서 고르면 그때 컴파일한다.
- PDF의 쪽을 모두 다시 그리므로 수백 쪽 문서에서는 갱신이 느려질 수 있다(7쪽 문서에서 1초 이내).
- 소스 위치와 PDF 위치를 잇는 SyncTeX 이동은 없다.

## 검증 (2026-10-28)

시험 폴더에서 화면 편집 "Hello 1 → Hello 2"가 자동 저장되고 약 3초 뒤 PDF에 "Hello 2"로 그려짐을 확인했다. 폴더 밖 경로(`../README.md`) 읽기는 403, 디스크가 먼저 바뀐 파일을 덮어쓰는 저장은 409로 막혔다.
