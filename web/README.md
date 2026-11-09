# 시험 자동 채점기 — Cloudflare 웹 버전

정답지·학생 시험지(hwp, hwpx, pdf, jpg/png 등)를 올리면 Worker가 읽고 Claude로 채점합니다.
HWP/HWPX는 Worker에서 텍스트를 직접 추출하고, PDF(스캔본 포함)와 이미지는 Claude가 직접 읽습니다.

## 배포 (본인 PC, 최초 1회)
    cd web
    npm install
    npx wrangler login
    npx wrangler secret put ANTHROPIC_API_KEY     # Claude API 키
    npx wrangler secret put APP_PASSWORD          # 접속 비밀번호 (미설정 시 서버가 모든 요청을 거부)
    npx wrangler deploy

배포되면 `https://grader.<계정>.workers.dev` 주소가 출력됩니다.
더 엄격히 막으려면 Cloudflare Zero Trust → Access 에서 이 주소에 로그인 정책을 추가하세요.

## 로컬 실행/테스트
    npm test                          # 파서·채점·인증 테스트
    echo ANTHROPIC_API_KEY=sk-ant-... > .dev.vars && echo APP_PASSWORD=test >> .dev.vars
    npm run dev

## 제한
- 파일당 25MB. 암호가 걸린 HWP는 읽을 수 없음. 이미지는 브라우저에서 JPEG로 줄여서 전송.
- 시험지 내용(이름·학번 포함)은 채점을 위해 Claude API로 전송되며 서버에는 저장하지 않음.
- 결과는 CSV(엑셀에서 열림)로 내려받음. 엑셀(.xlsx) 출력은 PC용 Python 버전에 있음.
