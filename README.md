# comseba

수행평가 보조 AI CLI — 교사용 인터랙티브 평가 보조 도구.

학생별 진로 텍스트, 카카오톡 스크린샷, 평가 기준 이미지, 제출물(PDF/이미지/텍스트)을
입력받아 루브릭 추출 → 수행평가 제안 → 항목별 피드백 → 예시 답안 → Markdown 보고서 →
학부모 문자 초안까지 한 번에 생성합니다. 모든 데이터는 로컬에만 저장됩니다.

## 요구 사항

- Python 3.11 이상
- Anthropic API 키 ([console.anthropic.com](https://console.anthropic.com/settings/keys))

## 설치

```bash
git clone git@github.com:jdh4601/comseba.git
cd comseba

python -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
```

## API 키 설정

`.env.example` 을 복사해서 `.env` 를 만들고 키를 채워 넣으세요.

```bash
cp .env.example .env
# .env 파일을 열어 ANTHROPIC_API_KEY=... 입력
```

`.env` 는 `.gitignore` 에 등록되어 있어 커밋되지 않습니다.

## 동작 확인 (smoke test)

API 키와 네트워크가 정상이면 한 줄짜리 응답이 출력됩니다.

```bash
python scripts/smoke_test.py
# [smoke] OK — model=claude-sonnet-4-6 reply='안녕하세요'
```

## 사용

```bash
comseba
# 또는
python -m comseba
```

CLI 가 단계별로 안내합니다.

1. 학생 이름 입력
2. 신규 / 기존 세션 선택 (이전 세션은 완료된 단계를 건너뛰고 재개)
3. 진로 텍스트 + (선택) 카카오톡 스크린샷 → 학생 프로필 생성
4. 평가기준 이미지 업로드 → 추출된 루브릭 교사 확인
5. 수행평가 아이디어 제안 (스킵 가능)
6. 제출물 입력 (PDF / 이미지 파일 또는 직접 텍스트)
7. 항목별 피드백 + 예시 답안 + Markdown 보고서 + 학부모 문자 초안 자동 저장

오류 발생 시 친화적 메시지가 출력됩니다. 디버깅이 필요하면:

```bash
comseba --debug
```

## 데이터 저장 위치

세션 결과는 다음 경로에 저장됩니다 (gitignore 됨):

```
students/
  {학생이름}/
    YYYY-MM-DD_session{N}/
      session.json
      rubric.json
      evaluation.json
      report.md
      sms.txt
```

## 개발

```bash
pytest                # 테스트 실행
ruff check .          # 린트
mypy src              # 타입 체크
```

## 라이선스

MIT
