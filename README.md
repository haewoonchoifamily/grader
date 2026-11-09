# 시험 자동 채점기

## 설치 (Windows, Python 3.10+)
    pip install -r requirements.txt
    set ANTHROPIC_API_KEY=sk-ant-...     (또는 앱 화면에 직접 입력)
    python app.py

## 사용
1. 정답지 선택 (hwp / hwpx / pdf / 이미지)
2. 학생 시험지 여러 개 또는 폴더째 선택
3. ▶ 채점 시작 → 행을 클릭하면 문항별 상세 확인 → 엑셀로 저장

## 채점 방식
- 객관식·단답형: 프로그램이 직접 비교 (① = 3 같은 표기 차이, 띄어쓰기, 복수정답 순서 무시)
- 단답형 불일치·서술형: Claude가 모범답안/채점기준으로 부분점수 판정 + 사유 기록
- 손글씨 인식 신뢰도가 낮거나 확인이 필요한 문항은 "확인 필요 사항"에 표시
- API 키가 없으면 텍스트 기반 파일(hwp/hwpx/pdf)의 객관식·단답형만 채점하는 간이 모드

## 참고
- 암호가 걸린 HWP는 읽을 수 없습니다. 암호 해제 후 사용하세요.
- CLI: python app.py --cli 정답지.hwpx 학생1.pdf 학생2.jpg -o 결과.xlsx
