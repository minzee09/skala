# 중고차 목록 관리 CRUD — 코드 설명 노트

> 바닐라 JS로 구현한 CRUD 실습 정리. 프레임워크 없이 **상태(배열) → 렌더링(DOM 생성) → 이벤트(사용자 입력)** 순환 구조로 동작한다.

---

## 전체 구조 한눈에 보기

```
[cars 배열]  ←― 등록/수정/삭제가 배열을 바꾼다
     │
     ▼
renderCars()  ―→ 배열을 읽어 화면(DOM)을 다시 그린다
     ▲
     │
[이벤트 리스너]  ←― 클릭, 입력, 제출이 위 함수들을 호출한다
```

핵심 원칙: **데이터(배열)가 진실이고, 화면은 데이터의 결과물이다.** 화면을 직접 고치지 않고, 배열을 바꾼 뒤 `renderCars()`로 전체를 다시 그린다. React의 "상태가 바뀌면 리렌더링" 개념의 원형이다.

---

## 1. HTML 요소 가져오기

```js
const carForm = document.querySelector('#carForm');
const makerInput = document.querySelector('#makerInput');
// ... 나머지 입력 요소들
```

- `document.querySelector('#id')` — CSS 선택자로 요소를 **하나** 찾는다. `#`은 id 선택자.
- 파일 맨 위에서 한 번만 찾아 상수에 담아두면, 매번 DOM을 뒤지지 않아도 된다.
- `<script src="app.js" defer></script>`의 **defer** 덕분에 HTML 파싱이 끝난 뒤 실행되므로, 요소를 못 찾는(null) 문제가 없다.

## 2. 상태(데이터) 정의

```js
let cars = [
  { id: 1, maker: '현대', model: '쏘나타', year: 2021, ... },
  { id: 2, maker: '기아', model: 'K5', year: 2020, ... },
];

let editingId = null; // null이면 등록 모드, 숫자면 그 id를 수정 중
```

- 차량 1대 = 객체 1개, 전체 목록 = 객체 배열. 이 배열이 앱의 **단일 진실 공급원(source of truth)**.
- `editingId` 하나로 등록/수정 모드를 구분한다. 별도의 boolean 플래그 없이 "무엇을 수정 중인가"까지 담는 영리한 설계.
- 요구사항대로 localStorage를 쓰지 않으므로 새로고침하면 이 초기값으로 돌아간다.

## 3. 렌더링 — renderCars()

```js
function renderCars() {
  const filteredCars = getFilteredCars();

  carList.innerHTML = ''; // ① 기존 목록을 싹 비우고

  emptyMessage.hidden = filteredCars.length > 0; // ② 빈 목록 메시지 토글
  countText.textContent = `전체 ${cars.length}대 / 표시 ${filteredCars.length}대`;

  filteredCars.forEach(function (car) {
    const card = createCarCard(car); // ③ 카드 DOM을 만들어
    carList.appendChild(card);       // ④ 목록에 붙인다
  });
}
```

- **"비우고 전부 다시 그리기"** 전략. 어떤 카드를 수정/삭제했는지 추적할 필요 없이 항상 배열과 화면이 일치한다.
- `element.hidden = true/false` — HTML의 hidden 속성을 JS로 토글. CSS `display:none`과 같은 효과.
- `` `전체 ${cars.length}대` `` — **템플릿 리터럴**(백틱). 문자열 안에 `${식}`으로 값을 끼워 넣는다.
- 항상 `getFilteredCars()`를 거치므로, 검색어/필터가 걸린 상태에서 등록·삭제해도 화면이 올바르게 나온다.

## 4. 검색 + 필터 — getFilteredCars()

```js
function getFilteredCars() {
  const keyword = searchInput.value.trim().toLowerCase();
  const selectedStatus = statusFilter.value;

  return cars.filter(function (car) {
    const searchText = `${car.maker} ${car.model}`.toLowerCase();
    const matchKeyword = searchText.includes(keyword);
    const matchStatus =
      selectedStatus === '전체' || car.status === selectedStatus;

    return matchKeyword && matchStatus;
  });
}
```

- `Array.filter(콜백)` — 콜백이 true를 반환하는 요소만 모아 **새 배열**을 반환. 원본은 안 건드린다.
- 대소문자 무시: 검색어와 대상 문자열 **양쪽 다** `toLowerCase()` → 'k'로 'K5' 검색 가능.
- 부분 일치: `String.includes(부분문자열)`. 빈 문자열 `''.includes` 는 항상 true라서, 검색어를 지우면 자동으로 전체가 나온다 (별도 처리 불필요).
- 검색 조건과 상태 조건을 `&&`로 묶어 **두 필터가 동시에** 적용된다.

## 5. 카드 DOM 생성 — createCarCard(car)

```js
const card = document.createElement('article');
card.className = 'car-card';

const title = document.createElement('h3');
title.textContent = `${car.maker} ${car.model}`;
// ... p(연식·연료·주행거리), p.price, span.status-badge

const editButton = document.createElement('button');
editButton.dataset.action = 'edit'; // → HTML: data-action="edit"
editButton.dataset.id = car.id;     // → HTML: data-id="1"

card.appendChild(title);
// ... appendChild로 조립 후
return card;
```

- `createElement` + `textContent` + `appendChild` 조합이 바닐라 JS의 기본 DOM 생성 패턴.
- `innerHTML`에 문자열을 붙이지 않고 `textContent`를 쓰는 이유: 사용자 입력이 HTML로 해석되지 않아 **XSS(스크립트 주입)에 안전**하다.
- `dataset.xxx` — 요소에 `data-xxx` 커스텀 속성을 저장. 버튼에 "무슨 동작인지(action)"와 "어느 차인지(id)"를 심어두고, 클릭 이벤트에서 꺼내 쓴다.
- `mileage.toLocaleString()` — 43000 → "43,000" 천 단위 콤마.

## 6. 이벤트 위임 — 수정/삭제 버튼 처리

```js
carList.addEventListener('click', function (event) {
  const action = event.target.dataset.action;
  const id = Number(event.target.dataset.id);

  if (action === 'edit') startEdit(id);
  if (action === 'delete') deleteCar(id);
});
```

- **이벤트 위임(event delegation)**: 카드마다 버튼에 리스너를 붙이지 않고, 부모(`#carList`) 하나에만 붙인다. 클릭이 버블링되어 올라오면 `event.target`(실제 클릭된 요소)으로 판별.
- 장점: 렌더링할 때마다 카드가 새로 만들어져도(innerHTML = '' 후 재생성) 리스너를 다시 붙일 필요가 없다. 리스너는 처음 한 번만 등록.
- `dataset` 값은 항상 **문자열**이므로 `Number()`로 변환해야 `===` 비교가 맞는다.

## 7. 등록 / 수정 — form submit

```js
carForm.addEventListener('submit', function (event) {
  event.preventDefault(); // 폼의 기본 동작(페이지 새로고침) 차단

  const car = getCarFromForm(); // 검증 실패 시 null
  if (car === null) return;

  if (editingId === null) {
    // 등록: 최대 id + 1로 새 id 발급
    const newId = cars.length > 0
      ? Math.max(...cars.map((c) => c.id)) + 1
      : 1;
    car.id = newId;
    cars.push(car);
  } else {
    // 수정: 같은 id의 객체를 새 객체로 교체
    car.id = editingId;
    cars = cars.map((c) => (c.id === editingId ? car : c));
  }

  resetForm();
  renderCars();
});
```

- `event.preventDefault()` — 없으면 submit 순간 페이지가 새로고침되어 모든 데이터가 날아간다. **바닐라 JS 폼 처리의 1번 규칙.**
- 새 id 발급: `cars.map(c => c.id)`로 id만 뽑고 → `Math.max(...배열)`로 최댓값 → +1. 삭제 후에도 id가 겹치지 않는다. (`...`는 배열을 개별 인자로 펼치는 스프레드 문법)
- 수정은 `Array.map`으로 "id가 일치하면 새 객체, 아니면 기존 객체"인 **새 배열**을 만든다. 등록/수정 로직이 하나의 submit 핸들러에 공존하고 `editingId`로 분기하는 게 이 코드의 뼈대.

## 8. 입력값 검증 — getCarFromForm()

```js
const year = Number(yearText);
const maxYear = new Date().getFullYear(); // 올해(2026)

if (maker === '') {
  alert('제조사를 선택하세요.');
  return null;
}
if (yearText === '' || Number.isNaN(year) || year < 1990 || year > maxYear) {
  alert(`연식은 1990년부터 ${maxYear}년 사이로 입력하세요.`);
  return null;
}
// ... 가격 ≥ 1, 주행거리 ≥ 0, 연료 선택 검사
return { maker, model, year, mileage, price, fuel, status };
```

- **조기 반환(early return) 패턴**: 검사 하나 실패 → alert → 즉시 `null` 반환. if-else 중첩 없이 위에서 아래로 읽힌다.
- 호출한 쪽(submit 핸들러)은 `null`인지 여부만 보면 되므로 검증과 저장 로직이 분리된다.
- `Number('')`는 0, `Number('abc')`는 NaN — 그래서 빈 문자열 검사(`yearText === ''`)와 `Number.isNaN()` 검사를 **둘 다** 한다.
- `new Date().getFullYear()`로 연도를 하드코딩하지 않아 해가 바뀌어도 코드 수정이 필요 없다.

## 9. 수정 모드 진입/해제 — startEdit() / resetForm()

```js
function startEdit(id) {
  const car = cars.find((c) => c.id === id); // 배열에서 해당 차 찾기
  if (!car) return;

  makerInput.value = car.maker; // 폼에 기존 값 채우기
  // ... 나머지 필드

  editingId = id;                        // 수정 모드 ON
  submitButton.textContent = '수정 완료'; // 버튼 라벨 교체
  cancelEditButton.hidden = false;       // 취소 버튼 표시
}

function resetForm() {
  editingId = null;             // 등록 모드로 복귀
  carForm.reset();              // 폼의 모든 입력값 초기화 (내장 메서드)
  submitButton.textContent = '등록';
  cancelEditButton.hidden = true;
  modelInput.focus();
}
```

- `Array.find(콜백)` — 조건에 맞는 **첫 요소**를 반환, 없으면 undefined.
- `form.reset()` — 입력칸을 일일이 비울 필요 없이 폼 전체를 한 번에 초기화하는 내장 메서드.
- "수정 취소" 버튼은 `resetForm()`만 호출하면 끝 — 상태와 UI 복구가 한 함수에 모여 있어서 등록 완료·수정 완료·수정 취소·(수정 중 삭제) 어디서든 재사용된다.

## 10. 삭제 — deleteCar()

```js
function deleteCar(id) {
  const ok = confirm('선택한 차량을 삭제할까요?'); // 확인=true, 취소=false
  if (!ok) return;

  cars = cars.filter((car) => car.id !== id); // 해당 id만 빼고 새 배열

  if (editingId === id) resetForm(); // 수정 중이던 차를 지웠다면 폼도 초기화

  renderCars();
}
```

- `confirm()`은 확인/취소 버튼이 있는 대화상자로 boolean을 반환한다. (`alert()`는 확인만 있어서 사용자가 거부할 수 없음 → 삭제 확인에는 confirm이 정답)
- 삭제 = "그 id가 **아닌** 것만 filter로 남기기". 배열에서 직접 빼는(splice) 것보다 안전하고 읽기 쉽다.
- 수정 중인 차량을 삭제하는 **엣지 케이스**까지 처리한 부분이 포인트.

---

## 자주 쓴 배열 메서드 요약

| 메서드 | 반환 | 이 프로젝트에서의 용도 |
|---|---|---|
| `filter(fn)` | 조건에 맞는 요소들의 새 배열 | 검색/필터, 삭제 |
| `map(fn)` | 각 요소를 변환한 새 배열 | 수정(교체), id 목록 뽑기 |
| `find(fn)` | 조건에 맞는 첫 요소 (없으면 undefined) | 수정할 차량 찾기 |
| `forEach(fn)` | 없음 (순회만) | 카드 하나씩 화면에 붙이기 |
| `push(item)` | 새 길이 (원본 변경) | 차량 등록 |

> filter/map/find는 **원본을 바꾸지 않고 새 배열/값을 반환**한다. 그래서 `cars = cars.filter(...)`처럼 재할당하며, `cars`가 `const`가 아니라 `let`인 이유가 이것이다.

## 이벤트 요약

| 대상 | 이벤트 | 하는 일 |
|---|---|---|
| `#carForm` | `submit` | 검증 → 등록 또는 수정 → 리렌더 |
| `#carList` | `click` (위임) | data-action 보고 수정/삭제 분기 |
| `#searchInput` | `input` | 글자 입력마다 리렌더 (실시간 검색) |
| `#statusFilter` | `change` | 선택 변경 시 리렌더 |
| `#cancelEditButton` | `click` | 폼/모드 초기화 |

> `input` 이벤트는 타이핑 즉시, `change`는 값이 확정될 때(select는 선택 즉시) 발생한다.
