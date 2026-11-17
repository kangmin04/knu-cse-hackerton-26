# 판서함 화면별 고칠 거리

- 기준 디자인: 피그마 `26-knu-cse-hackathon` › `키타가와 마린` 페이지 (01~23, 26장)
- 확인한 것: 피그마 화면 · 지금 SwiftUI 코드(`Pansoham/Pansoham/`) · iPad Pro 13 시뮬레이터 스플릿뷰(1/2, 1/3)
- 확인 날짜: 2026-11-17

우선순위

| 표시 | 뜻 |
|---|---|
| 🔴 | 데모에서 바로 티 남 (눌러도 안 됨, 자리 표시 글자, 잘림) |
| 🟡 | 고치면 좋음 |
| ⚪ | 팀이 정할 것 |

---

## 담당 나누기 (2명)

같은 파일을 둘이 동시에 고치면 충돌이 나서, **파일 단위로** 나눴어요. 자기 파일만 고치고, 상대 파일을 건드려야 하면 먼저 말하기.

| 담당 | 화면 | 맡는 파일 (`Pansoham/Pansoham/`) | 🔴 | 🟡 |
|---|---|---|---|---|
| **A** | 시작 흐름 · 메인 (01~08) | `Screens/OnboardingView.swift` · `Screens/SetupScreens.swift` · `Screens/HomeScreen.swift` | 5 | 7 |
| **B** | 촬영 이후 · 폴더 · 계정 (09~23) + 스플릿뷰 공통 | `Screens/CaptureScreens.swift` · `Screens/ResultScreens.swift` · `Screens/SplitAndDetailScreens.swift` · `Screens/SubjectScreens.swift` · `Screens/UnsortedScreens.swift` · `Screens/SemesterScreens.swift` · `Screens/AccountScreen.swift` · `Narrow.swift` | 7 | 8 |

- A 는 개수는 적지만 사진첩 열기 · 끌어다 놓기(05)가 무거움. B 는 한두 줄짜리가 많음
- `DesignSystem.swift` · `SampleData.swift` 는 공용 — 고칠 일이 생기면 먼저 말하고 한 명만
- ⚪ 항목은 담당 없음 — 둘이(또는 팀이) 정한 뒤 해당 파일 담당이 반영
- 🔴 #4 · #5 · #7 (`모두 보기` · 종 아이콘 · `원본 보기`)은 **갈 화면부터 정해야 함** — 시작 전에 같이 정하기

## 🔴 먼저 고칠 것 (한눈에)

| # | 담당 | 화면 | 고칠 것 | 위치 |
|---|---|---|---|---|
| 1 | A | 04 로그인 | `앱 이름` 자리 표시 글자가 그대로 나옴 → `판서함` | `Screens/SetupScreens.swift` (넓은 화면 · 좁은 화면 2곳) |
| 2 | A | 05 시간표 업로드 | `사진 앨범에서 선택` 이 사진첩을 안 열고 고른 척만 함 | `SetupScreens.swift` `TimetableUploadScreen` |
| 3 | A | 05 시간표 업로드 | "여기에 끌어다 놓으세요"인데 끌어다 놓기 없음 | 같은 곳 (`dropDestination` 없음) |
| 4 | A | 08 메인 | `모두 보기` 가 버튼이 아님 (글자만) | `Screens/HomeScreen.swift:188` |
| 5 | A | 08 메인 | 알림(종) 아이콘이 버튼이 아님 | `HomeScreen.swift` `topBar` |
| 6 | B | 09 촬영 | `앨범` 버튼이 사진첩 대신 오류 화면(11)으로 감 | `Screens/CaptureScreens.swift:87` |
| 7 | B | 12 결과 | `원본 보기` 가 버튼이 아님 | `Screens/ResultScreens.swift:227, 281` |
| 8 | B | 15 · 16 · 19 과목 · 미분류함 | 위 오른쪽 검색 · 더보기 아이콘이 버튼이 아님 | `Screens/SubjectScreens.swift` `FolderNavBar`, `UnsortedScreens.swift:161` |
| 9 | B | 16 카드 모아 보기 | `N개 복사` 가 실제로 복사 안 하고 스플릿 뷰 안내로만 감 | `SubjectScreens.swift:302` |
| 10 | B | 스플릿뷰 (모든 좁은 화면) | 위 막대(뒤로가기 · 제목 · 닫기)가 창 조절 버튼에 가려짐 | `Narrow.swift` `NarrowPage`, `CaptureScreens.swift` |
| 11 | B | 12 · 16 스플릿뷰 | 손글씨 수식 그림이 오른쪽에서 잘림 | `ResultScreens.swift` `Image(ink)` → `.resizable().scaledToFit()` |
| 12 | B | 17 카드 수정 스플릿뷰 | `내용 (LaTeX)` 칸이 한 줄로 잘림 | `SplitAndDetailScreens.swift` `field()` → `axis: .vertical` |

---

## 공통 — 담당 없음 (같이 정하기)

- ⚪ **글꼴** — 피그마는 Noto Sans KR, 앱은 시스템 글꼴. 프로젝트에 글꼴 파일 없음. 맞추려면 글꼴 추가 + `DesignSystem.swift` `ds()` 등 글자 함수만 바꾸면 전체 반영
- ⚪ **데이터가 전부 샘플** — 과목 · 판서 · 카드 · 시간이 `SampleData.swift` 와 화면 안 고정 글자. 지우거나 옮겨도 화면을 나갔다 오면 원래대로. 서버 · AI 파이프라인(PR #3) 연결 때 같이 정하기

## 01~03 온보딩 · 담당 A — `Screens/OnboardingView.swift`

- ⚪ 다 봐도 저장 안 해서 앱을 켤 때마다 다시 나옴 (데모용으로 둘지, `@AppStorage` 로 한 번만)

## 04 로그인 · 담당 A — `Screens/SetupScreens.swift` `LoginScreen`

- ✅ 🔴 `앱 이름` 이 그대로 나옴 → `판서함`
- ✅ 🟡 로고(`app-logo`) 배경이 거의 검정이라 왼쪽 검은 면에 묻힘 → 테두리나 밝은 배경
- 🟡 (확인 필요) 상태 표시줄 시간 글자가 검은 면 위에서 안 보일 수 있음 — 피그마는 흰 글자, 앱은 밝은 모드 고정이라 검정
- ⚪ 카카오 · Apple · 이메일 모두 실제 로그인 없이 다음 화면으로

## 05 시간표 업로드 · 담당 A — `SetupScreens.swift` `TimetableUploadScreen`

- ✅ 🔴 `사진 앨범에서 선택` → `PhotosPicker` 연결
- ✅ 🔴 끌어다 놓기 → `dropDestination(for: Image/Data)` (스플릿뷰로 사진 앱에서 끌어오는 흐름)
- ✅ 🟡 고른 이미지 미리보기가 없음 (문구만 바뀜)

## 06 시간표 확인 · 담당 A — `SetupScreens.swift` `TimetableConfirmScreen`

- ✅ 🟡 "잘못 읽힌 과목은 눌러서 고칠 수 있어요"인데 과목 줄을 눌러도 아무 일 없음
- ✅ 🟡 `과목 추가` 가 과목을 추가하지 않고 지운 과목을 되살리기만 함 (샘플로 초기화)
- ✅ 🟡 왼쪽 원본 캡처가 고른 이미지가 아니라 그려 둔 검은 네모
- ⚪ `이대로 저장` 해도 지운 과목이 홈에 그대로 나옴 (저장 안 함)

## 07 · 08 메인 · 담당 A — `Screens/HomeScreen.swift`

- ✅ 🔴 `모두 보기` 가 버튼이 아님 + 갈 화면이 없음 (옮기지 않은 판서 전체 목록 화면 없음 → 기존 화면에 연결할지, 새로 만들지)
- ✅ 🔴 알림(종) 아이콘이 `Image` 만 있고 버튼이 아님. 피그마에도 알림 화면은 없음 → 연결할 곳 정하기
- ⚪ 지금 수업 · 오늘 수업 · `42분 남음` · `2시간 뒤` · 이번 주 막대가 고정 글자 (지금 시각과 무관)
- ⚪ 프로필 동그라미의 `김` 고정
- 🟡 스플릿뷰: 촬영 버튼이 맨 아래 폴더 카드를 덮음 (스크롤 끝 여백은 있음)

## 09 촬영 · 담당 B — `Screens/CaptureScreens.swift` `CaptureScreen`

- ✅ `앨범` 이 사진첩 대신 오류 화면(11)으로 감 → 사진첩을 열고 고르면 처리 중으로. 오류 화면은 **셔터를 길게 누르면** 나옴 (데모용)
- ⚪ 실제 카메라 없음 — 미리보기가 고정 사진. 셔터는 처리 중 화면으로
- 🟡 `자료구조 폴더에 저장` 이 고정 (지금 수업에 따라 바뀌어야 함)

## 10 처리 중 · 담당 B — `CaptureScreens.swift` `ProcessingScreen`

- ⚪ 시간이 지나면 넘어가는 연출만 있음 (AI 처리 연결 전)
- (확인 못 함) 스플릿뷰에서 너무 빨리 지나가 화면을 못 봄 — 사진(600×450) · 진행 막대(320) 고정 크기라 좁은 창 확인 필요

## 11 오류 · 화면을 찾지 못함 · 담당 B — `CaptureScreens.swift` `CaptureErrorScreen`

- 고칠 것 없음 (`그대로 쓰기` → 결과, `다시 찍기` → 촬영)

## 12 결과 · 13 복사 완료 · 담당 B — `Screens/ResultScreens.swift`

- ✅ `원본 보기` 가 버튼이 아님 → 누르면 원본 판서 사진을 전체 화면으로 (넓은 화면 · 좁은 화면 둘 다)
- 🔴 스플릿뷰: 손글씨 수식(`분할 정복 점화식`) 그림이 잘림 — `Image(ink)` 에 `.resizable()` 없음
- ⚪ 뒤로 가기 글자 `자료구조` 고정

## 14 스플릿 뷰 · 담당 B — `Screens/SplitAndDetailScreens.swift` `SplitViewScreen`

- ⚪ 굿노트를 그려 둔 연출 화면 (실제 스플릿뷰 아님). 아무 데나 누르면 홈으로. 데모에서 이 화면을 쓸지, 실제 스플릿뷰로 시연할지

## 15 · 16 · 18 과목 상세 · 담당 B — `Screens/SubjectScreens.swift`

- ✅ 위 오른쪽 검색 · 더보기 아이콘이 버튼이 아님 → 검색창(카드 제목·내용 / 날짜·태그로 거르기) + 더보기 메뉴(판서 찍기 · 보기 전환 · 전체 학기)
- ✅ `N개 복사` 가 클립보드에 복사하지 않고 스플릿 뷰 화면으로만 감 (결과 화면 `모두 복사` 는 실제 복사함)
- 🟡 스플릿뷰: 필터 칩(`텍스트 19`)이 1/3 폭에서 오른쪽 끝에 딱 붙음 — 더 좁거나 숫자가 커지면 넘침

## 17 카드 상세 · 수정 · 담당 B — `SplitAndDetailScreens.swift` `CardDetailScreen`

- 🟡 `삭제` 가 지우지 않고 뒤로만 감
- 🟡 `저장` 이 고친 내용을 저장하지 않고 뒤로만 감
- 🔴 스플릿뷰: `내용 (LaTeX)` 칸이 한 줄로 잘림 — `TextField(axis: .vertical).lineLimit(3...)`

## 19 · 20 미분류함 · 담당 B — `Screens/UnsortedScreens.swift`

- ✅ 검색 · 더보기 아이콘이 버튼이 아님 → 15 와 같이 (날짜 · 설명으로 거르기)
- ⚪ `과목으로 옮기기` 하면 목록에서 사라지기만 하고 과목 폴더에는 안 들어감

## 21 · 22 학기 · 담당 B — `Screens/SemesterScreens.swift`

- 고칠 것 없음

## 23 내 계정 · 담당 B — `Screens/AccountScreen.swift`

- 🟡 `프로필 수정` 버튼 동작 없음
- 🟡 `기본 촬영 모드` · `기본 펜 색` 줄에 화살표는 있는데 눌러도 아무 일 없음
- 🟡 `계정 삭제` 동작 없음
- ⚪ 알림 토글 상태를 저장 안 함 (화면 나갔다 오면 원래대로)

---

## 스플릿뷰 · 창 크기 · 담당 B (`Narrow.swift`)

각 화면의 좁은 화면 배치(`narrow(...)`)는 그 화면 담당이, 공통 틀(`Narrow.swift`)은 B 가 고쳐요.

iPad Pro 13 시뮬레이터에서 1/2, 1/3 비율로 확인. 배치는 대부분 좁은 화면용으로 잘 바뀜 (카드 2열 → 1열, 폴더 3열 → 2열, 태그 줄바꿈, 썸네일 가로 스크롤).

- 🔴 **위 막대가 창 조절 버튼(빨강 · 노랑 · 초록 점)에 가려짐** — 결과 · 홈 · 과목 · 카드 수정 · 촬영 모두. 1/3 카드 수정에서는 뒤로가기가 `‹` 만 보이고, 촬영은 닫기 `✕` 위에 그대로 겹침
  - `Narrow.swift` `NarrowPage` 의 `.padding(.leading, 12)` 를 창 모드일 때 늘리기
  - 촬영 화면은 위 막대를 따로 그려서 `CaptureScreens.swift` 도 같이 고쳐야 함
- 🟡 **넓은 화면 전환 기준이 `width < height` 뿐** (`Narrow.swift` `Adaptive`) — Stage Manager 의 작은 가로 창(예: 700×500)에서 피그마 화면이 통째로 작아짐. 최소 너비 조건 추가
- 확인 못 한 화면: 온보딩 · 로그인 · 시간표(05 · 06) · 처리 중 · 미분류함 · 학기 · 계정의 좁은 화면
