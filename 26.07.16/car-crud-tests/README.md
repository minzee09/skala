# 중고차 목록 관리 CRUD — E2E 테스트

`SKALA141_5_김민지_HTML` 폴더의 앱을 종합실습 가이드 PDF 기준으로 검증하는 Playwright 테스트.

## 처음 한 번만

```bash
npm install
npx playwright install chromium
```

## 실행

```bash
npx playwright test              # 전체 실행
npx playwright test -g "검색"    # 이름에 "검색"이 들어간 테스트만
npx playwright test --headed     # 브라우저 창을 띄워서 눈으로 보며 실행
```

## 테스트 항목

1. 기본 목록 (쏘나타, K5)
2. 차량 등록 + 폼 초기화
3. 입력값 검증 (alert 메시지 6종)
4. 수정 버튼 → 폼에 값 로드
5. 수정 완료 → 카드 갱신
6. 수정 취소
7. 삭제 (confirm 확인/취소)
8. 검색 (부분 일치, 대소문자 무시)
9. 판매 상태 필터
10. 새로고침 시 예시 데이터 복원
11. 반응형 (800px 이하 1열)

앱 파일은 `file://`로 직접 로드하므로 서버 없이 동작하며, 앱 코드는 수정하지 않는다.
제출 zip에는 이 폴더를 포함하지 않는다.
