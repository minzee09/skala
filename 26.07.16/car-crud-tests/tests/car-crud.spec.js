// 중고차 목록 관리 CRUD — 종합실습 가이드 기반 E2E 테스트
// 대상: SKALA141_5_김민지_HTML (파일 수정 없음, file:// 로 직접 로드)
const { test, expect } = require('@playwright/test');

const PAGE_URL =
  'file:///Users/minjikim/Desktop/workspace/skala/26.07.16/' +
  encodeURIComponent('SKALA141_5_김민지_HTML') +
  '/index.html';

// 각 테스트마다 alert/confirm 메시지를 수집한다.
let dialogs;

test.beforeEach(async ({ page }) => {
  dialogs = [];
  page.on('dialog', async (dialog) => {
    dialogs.push({ type: dialog.type(), message: dialog.message() });
    await dialog.accept();
  });
  await page.goto(PAGE_URL);
});

// 폼을 유효한 값으로 채우는 헬퍼
async function fillForm(page, car = {}) {
  const v = {
    maker: '제네시스',
    model: 'G80',
    year: '2023',
    mileage: '12000',
    price: '5200',
    fuel: '가솔린',
    status: '판매중',
    ...car,
  };
  await page.locator('#makerInput').selectOption(v.maker);
  await page.locator('#modelInput').fill(v.model);
  await page.locator('#yearInput').fill(v.year);
  await page.locator('#mileageInput').fill(v.mileage);
  await page.locator('#priceInput').fill(v.price);
  await page.locator('#fuelInput').selectOption(v.fuel);
  await page.locator('#statusInput').selectOption(v.status);
}

test('1. 기본 목록 — 현대 쏘나타, 기아 K5가 보인다', async ({ page }) => {
  const cards = page.locator('.car-card');
  await expect(cards).toHaveCount(2);
  await expect(cards.nth(0)).toContainText('현대 쏘나타');
  await expect(cards.nth(1)).toContainText('기아 K5');
  await expect(page.locator('#countText')).toHaveText('전체 2대 / 표시 2대');
  await expect(page.locator('#emptyMessage')).toBeHidden();
});

test('2. 차량 등록 — 입력한 차량이 목록에 추가되고 폼이 초기화된다', async ({
  page,
}) => {
  await fillForm(page);
  await page.locator('#submitButton').click();

  await expect(page.locator('.car-card')).toHaveCount(3);
  const newCard = page.locator('.car-card').nth(2);
  await expect(newCard).toContainText('제네시스 G80');
  await expect(newCard).toContainText('2023년식 · 가솔린 · 12,000km');
  await expect(newCard).toContainText('5,200만원');
  await expect(page.locator('#countText')).toHaveText('전체 3대 / 표시 3대');

  // 등록 후 입력 항목 초기화
  await expect(page.locator('#makerInput')).toHaveValue('');
  await expect(page.locator('#modelInput')).toHaveValue('');
  await expect(page.locator('#yearInput')).toHaveValue('');
  expect(dialogs).toHaveLength(0);
});

test('3. 입력값 검증 — 항목별 alert 메시지가 순서대로 출력된다', async ({
  page,
}) => {
  const submit = page.locator('#submitButton');

  // 제조사 누락
  await submit.click();
  expect(dialogs.at(-1).message).toBe('제조사를 선택하세요.');

  // 모델명 누락
  await page.locator('#makerInput').selectOption('현대');
  await submit.click();
  expect(dialogs.at(-1).message).toBe('모델명을 입력하세요.');

  // 연식 범위(1990 미만)
  await page.locator('#modelInput').fill('그랜저');
  await page.locator('#yearInput').fill('1980');
  await submit.click();
  expect(dialogs.at(-1).message).toContain('연식은 1990년부터');

  // 가격 1 미만
  await page.locator('#yearInput').fill('2020');
  await page.locator('#priceInput').fill('0');
  await submit.click();
  expect(dialogs.at(-1).message).toBe('가격은 1이상 입력하세요.');

  // 주행거리 음수
  await page.locator('#priceInput').fill('1000');
  await page.locator('#mileageInput').fill('-1');
  await submit.click();
  expect(dialogs.at(-1).message).toBe('주행거리는 0이상 입력하세요.');

  // 연료 누락
  await page.locator('#mileageInput').fill('30000');
  await submit.click();
  expect(dialogs.at(-1).message).toBe('연료를 선택하세요.');

  // 검증 실패 동안 목록은 그대로 2대
  await expect(page.locator('.car-card')).toHaveCount(2);
});

test('4. 차량 수정 — 수정 버튼 클릭 시 기존 값이 폼에 들어가고 버튼이 바뀐다', async ({
  page,
}) => {
  await page.locator('.car-card', { hasText: '현대 쏘나타' })
    .getByRole('button', { name: '수정' })
    .click();

  await expect(page.locator('#makerInput')).toHaveValue('현대');
  await expect(page.locator('#modelInput')).toHaveValue('쏘나타');
  await expect(page.locator('#yearInput')).toHaveValue('2021');
  await expect(page.locator('#mileageInput')).toHaveValue('43000');
  await expect(page.locator('#priceInput')).toHaveValue('1850');
  await expect(page.locator('#fuelInput')).toHaveValue('LPG');
  await expect(page.locator('#statusInput')).toHaveValue('판매중');

  await expect(page.locator('#submitButton')).toHaveText('수정 완료');
  await expect(page.locator('#cancelEditButton')).toBeVisible();
});

test('5. 수정 완료 — 값을 바꾸면 카드 내용이 바뀌고 폼이 초기화된다', async ({
  page,
}) => {
  await page.locator('.car-card', { hasText: '기아 K5' })
    .getByRole('button', { name: '수정' })
    .click();

  await page.locator('#priceInput').fill('1500');
  await page.locator('#statusInput').selectOption('판매완료');
  await page.locator('#submitButton').click();

  const card = page.locator('.car-card', { hasText: '기아 K5' });
  await expect(card).toContainText('1,500만원');
  await expect(card).toContainText('판매완료');
  await expect(page.locator('.car-card')).toHaveCount(2); // 수정이지 추가가 아님

  // 폼 초기화 + 버튼 원복
  await expect(page.locator('#modelInput')).toHaveValue('');
  await expect(page.locator('#submitButton')).toHaveText('등록');
  await expect(page.locator('#cancelEditButton')).toBeHidden();
});

test('6. 수정 취소 — 수정 상태가 해제되고 버튼이 다시 등록으로 바뀐다', async ({
  page,
}) => {
  await page.locator('.car-card', { hasText: '현대 쏘나타' })
    .getByRole('button', { name: '수정' })
    .click();
  await page.locator('#cancelEditButton').click();

  await expect(page.locator('#submitButton')).toHaveText('등록');
  await expect(page.locator('#cancelEditButton')).toBeHidden();
  await expect(page.locator('#modelInput')).toHaveValue('');

  // 취소 후 등록하면 수정이 아니라 새 차량으로 추가되어야 한다.
  await fillForm(page);
  await page.locator('#submitButton').click();
  await expect(page.locator('.car-card')).toHaveCount(3);
});

test('7. 차량 삭제 — confirm 확인 시 삭제, 취소 시 유지된다', async ({
  page,
}) => {
  // 취소(dismiss)하면 그대로 2대
  page.removeAllListeners('dialog');
  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toBe('선택한 차량을 삭제할까요?');
    await dialog.dismiss();
  });
  await page.locator('.car-card', { hasText: '현대 쏘나타' })
    .getByRole('button', { name: '삭제' })
    .click();
  await expect(page.locator('.car-card')).toHaveCount(2);

  // 확인(accept)하면 삭제되어 1대
  page.once('dialog', (dialog) => dialog.accept());
  await page.locator('.car-card', { hasText: '현대 쏘나타' })
    .getByRole('button', { name: '삭제' })
    .click();
  await expect(page.locator('.car-card')).toHaveCount(1);
  await expect(page.locator('.car-card')).not.toContainText('쏘나타');
  await expect(page.locator('#countText')).toHaveText('전체 1대 / 표시 1대');
});

test('8. 검색 — 부분 일치, 대소문자 무시, 지우면 전체 복원', async ({
  page,
}) => {
  const search = page.locator('#searchInput');

  await search.fill('현');
  await expect(page.locator('.car-card')).toHaveCount(1);
  await expect(page.locator('.car-card')).toContainText('현대 쏘나타');
  await expect(page.locator('#countText')).toHaveText('전체 2대 / 표시 1대');

  await search.fill('k'); // 소문자로 K5 검색
  await expect(page.locator('.car-card')).toHaveCount(1);
  await expect(page.locator('.car-card')).toContainText('기아 K5');

  await search.fill('없는차');
  await expect(page.locator('.car-card')).toHaveCount(0);
  await expect(page.locator('#emptyMessage')).toBeVisible();

  await search.fill('');
  await expect(page.locator('.car-card')).toHaveCount(2);
});

test('9. 필터 — 판매 상태별로 목록이 바뀐다', async ({ page }) => {
  const filter = page.locator('#statusFilter');

  await filter.selectOption('판매중');
  await expect(page.locator('.car-card')).toHaveCount(1);
  await expect(page.locator('.car-card')).toContainText('현대 쏘나타');

  await filter.selectOption('예약중');
  await expect(page.locator('.car-card')).toHaveCount(1);
  await expect(page.locator('.car-card')).toContainText('기아 K5');

  await filter.selectOption('판매완료');
  await expect(page.locator('.car-card')).toHaveCount(0);
  await expect(page.locator('#emptyMessage')).toBeVisible();

  await filter.selectOption('전체');
  await expect(page.locator('.car-card')).toHaveCount(2);
});

test('10. 새로고침 — 브라우저 저장 없이 처음 예시 데이터로 돌아간다', async ({
  page,
}) => {
  // 하나 등록하고 하나 삭제해서 상태를 바꾼 뒤
  await fillForm(page);
  await page.locator('#submitButton').click();
  await expect(page.locator('.car-card')).toHaveCount(3);

  // 새로고침하면 다시 기본 2대
  await page.reload();
  await expect(page.locator('.car-card')).toHaveCount(2);
  await expect(page.locator('.car-card').nth(0)).toContainText('현대 쏘나타');
  await expect(page.locator('.car-card').nth(1)).toContainText('기아 K5');
});

test('반응형 — 좁은 화면에서 1열로 바뀐다', async ({ page }) => {
  // 넓은 화면: 2열
  await page.setViewportSize({ width: 1280, height: 900 });
  const wide = await page
    .locator('.container')
    .evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(' ').length);
  expect(wide).toBe(2);

  // 좁은 화면(800px 이하): 1열
  await page.setViewportSize({ width: 500, height: 900 });
  const narrow = await page
    .locator('.container')
    .evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(' ').length);
  expect(narrow).toBe(1);
});
