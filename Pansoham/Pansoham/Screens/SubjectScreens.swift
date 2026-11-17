//
//  SubjectScreens.swift
//  판서함
//
//  15 과목 상세 · 수업별 / 16 과목 상세 · 카드 모아 보기
//

import SwiftUI

// MARK: - 과목 화면 공통 (위 막대 + 제목 + 보기 전환)

/// 뒤로 · 검색 · 더 보기가 있는 위 막대. 검색 중이면 검색창으로 바뀌어요.
struct FolderNavBar<MenuItems: View>: View {
    var backTitle: String
    var onBack: () -> Void
    @Binding var searching: Bool
    @Binding var query: String
    var canSearch: Bool
    let menu: MenuItems

    init(backTitle: String = "판서함", onBack: @escaping () -> Void = {},
         searching: Binding<Bool> = .constant(false), query: Binding<String> = .constant(""),
         canSearch: Bool = true, @ViewBuilder menu: () -> MenuItems) {
        self.backTitle = backTitle
        self.onBack = onBack
        self._searching = searching
        self._query = query
        self.canSearch = canSearch
        self.menu = menu()
    }

    var body: some View {
        if searching {
            FolderSearchField(text: $query) { searching = false; query = "" }
                .padding(.horizontal, 48)
                .frame(width: DS.width, height: 56)
                .background(Color.white)
                .at(0, 24)
        } else {
            NavBar(backTitle: backTitle, title: "", onBack: onBack) {
                FolderActions(spacing: 24, canSearch: canSearch, onSearch: { searching = true }) { menu }
            }
        }
    }
}

/// 위 막대 오른쪽의 검색 · 더 보기 버튼
struct FolderActions<MenuItems: View>: View {
    var spacing: CGFloat = 20
    var canSearch = true
    var onSearch: () -> Void = {}
    @ViewBuilder var menu: MenuItems

    var body: some View {
        HStack(spacing: spacing) {
            if canSearch {
                Button(action: onSearch) { Image("search-24") }
                    .buttonStyle(.plain)
                    .accessibilityLabel("검색")
            }
            Menu { menu } label: { Image("more-24") }
                .menuStyle(.button)
                .buttonStyle(.plain)
                .accessibilityLabel("더 보기")
        }
    }
}

/// 검색창 (돋보기 · 입력 · 지우기 · 취소)
struct FolderSearchField: View {
    @Binding var text: String
    var onCancel: () -> Void
    @FocusState private var focused: Bool

    var body: some View {
        HStack(spacing: 12) {
            HStack(spacing: 8) {
                Image("search-24")
                TextField("검색", text: $text)
                    .font(.system(size: 17))
                    .focused($focused)
                    .submitLabel(.search)
                if !text.isEmpty {
                    Button { text = "" } label: {
                        Image(systemName: "xmark.circle.fill").foregroundStyle(Color.dsSub)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 12)
            .frame(height: 44)
            .background(Color.black.opacity(0.05))
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            Button(action: onCancel) { Text("취소").ds(17, .medium) }
                .buttonStyle(.plain)
        }
        .onAppear { focused = true }
    }
}

/// 검색 결과가 없을 때
struct NoSearchResult: View {
    let query: String
    var body: some View {
        Text("‘\(query)’ 검색 결과가 없어요").ds(17, .medium, .dsSub)
            .padding(.vertical, 24)
    }
}

/// 과목 · 미분류함 더 보기 메뉴
struct FolderMenu: View {
    let router: Router
    /// 보기 전환 (예: ("카드 모아 보기", .subjectCards)). 없으면 빼요.
    var switchTo: (title: String, screen: Screen)? = nil

    var body: some View {
        Button { router.push(.capture) } label: { Label("판서 찍기", systemImage: "camera") }
        if let switchTo {
            Button { router.replace(switchTo.screen) } label: {
                Label(switchTo.title, systemImage: "rectangle.grid.1x2")
            }
        }
        Button { router.push(.allSemesters) } label: { Label("전체 학기", systemImage: "folder") }
    }
}

/// 검색어가 글자들 중 하나에 들어 있는지 (빈 검색어면 모두 통과)
func matches(_ query: String, _ fields: [String]) -> Bool {
    let q = query.trimmingCharacters(in: .whitespaces)
    return q.isEmpty || fields.contains { $0.localizedCaseInsensitiveContains(q) }
}

/// 과목 이름 · 설명 · (수업별 | 카드 모아 보기)
struct SubjectHeader: View {
    let name: String
    let detail: String
    /// 0 수업별, 1 카드 모아 보기. nil 이면 전환 단추를 숨겨요.
    var mode: Int? = nil
    var onMode: (Int) -> Void = { _ in }

    var body: some View {
        HStack(alignment: .bottom) {
            VStack(alignment: .leading, spacing: 6) {
                Text(name).ds(34, .bold)
                Text(detail).ds(17, .regular, .dsSub)
            }
            Spacer()
            if let mode {
                HStack(spacing: 2) {
                    chip("수업별", on: mode == 0) { onMode(0) }
                    chip("카드 모아 보기", on: mode == 1) { onMode(1) }
                }
                .padding(4)
                .background(Color.black.opacity(0.05))
                .clipShape(Capsule())
            }
        }
        .frame(width: 1098)
        .at(48, 92)
    }

    private func chip(_ title: String, on: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).ds(15, on ? .bold : .medium, on ? .black : .dsSub)
                .padding(.horizontal, 18)
                .padding(.vertical, 8)
                .background(on ? Color.white : Color.clear)
                .clipShape(Capsule())
                .shadow(color: .black.opacity(on ? 0.12 : 0), radius: 1.5, x: 0, y: 1)
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
    }
}

/// 오른쪽 아래 촬영 버튼
struct CaptureFAB: View {
    var action: () -> Void = {}

    var body: some View {
        Button(action: action) {
            Image("camera-30")
                .frame(width: 72, height: 72)
                .background(Color.black)
                .clipShape(Circle())
                .shadow(color: .black.opacity(0.22), radius: 14, x: 0, y: 10)
        }
        .buttonStyle(.plain)
        .at(1082, 722)
    }
}

/// 판서 사진 미리보기 (168 × 112, 사진 일부를 잘라 보여 줘요)
struct LessonThumb: View {
    let x: CGFloat
    let y: CGFloat

    var body: some View {
        BoardPhoto(width: 168, height: 112, scaleX: 1.6667, scaleY: 1.8762, x: x, y: y, radius: 14)
    }
}

/// 회색 알약 모양 꼬리표
struct TagChip: View {
    let title: String
    var plain = false

    var body: some View {
        Text(title).ds(13, .medium, plain ? .dsSub : .black)
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(plain ? Color.clear : Color.black.opacity(0.05))
            .clipShape(Capsule())
    }
}

// MARK: - 15 과목 상세 · 수업별

struct SubjectLessonsScreen: View {
    @Environment(Router.self) private var router

    private struct Lesson: Identifiable {
        let id: Int
        let date: String
        let summary: String
        let today: Bool
        let thumbs: [(CGFloat, CGFloat)]
        let tags: [String]
        var more: String? = nil
    }

    @State private var searching = false
    @State private var query = ""
    private var shownLessons: [Lesson] { lessons.filter { matches(query, [$0.date] + $0.tags) } }

    private let lessons: [Lesson] = [
        .init(id: 0, date: "11월 17일 (월)", summary: "사진 2장 · 카드 5개", today: true,
              thumbs: [(-0.3333, -0.5629), (-0.0333, -0.8443)],
              tags: ["스택의 연산", "분할 정복 점화식", "주의", "결론", "예시 코드"]),
        .init(id: 1, date: "11월 10일 (월)", summary: "사진 3장 · 카드 8개", today: false,
              thumbs: [(-0.6333, -0.1501), (-0.6333, -0.8443), (-0.0333, -0.1876)],
              tags: ["큐의 연산", "원형 큐 인덱스", "덱", "큐 vs 스택", "오버플로 조건", "예시 코드"], more: "+2"),
        .init(id: 2, date: "11월 3일 (월)", summary: "사진 4장 · 카드 4개", today: false,
              thumbs: [(-0.3333, -0.5629), (-0.0333, -0.8443), (-0.6333, -0.1501), (-0.6333, -0.8443)],
              tags: ["연결 리스트", "노드 삽입", "노드 삭제", "이중 연결 리스트"]),
    ]

    var body: some View {
        Adaptive { wide } narrow: { narrow($0) }
    }

    private var wide: some View {
        DesignCanvas {
            FolderNavBar(onBack: { router.popTo(.home) }, searching: $searching, query: $query) {
                FolderMenu(router: router, switchTo: ("카드 모아 보기", .subjectCards))
            }
            SubjectHeader(name: "자료구조", detail: "월 10:30–12:00 · 판서 12장 · 카드 34개", mode: 0) { mode in
                if mode == 1 { router.replace(.subjectCards) }
            }

            // 수업 목록
            ScrollView(.vertical, showsIndicators: false) {
                VStack(alignment: .leading, spacing: 0) {
                    if shownLessons.isEmpty { NoSearchResult(query: query) }
                    ForEach(shownLessons) { lesson in
                        Button { router.push(.result) } label: { row(lesson) }
                            .buttonStyle(.plain)
                    }
                }
                .padding(.bottom, 120)
            }
            .frame(width: 1098, height: 638, alignment: .top)
            .at(48, 196)

            // 아래로 갈수록 흐려지기
            LinearGradient(colors: [.white.opacity(0), .white], startPoint: .top, endPoint: .bottom)
                .frame(width: DS.width, height: 80)
                .allowsHitTesting(false)
                .at(0, 754)

            CaptureFAB { router.push(.capture) }
        }
    }

    private func row(_ lesson: Lesson) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                HStack(spacing: 10) {
                    Text(lesson.date).ds(20, .bold)
                    if lesson.today {
                        Text("오늘").ds(12, .bold, .white)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 3)
                            .background(Color.dsBlue)
                            .clipShape(Capsule())
                    }
                }
                Spacer()
                HStack(spacing: 2) {
                    Text(lesson.summary).ds(15, .medium, .dsSub)
                    Image("chevron-right-20")
                }
            }
            HStack(spacing: 12) {
                ForEach(Array(lesson.thumbs.enumerated()), id: \.offset) { _, thumb in
                    LessonThumb(x: thumb.0, y: thumb.1)
                }
            }
            HStack(spacing: 8) {
                ForEach(lesson.tags, id: \.self) { TagChip(title: $0) }
                if let more = lesson.more { TagChip(title: more, plain: true) }
            }
        }
        .padding(.vertical, 22)
        .frame(width: 1098, alignment: .leading)
        .overlay(alignment: .bottom) {
            if lesson.id < lessons.count - 1 {
                Rectangle().fill(Color.dsLine).frame(height: 1)
            }
        }
        .contentShape(Rectangle())
    }
}

// MARK: - 16 과목 상세 · 카드 모아 보기

struct SubjectCardsScreen: View {
    @Environment(Router.self) private var router
    @State private var filter = "전체"
    @State private var selection: Set<Int> = [1, 2, 3]
    @State private var copiedCount: Int?     // 좁은 화면에서 방금 복사한 카드 수
    @State private var searching = false
    @State private var query = ""

    private let all = SampleData.subjectStickers
    private let filters: [(name: String, count: Int)] = [("전체", 34), ("수식", 9), ("코드", 6), ("텍스트", 19)]

    private var visible: [Sticker] {
        (filter == "전체" ? all : all.filter { $0.kind == filter })
            .filter { matches(query, [$0.title, $0.text]) }
    }

    /// 카드를 세 줄에 차례로 나눠 담아요 (1·4·7 / 2·5·8 / 3·6·9).
    private var columns: [[Sticker]] {
        var result: [[Sticker]] = [[], [], []]
        for (index, sticker) in visible.enumerated() { result[index % 3].append(sticker) }
        return result
    }

    var body: some View {
        Adaptive { wide } narrow: { narrow($0) }
    }

    private var wide: some View {
        DesignCanvas {
            FolderNavBar(onBack: { router.popTo(.home) }, searching: $searching, query: $query) {
                FolderMenu(router: router, switchTo: ("수업별로 보기", .subjectLessons))
            }
            SubjectHeader(name: "자료구조", detail: "월 10:30–12:00 · 판서 12장 · 카드 34개", mode: 1) { mode in
                if mode == 0 { router.replace(.subjectLessons) }
            }

            // 필터
            HStack(spacing: 8) {
                ForEach(filters, id: \.name) { item in
                    let on = filter == item.name
                    Button { withAnimation(.easeInOut(duration: 0.15)) { filter = item.name } } label: {
                        Text("\(item.name) \(item.count)").ds(14, .bold, on ? .white : .black)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 8)
                            .background(on ? Color.black : Color.black.opacity(0.05))
                            .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)
                }
            }
            .at(48, 196)

            // 카드 격자
            ScrollView(.vertical, showsIndicators: false) {
                HStack(alignment: .top, spacing: 16) {
                    ForEach(Array(columns.enumerated()), id: \.offset) { _, column in
                        VStack(spacing: 16) {
                            ForEach(column) { sticker in
                                StickerCard(sticker: sticker, width: 355,
                                            selected: selection.contains(sticker.id),
                                            onTap: { router.push(.cardDetail) },
                                            onCopy: { toggle(sticker.id) },
                                            onSelect: { toggle(sticker.id) })
                            }
                        }
                        .frame(width: 355, alignment: .top)
                    }
                }
                .padding(1)
                .padding(.bottom, 24)
            }
            .frame(width: 1100, height: 478, alignment: .topLeading)
            .at(47, 251)

            // 선택 막대
            HStack {
                HStack(spacing: 20) {
                    Text("\(selection.count)개 선택됨").ds(17, .bold)
                    Button { selection = Set(visible.map(\.id)) } label: {
                        Text("모두 선택").ds(17, .medium, .dsSub)
                    }
                    .buttonStyle(.plain)
                }
                Spacer()
                HStack(spacing: 12) {
                    Button { selection = [] } label: {
                        Text("취소").ds(17, .bold)
                            .padding(.horizontal, 24)
                            .frame(height: 56)
                            .background(Color.black.opacity(0.05))
                            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                    }
                    .buttonStyle(.plain)
                    PrimaryButton(title: "\(selection.count)개 복사", enabled: !selection.isEmpty) {
                        Clipboard.copy(selectedText)
                        router.push(.splitView)
                    }
                }
            }
            .padding(.horizontal, 48)
            .frame(width: DS.width, height: 104)
            .background(Color.white)
            .overlay(alignment: .top) { Rectangle().fill(Color.dsLine).frame(height: 1) }
            .at(0, 730)
        }
    }

    private func toggle(_ id: Int) {
        if selection.contains(id) { selection.remove(id) } else { selection.insert(id) }
    }
}

// MARK: - 18 과목 상세 · 빈 상태

struct SubjectEmptyScreen: View {
    @Environment(Router.self) private var router

    var body: some View {
        Adaptive { wide } narrow: { narrow($0) }
    }

    private var wide: some View {
        DesignCanvas {
            FolderNavBar(onBack: { router.pop() }, canSearch: false) { FolderMenu(router: router) }
            SubjectHeader(name: "운영체제", detail: "금 10:30–12:00 · 판서 0장", mode: 0)

            VStack(spacing: 0) {
                Image("folder-empty-72")
                Color.clear.frame(width: 1, height: 20)
                Text("아직 찍은 판서가 없어요").ds(22, .bold)
                Color.clear.frame(width: 1, height: 8)
                Text("금요일 10:30 수업 시간에 찍으면 여기로 모여요").ds(17, .regular, .dsSub)
                Color.clear.frame(width: 1, height: 28)
                PrimaryButton(title: "판서 찍기") { router.push(.capture) }
            }
            .frame(width: DS.width)
            .at(0, 330)
        }
    }
}

// MARK: - 좁은 화면 (스플릿 뷰)


extension SubjectLessonsScreen {
    func narrow(_ size: CGSize) -> some View {
        NarrowPage(backTitle: "판서함", onBack: { router.popTo(.home) },
                   title: "자료구조", detail: "월 10:30–12:00 · 판서 12장 · 카드 34개",
                   trailing: {
            FolderActions(onSearch: { searching = true }) {
                FolderMenu(router: router, switchTo: ("카드 모아 보기", .subjectCards))
            }
        }, content: {
            if searching { FolderSearchField(text: $query) { searching = false; query = "" } }
            NarrowModeToggle(mode: 0) { mode in
                if mode == 1 { router.replace(.subjectCards) }
            }

            VStack(alignment: .leading, spacing: 0) {
                if shownLessons.isEmpty { NoSearchResult(query: query) }
                ForEach(shownLessons) { lesson in
                    Button { router.push(.result) } label: {
                        VStack(alignment: .leading, spacing: 12) {
                            HStack {
                                HStack(spacing: 8) {
                                    Text(lesson.date).ds(18, .bold)
                                    if lesson.today {
                                        Text("오늘").ds(12, .bold, .white)
                                            .padding(.horizontal, 10)
                                            .padding(.vertical, 3)
                                            .background(Color.dsBlue)
                                            .clipShape(Capsule())
                                    }
                                }
                                Spacer(minLength: 0)
                                Image("chevron-right-20")
                            }
                            Text(lesson.summary).ds(14, .medium, .dsSub)
                            ScrollView(.horizontal, showsIndicators: false) {
                                HStack(spacing: 10) {
                                    ForEach(Array(lesson.thumbs.enumerated()), id: \.offset) { _, thumb in
                                        LessonThumb(x: thumb.0, y: thumb.1).scaledBox(168, 112, to: 132)
                                    }
                                }
                            }
                            Flow(spacing: 8) {
                                ForEach(lesson.tags, id: \.self) { TagChip(title: $0) }
                                if let more = lesson.more { TagChip(title: more, plain: true) }
                            }
                        }
                        .padding(.vertical, 18)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .overlay(alignment: .bottom) {
                            if lesson.id < lessons.count - 1 { Rectangle().fill(Color.dsLine).frame(height: 1) }
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.bottom, 80)
        }, bottom: { EmptyView() })
        .overlay(alignment: .bottomTrailing) {
            NarrowFAB { router.push(.capture) }.padding(20)
        }
    }
}

extension SubjectCardsScreen {
    func narrow(_ size: CGSize) -> some View {
        let inner = size.width - 40
        let columnCount = inner >= 520 ? 2 : 1
        let cardWidth = (inner - 12 * CGFloat(columnCount - 1)) / CGFloat(columnCount)
        return NarrowPage(backTitle: "판서함", onBack: { router.popTo(.home) },
                          title: "자료구조", detail: "월 10:30–12:00 · 판서 12장 · 카드 34개",
                          trailing: {
            FolderActions(onSearch: { searching = true }) {
                FolderMenu(router: router, switchTo: ("수업별로 보기", .subjectLessons))
            }
        }, content: {
            if searching { FolderSearchField(text: $query) { searching = false; query = "" } }
            NarrowModeToggle(mode: 1) { mode in
                if mode == 0 { router.replace(.subjectLessons) }
            }

            Flow(spacing: 8) {
                ForEach(filters, id: \.name) { item in
                    let on = filter == item.name
                    Button { withAnimation(.easeInOut(duration: 0.15)) { filter = item.name } } label: {
                        Text("\(item.name) \(item.count)").ds(14, .bold, on ? .white : .black)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 8)
                            .background(on ? Color.black : Color.black.opacity(0.05))
                            .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)
                }
            }

            // 카드 (너비에 따라 한 줄 또는 두 줄)
            HStack(alignment: .top, spacing: 12) {
                ForEach(0..<columnCount, id: \.self) { column in
                    VStack(spacing: 12) {
                        ForEach(visible.indices.filter { $0 % columnCount == column }, id: \.self) { index in
                            let sticker = visible[index]
                            StickerCard(sticker: sticker, width: cardWidth,
                                        selected: selection.contains(sticker.id),
                                        onTap: { router.push(.cardDetail) },
                                        onCopy: { toggle(sticker.id) },
                                        onSelect: { toggle(sticker.id) })
                        }
                    }
                    .frame(width: cardWidth, alignment: .top)
                }
            }
        }, bottom: {
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(selection.count)개 선택됨").ds(15, .bold)
                    Button { selection = Set(visible.map(\.id)) } label: {
                        Text("모두 선택").ds(14, .medium, .dsSub)
                    }
                    .buttonStyle(.plain)
                }
                Spacer(minLength: 0)
                GrayButton(title: "취소") { selection = [] }
                PrimaryButton(title: "\(selection.count)개 복사", width: inner < 440 ? 120 : 180, enabled: !selection.isEmpty) {
                    copySelection()
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 14)
            .background(Color.white)
            .overlay(alignment: .top) { Rectangle().fill(Color.dsLine).frame(height: 1) }
            .overlay(alignment: .top) {
                if let copiedCount {
                    HStack(spacing: 10) {
                        Image("check-circle-24")
                        Text("카드 \(copiedCount)개를 복사했어요").ds(15, .bold, .white)
                    }
                    .padding(.leading, 18)
                    .padding(.trailing, 24)
                    .padding(.vertical, 14)
                    .background(Color.black)
                    .clipShape(Capsule())
                    .shadow(color: .black.opacity(0.25), radius: 16, x: 0, y: 12)
                    .offset(y: -68)
                    .transition(.opacity.combined(with: .offset(y: 40)))
                }
            }
        })
    }

    /// 고른 카드 글자를 한데 이은 것 (카드 사이 빈 줄)
    var selectedText: String {
        all.filter { selection.contains($0.id) }.map(\.text).joined(separator: "\n\n")
    }

    /// 고른 카드의 글자를 클립보드에 넣고 알림을 잠깐 띄워요.
    private func copySelection() {
        Clipboard.copy(selectedText)
        withAnimation(.easeOut(duration: 0.5).delay(0.1)) { copiedCount = selection.count }
        Task {
            try? await Task.sleep(for: .seconds(2.2))
            withAnimation(.easeIn(duration: 0.25)) { copiedCount = nil }
        }
    }
}

extension SubjectEmptyScreen {
    func narrow(_ size: CGSize) -> some View {
        NarrowPage(backTitle: "판서함", onBack: { router.pop() },
                   title: "운영체제", detail: "금 10:30–12:00 · 판서 0장",
                   trailing: { FolderActions(canSearch: false) { FolderMenu(router: router) } }, content: {
            NarrowModeToggle(mode: 0)

            VStack(spacing: 0) {
                Image("folder-empty-72")
                Color.clear.frame(width: 1, height: 20)
                Text("아직 찍은 판서가 없어요").ds(22, .bold)
                Color.clear.frame(width: 1, height: 8)
                Text("금요일 10:30 수업 시간에 찍으면 여기로 모여요")
                    .dsWrap(15, .regular, .dsSub)
                    .multilineTextAlignment(.center)
                Color.clear.frame(width: 1, height: 24)
                PrimaryButton(title: "판서 찍기") { router.push(.capture) }
            }
            .frame(maxWidth: .infinity)
            .padding(.top, size.height * 0.14)
        }, bottom: { EmptyView() })
    }
}
