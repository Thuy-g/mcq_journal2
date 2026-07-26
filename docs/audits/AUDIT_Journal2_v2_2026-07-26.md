# Technical & Methodological Audit — Journal 2
### "A Method to Generate Choices with their Rationales for Multiple Choice Questions Using Knowledge Graphs"

**Ngày:** 2026-07-26
**Phạm vi:** `category_extractor_ClaudeWeb_v2.py`, `extract_221_and_select_distractors_ClaudeWeb_v2.py`, `MCQ_lrolesim_ClaudeWeb_v2.py` (+ bản cũ, + `read_ttl.py`, `treat_entity_type.py`, `mcq_generation.py`, `build_bipartite_and_draw_ExtendedVersion.py`, `all_in_one.py`)
**Tài liệu tham chiếu:** `Umematsu_Master_final.pdf`, `Official_LRoleSim_Aug2025.pdf`, `Explainability_of_LRoleSim.pdf`, `MCQ2025_Slides_Seminar20250604_Thuy.pdf`, `Linked_Data…Okuhara.pdf`, `JIP2025_Okuhara.pdf`

---

## 0. Trạng thái kiểm thử (bắt buộc đọc trước)

Tôi phân biệt rõ ba loại, đúng như yêu cầu:

### 0.1 Test ĐÃ CHẠY THẬT trong lượt này

| # | Nội dung | Kết quả |
|---|---|---|
| T0 | `py_compile` trên 11 file | 10/11 OK. **`all_in_one.py` KHÔNG compile** (SyntaxError dòng 369) |
| T0b | `pyflakes` trên 11 file | 4 tên chưa định nghĩa (chi tiết §7) |
| T1 | Chạy `precompute_groups` + `lrolesim_iteration` của bản v2 trên **lõi HanamiSpots 8 node** tái dựng từ Example 2/7/8 của `Official_LRoleSim_Aug2025.pdf` + `jikken_Hanami_EnglishVersion_EntityType.txt` | **KHỚP tuyệt đối** giá trị iteration-1 của Bảng 1 (`Explainability_of_LRoleSim.pdf`) cho **cả 5 độ đo**: rolesim/d/e/ed = 1.000, **edt = 0.600** |
| T2.1 | `extended_edgeset()` với `use_in=True` rồi `use_in=False` | **LỖI XÁC NHẬN** — trả về cùng một kết quả |
| T2.2 | Truy vết `score_norm` trong file | Chỉ xuất hiện ở dòng 340 (khai báo) và 377 (gán). **Dead code** |
| T2.3 | KG tổng hợp: A có f₁ loại d₁,d₂; f₂ loại d₃ | `select_distractor_set()` **trả về 0 distractor** → loại bỏ câu hỏi HỢP LỆ |
| T2.4 | Set cover bitmask k=3 trên cùng dữ liệu | Tìm đúng `R* = {f₁, f₂}`, `\|R*\| = 2`, chi phí O(8m) |
| T2.5 | `remove_parenthetical()` trên 7 chuỗi | `Phosphorus(V)_oxide → "Phosphorus oxide"`, `Iron(III)_chloride → "Iron chloride"` — **hỏng thực thể hóa học** |
| T3.1 | Benchmark `lrolesim_iteration()` n = 300/600/1200 | 16.0 / 4.5 / 5.6 µs mỗi cặp (container chậm; máy bạn nhanh hơn ~2–3×) |
| T3.2 | `Sim.max_delta()` với \|Sim\| = 719.400 | **+167,8 MB** cho MỘT lần gọi → ngoại suy n = 4000: **≈ 1,9 GB** |

### 0.2 Test CHỈ VIẾT, KHÔNG CHẠY ĐƯỢC (thiếu dữ liệu / môi trường)

- `MCQ_lrolesim_ClaudeWeb_v2.py --check-hanami`: cần `data/infobox.pickle_EnglishVersion_EntityType` (không có trong Project).
- Tái lập giá trị **iteration 2 và 3** của Bảng 1 (ví dụ `lrolesim_ed = 0.867`): cần đủ 13 node; tôi chỉ tái dựng chắc chắn được 8 node từ các Example trong bài báo, nên **chỉ khẳng định được iteration 1**.
- Mọi lời gọi SPARQL: `dbpedia.org` **không nằm trong allow-list mạng** của môi trường này.
- SBERT / spaCy / NLTK: **chưa cài** → không đánh giá thực nghiệm được truncation, chỉ phân tích tĩnh.
- `rank_by_similarity()` end-to-end trên DBpedia thật: **chưa chạy**.

### 0.3 Câu KHÔNG được nói

Tôi **không** khẳng định "all tests pass". Tôi **không** khẳng định bản v2 tái lập được số liệu Journal 1 — điều đó chưa được kiểm chứng (xem §5.3.1).

---

## 1. Executive verdict

1. **Ba file v2 compile được**, nhưng **không chạy được như một pipeline** vì lỗi import (§6.1). Đây là blocker số 1.
2. **Blocker phương pháp luận nghiêm trọng nhất:** `extract_221_..._v2.py` **hoàn toàn không dùng LRoleSim**. Không có dòng `import` nào tới `MCQ_lrolesim`. Xếp hạng ứng viên chỉ dùng `OverlapStrict/OverlapLoose` (`rank_candidates()`, dòng 371–373). Điều này mâu thuẫn trực tiếp với slide "Pipeline Overview" và với `README.md` mục 3.
3. **Blocker phương pháp luận thứ hai (và là cơ hội novelty lớn nhất của bạn):** điều kiện khả thi trong `select_distractor_set()` dòng 450–455 và `build_choices()` dòng 507–510 là trường hợp đặc biệt **|R| = 1** — đòi hỏi **một fact duy nhất** loại được **cả ba** distractor. Tôi đã **chạy thật** một ví dụ (T2.3): câu hỏi hoàn toàn hợp lệ với rationale 2 fact **bị code vứt bỏ**. Nghĩa là dòng "*Maybe this kind of condition is too strict!!!*" trong slide Step 4 của bạn **một phần là artifact của code, không phải tính chất của DBpedia**.
4. **Không nhất quán nội bộ:** dòng 415 lọc ứng viên bằng `n_distinguishing > 0` — đây **chính là** điều kiện khả thi đúng của set cover; nhưng dòng 453 lại áp một điều kiện chặt hơn hẳn. Hai chỗ trong cùng một hàm dùng hai định nghĩa khác nhau.
5. **Kernel LRoleSim v2 là TRUNG THỰC với Definition 11–12 của Journal 1** — tôi đã kiểm chứng số học (T1), kể cả trường hợp đặc trưng `edt = 0.600`. Đây là tin tốt: bạn không cần lo bản viết lại làm sai định nghĩa.
6. **Nhưng hàm bao `lrolesim()` thì KHÁC Journal 1**: dòng 256 dùng `max_iter=20, tol=1e-4` (chạy đến hội tụ), trong khi Journal 1 dùng đúng `for _ in range(3)` (`MCQ_lrolesim.py` dòng 961). Theo Theorem 3 (đơn điệu giảm), giá trị hội tụ **luôn ≤** giá trị tại k=3 → **số liệu sẽ khác**. Đây phải là một tham số được công bố, không phải mặc định ẩn.
7. **`make_sorted_list_fn()` dòng 464 làm THAY ĐỔI xếp hạng** so với Journal 1 (`MCQ_lrolesim.py` dòng 975 `sort(reverse=True)` phá hoà bằng chỉ số node). Sửa này **đúng về nguyên tắc**, nhưng nó có nghĩa MRR/NDCG của Journal 1 **không tái lập được bằng file v2**. Phải giữ `MCQ_lrolesim_journal1_archive.py`.
8. **`score_norm` là dead code** (T2.2). Chú thích dòng 374–375 tuyên bố "chuẩn hoá theo bậc" nhưng thực tế **không chuẩn hoá gì cả** — vẫn xếp hạng bằng `-c.score` thô (dòng 381), nên entity nhiều cạnh (Aristotle) vẫn thắng. Đúng cái lỗi mà chú thích nói là đã sửa.
9. **Chi phí LRoleSim đo được**: `lrolesim_iteration()` duyệt `combinations(index_list, 2)`. Với `max_nodes=4000` (mặc định dòng 349) → 7,998,000 cặp/vòng. Trên máy bạn ước ~2 µs/cặp → ~16 s/vòng × tới 20 vòng = **~5 phút/câu**, ×100 câu = **~8 giờ**, và **~3–4 GB RAM đỉnh** (2 bản `Sim` + tập khoá hợp của `max_delta`). Khả thi trên 64 GB nhưng **phải cache theo class, không phải theo câu**.
10. **Luận văn Umematsu KHÔNG chứng minh có "best class" duy nhất.** Ngược lại: *"提案手法では正答語句から**出題者にクラスを指定し**"* — người ra đề chỉ định class. Bản so sánh còn dùng class **ngẫu nhiên**. Vì vậy `choose_best_class_for_answer()` (dòng 445) **đang phóng đại**. Ba chế độ manual / recommended / fallback của bạn **trung thực hơn** với tiền lệ.
11. **OWA:** `distinguishing_facts()` (dòng 389–396) coi *thiếu triple* là *contrast hợp lệ*. Umematsu tránh được điều này bằng cách chỉ lấy *"目的語が一意に決まる述語"* (predicate có object xác định duy nhất). Bạn **phải** khôi phục ràng buộc đó, nếu không rationale sẽ sai dưới Open-World Assumption (§3.4).
12. **Wording đúng cho bài báo:** *"we **apply/integrate** LRoleSim as a distractor plausibility ranker"*, **KHÔNG** phải *"we extend LRoleSim"*. Bạn không sửa gì trong định nghĩa LRoleSim.
13. **Redirect/canonical URI: KHÔNG có trong code v2** (`grep` trả về rỗng). Đây là một *kế hoạch*, không phải một *lỗi đang tồn tại*. Khuyến nghị: **DEFER** (§Phụ lục A).
14. **`remove_parenthetical()` hiện CHỈ dùng cho leak detection** (dòng 295, 296, 305, 308), **không dùng cho display label ở bất cứ đâu**. Vấn đề "A (Makoto Kobayashi (physicist))" đến từ `build_bipartite_and_draw_ExtendedVersion.py`, không phải từ file này. Cần một hàm **riêng** `format_display_label()` (§Phụ lục B).
15. **Yield rate là con số quan trọng nhất bạn chưa đo.** Trước khi tối ưu bất cứ thứ gì, hãy chạy 100 Answer và đếm: bao nhiêu câu ra được 3 distractor + rationale? Không có con số này thì mọi tối ưu đều mù.

---

## 2. Đánh giá các điểm trong câu trả lời trước của Claude

### 2.1 ĐÚNG (giữ nguyên sau khi đọc code)

| Điểm | Bằng chứng |
|---|---|
| `precompute_groups()` chuyển phân hoạch ra ngoài vòng lặp cặp: O(n²d) → O(nd) | Dòng 152–172 v2 vs `MCQ_lrolesim.py` dòng 424 (`create_mats` gọi trong vòng cặp). Đúng về toán, không đổi kết quả |
| Ba đường tắt trong `_max_weight_matching()` (dòng 198–203) là **chính xác**, không phải xấp xỉ | Trọng số `s ∈ [β, 1] > 0` nên assignment cực đại trên ma trận 1×m = `max(row)`. Đúng |
| Nhánh `shared = ∅ → s = β` (dòng 237–243) là **chính xác** theo Definition 11–12 | Không có lớp tương đương chung ⟹ mọi `L(x,y)=0` ⟹ `w(M)=0` ⟹ `s = β`. Trùng khớp với mục 3.4 "best case O(1)" của Journal 1 |
| Thêm cạnh IN (dòng 127–129) là **bắt buộc** | Definition 10: `N′(v) = I′(v) ∪ O′(v)`. Bản cũ chỉ dùng `out_neighbor` (`extract_221….py` dòng 68–73) → mất một nửa thông tin |
| Bỏ double-counting strict/loose (dòng 320) + dùng matching thay vì đếm mọi cặp (dòng 329) | Definition 4: matching là injective. Bản cũ dòng 129–133 đếm mọi cặp → thổi phồng node bậc lớn |
| Blocker import (dòng 37–43) | Xác nhận: `category_extractor.py` gốc **không có** `run_sparql`, `get_nodes_in_class`, `rank_classes_for_answer` |
| LRoleSim không nằm trong pipeline distractor | Xác nhận: `grep -n "MCQ_lrolesim" extract_221_..._v2.py` → rỗng |
| Điều kiện khả thi là trường hợp \|R\|=1 | **Đã chạy** T2.3, xác nhận |
| `mcq_generation.get_diff_fact()` vi phạm OWA | Dòng 93–97: nhánh `else` (distractor **không có** key `kA`) vẫn trả về fact. Đây là *unverified negative* |
| Kiểm tra chéo trong `get_diff_fact` so sánh **hai fact khác nhau** | Dòng 176–182: `uf2 = get_diff_fact(answer, dd)` trả về fact **đầu tiên** theo thứ tự dict, rồi so với `o_i` — phụ thuộc thứ tự, sinh false negative |
| Wording "apply/integrate" thay vì "extend" | Đúng. Không có dòng nào sửa Definition 11 |
| Manual / recommended / fallback trung thực hơn với Umematsu | Xác nhận bằng nguyên văn luận văn (§4) |

### 2.2 ĐÚNG MỘT PHẦN (cần thêm điều kiện)

| Điểm | Thiếu gì |
|---|---|
| "Sửa lỗi trộn thang đo TF-IDF với SBERT" (header dòng 11) | `_idf()` (dòng 349–352) đã chuẩn hoá về [0,1] ✔. Nhưng **cùng khoảng giá trị ≠ cùng thang đo**: IDF trải gần đều [0,1], còn cosine SBERT của `all-MiniLM-L6-v2` tập trung dày ở [0.1, 0.5]. Cộng `0.7·sbert + 0.3·idf` (dòng 438) ⟹ IDF **áp đảo** dù α=0.7. Cần z-score hoặc rank-normalisation **trong từng answer**, và phải báo cáo ablation α |
| "Giảm SPARQL từ (2+N) xuống 2" (header dòng 8) | **Chỉ đúng khi `local_index=None`.** Khi truyền `local_index`, dòng 411 gọi `get_nodes_in_class()` **cho từng class còn sống** → lại thành (2+N). Và `build_choices()` dòng 495 gọi lại lần nữa. Header đang phóng đại |
| "3 lỗi có thể ảnh hưởng số liệu Journal 1" (header dòng 11–12) | File chỉ đánh dấu **LỖI 2** (dòng 450) và **LỖI 3** (dòng 498). **Không có LỖI 1 nào trong file.** Tuyên bố "3 lỗi" không kiểm chứng được từ artefact đã giao |
| "Benchmark 15–25× speedup" | Trên **đồ thị tổng hợp**, không phải DBpedia thật. Phải ghi rõ khi viết paper |
| "Chọn distractor có RÀNG BUỘC KHẢ THI + ĐA DẠNG" (header dòng 17–19) | Khả thi: **sai định nghĩa** (dòng 453, xem §1.3). Đa dạng: MMR đo trên **tập cạnh** (dòng 429–431), không đo trên **tập rationale** → **không** đảm bảo mỗi distractor bị loại vì lý do khác nhau. Chú thích dòng 409–411 tuyên bố điều mà code không làm |
| Chi phí LRoleSim "≈2,3 phút/câu, 2,2 GB" | Ước lượng thời gian hợp lý; **ước lượng RAM thấp**. Đo thật (T3.2): riêng `max_delta()` đã thêm ~1,9 GB ở n=4000, cộng 2 bản `Sim` đồng thời (dòng 275–277) → **3–4 GB** |

### 2.3 SAI hoặc PHÓNG ĐẠI

| Điểm | Thực tế |
|---|---|
| Chú thích dòng 374–375: *"Chuẩn hoá theo bậc: nếu không, entity nổi tiếng luôn thắng"* | **SAI.** `score_norm` (dòng 377) **không bao giờ được dùng**. Sort dùng `-c.score` (dòng 381), MMR dùng `c.score/max_score` (dòng 426). Lỗi mà chú thích nói là đã sửa **vẫn còn nguyên** |
| Tóm tắt phiên trước: *"All rewrites were verified numerically identical to the originals (max diff ~5.6e-17)"* | **PHÓNG ĐẠI.** Chỉ có thể đúng cho **kernel một vòng lặp**. `lrolesim()` (hội tụ vs 3 vòng) và `make_sorted_list_fn()` (đổi tie-break) **cố ý** cho kết quả khác. Không được dùng câu này trong paper |
| Chú thích dòng 12: *"Trả về DANH SÁCH XẾP HẠNG để pipeline có thể fallback"* + tên hàm `choose_best_class_for_answer()` | Mâu thuẫn nội bộ: đã thừa nhận cần fallback thì **không còn "best"**. Nên đổi tên thành `rank_classes_for_answer()` / `first_feasible_class()` |
| Chú thích dòng 122–123: *"Kết quả được cache vì cùng một node bị hỏi lại rất nhiều lần"* | Cache **có** hiệu quả, nhưng **khoá sai** (T2.1). Lợi ích tốc độ đi kèm rủi ro kết quả sai |
| Chú thích dòng 259–264 (`lrolesim`): *"`for _ in range(3)` là một hằng số không có căn cứ"* | **Phóng đại.** k=3 là **thiết kế thí nghiệm đã công bố của Journal 1**. Đổi mặc định sang hội tụ mà không nêu rõ là **phá vỡ tính so sánh được**, chứ không phải sửa lỗi. `max_iter` phải là tham số CLI có giá trị mặc định = 3 để tương thích Journal 1 |

---

## 3. Đánh giá công thức lựa chọn distractor và rationale

### 3.1 Ký hiệu chuẩn (dùng lại ký hiệu Journal 1 để nối hai bài)

Cho đồ thị tri thức quan sát được `K = (V, P, E)` với `E ⊆ V × P × V`.

**Fact (extended edge) của một node** — chính là `N′(v)` của Definition 10, Journal 1:

```
F(v) = { (p, →, o) : (v, p, o) ∈ E }  ∪  { (p, ←, s) : (s, p, v) ∈ E }
```

| Ký hiệu | Định nghĩa | Vị trí trong code |
|---|---|---|
| `A ∈ V` | Answer node | `build_choices()` dòng 488 |
| `κ(A)` | class được chọn (dbc:…) | `rank_classes_for_answer()` dòng 453 |
| **Candidate set** `C` | `{x : (x, dcterms:subject, κ(A)) ∈ E} \ {A}`, đã lọc non-entity và ánh xạ được vào KG cục bộ | `get_candidates_for_class()` dòng 463–477 |
| **Distractor set** `D` | `D ⊆ C`, `\|D\| = k` (k = 3) | `select_distractor_set()` dòng 399 |
| **Answer facts** `F(A)` | như trên | `extended_edgeset()` dòng 118 |
| **Exclusion set** của fact f | `E_D(f) = { d ∈ D : f ∉ F(d) }` | **CHƯA CÓ trong code** |
| **Rationale set** `R` | `R ⊆ F(A)` sao cho `⋃_{f∈R} E_D(f) = D` | **CHƯA CÓ** (chỉ có trường hợp \|R\|=1, dòng 450–455) |
| **Plausibility** | `Plaus(A,d) = S^{(κ)}_LRoleSim(A,d)` trên đồ thị con `G_A` | **CHƯA NỐI VÀO** |
| Redundancy | `Red(d,d′) = \|F(d) ∩ F(d′)\| / max(\|F(d)\|, \|F(d′)\|)` | dòng 429–431 |

### 3.2 Ba khái niệm rationale — PHẢI phân biệt rõ trong paper

1. **Single-fact discrimination (\|R\| = 1)** — tồn tại `f ∈ F(A)` với `E_D(f) = D`.
   *Đây là điều code hiện tại đang làm* (dòng 450–455) và cũng là *"unique predicate"* trên slide Step 4. Chặt nhất.
2. **Minimum-cardinality rationale** — `R* ∈ argmin { |R| : ⋃_{f∈R} E_D(f) = D }`.
3. **Subset-minimal (irredundant) rationale** — `R` phân biệt được `D`, và `∀f ∈ R`, `R \ {f}` **không** còn phân biệt được.

**Quan hệ:** (1) ⟹ (2) ⟹ (3), nhưng **không có chiều ngược lại**. Một `R` subset-minimal có thể có 3 phần tử trong khi `R*` chỉ có 2 (nếu tồn tại một fact "mạnh" khác). Đây là điểm reviewer sẽ hỏi — hãy nêu rõ bạn tối ưu cái nào (khuyến nghị: **minimum-cardinality**, vì k nhỏ nên giải chính xác được).

### 3.3 Bổ đề khả thi (nên đưa vào paper — chứng minh 3 dòng)

> **Bổ đề.** Với `D` cho trước, tồn tại rationale phân biệt `R ⊆ F(A)` **khi và chỉ khi** `F(A) \ F(d) ≠ ∅` với **mọi** `d ∈ D`. Hơn nữa, khi đó `|R*| ≤ |D| = k`.
>
> *Chứng minh.* (⟸) Với mỗi `d` chọn `f_d ∈ F(A) \ F(d)`; khi đó `R = {f_d : d ∈ D}` phủ `D`, và `|R| ≤ k`. (⟹) Nếu `∃d : F(A) ⊆ F(d)` thì `∀f ∈ F(A), f ∈ F(d)`, nên `d ∉ E_D(f)` với mọi `f`, không `R` nào phủ được `d`. ∎

**Hệ quả quan trọng cho bài báo của bạn:** bài toán set cover tổng quát là NP-hard, **nhưng** trong setting MCQ `k ≤ 5`, nên `|R*| ≤ 5` và lời giải **chính xác** thu được bằng bitmask trong `O(m · 2^k)` — với `k=3` là `O(8m)`. Tôi đã **chạy thật** cài đặt này (T2.4). Đây là một đóng góp *nhỏ nhưng sạch* và rất dễ bảo vệ.

### 3.4 Tính đúng đắn dưới Open-World Assumption

Công thức mà tôi đề xuất trước đây dùng ký hiệu `R ⊨ A ∧ ∀d ∈ D, R ⊭ d` — **ký hiệu này SAI dưới OWA**. `⊨` là *entailment*; từ việc `K` không chứa `(d, p, o)` **không suy ra được** `¬(d, p, o)`. Phải thay bằng quan hệ **quan sát trên K**:

```
f  K-contrasts  (A, d)   ⟺   f ∈ F_K(A)  ∧  f ∉ F_K(d)
```

và gọi đúng tên: **observed-KG contrast**, không phải "d không có f".

**Ba mức bằng chứng — nên phân loại và báo cáo tỉ lệ:**

| Mức | Điều kiện | Có được in ra cho học sinh không? |
|---|---|---|
| **L2 — positive contrast** | `∃o′ ≠ o : (d, p, o′) ∈ K` **và** `p` functional trên `d` (`\|{o : (d,p,o) ∈ K}\| = 1`) | **CÓ.** Hợp lệ tuyệt đối dưới OWA: "A có p = o, còn d có p = o′" |
| **L1 — verified absent** | `(d,p,o) ∉ K` **và** kiểm chứng chéo Wikidata (hoặc DBpedia ngôn ngữ khác) cũng không có | **CÓ**, kèm ghi chú nguồn |
| **L0 — unverified absent** | chỉ `(d,p,o) ∉ K` | **KHÔNG.** Chỉ dùng để báo cáo yield rate |

**Đây chính xác là điều Umematsu đã làm và bạn đang đánh mất.** Luận văn mục 4.4: *"正答が Wikidata 上に有する述語中から**目的語が一意に決まる述語集合**を抽出する. つまり "is-a" や "like" などの目的語が複数考えられるものをここで除いている"* — tức lọc **functional predicate** trước. `distinguishing_facts()` (dòng 389–396) hiện **không có** bước lọc này.

**Khuyến nghị cụ thể:** mỗi phần tử rationale xuất ra kèm trường `evidence_level ∈ {L2, L1, L0}`. 100 câu nộp giáo sư chỉ dùng L2 (và L1 nếu đã cross-verify).

### 3.5 Công thức cuối cùng đề xuất cho paper

```
                  ⎧              ⎫
   max            ⎨ Φ(D)         ⎬
 D ⊆ C, |D| = k   ⎩              ⎭

   Φ(D)  =  λ · Σ_{d∈D} S_LRoleSim^{(κ)}(A, d)
            − (1−λ) · Σ_{d,d′∈D, d≠d′} Red(d, d′)

   s.t.  (C1)  ∀d ∈ D :  F(A) \ F(d) ≠ ∅                     [khả thi]
         (C2)  |R*(D)| ≤ ρ                                    [trình bày được]
         (C3)  ∀f ∈ R*(D) :  evidence_level(f) ≥ L1           [hợp lệ dưới OWA]

   trong đó   R*(D) = argmin  |R|   s.t.  ⋃_{f∈R} E_D(f) = D
                       R ⊆ F(A)
```

**Phê bình công thức ChatGPT đề xuất.** Cách viết `R*(D) = argmin … such that …` **định nghĩa** `R*(D)` rất chuẩn — điểm này ChatGPT làm đúng và tốt hơn bản của tôi. **Nhưng** đặt nó sau chữ *"subject to"* là **lỗi kiểu**: `R*(D)` là *đại lượng dẫn xuất*, không phải *ràng buộc* — nó không thu hẹp miền khả thi của `D` chút nào. Bài toán khi đó suy biến thành "max plausibility" không ràng buộc. Phải bổ sung **(C1)** và **(C2)** như trên. Ngoài ra, `R*(D)` chỉ tồn tại khi (C1) đúng, nên (C1) là *điều kiện tiên quyết* cho phát biểu của ChatGPT có nghĩa.

**Về `ρ` trong (C2):** theo Bổ đề 3.3, đặt `ρ = k` làm (C2) trở nên vô nghĩa (luôn thoả). Vậy `ρ` là **tham số trình bày**, không phải tham số đúng/sai:
- `ρ = 1` → đúng code hiện tại, đúng slide Step 4 → yield thấp.
- `ρ = 2` → khuyến nghị. Rationale dạng "A và B đều …; nhưng chỉ A mới …".
- `ρ = 3` → tối đa yield, rationale dài.

**Việc quét `ρ = 1, 2, 3` và báo cáo yield rate chính là thí nghiệm chính của bài báo 2 của bạn.**

### 3.6 Novelty — đánh giá trung thực

| Câu hỏi | Trả lời |
|---|---|
| Có phải **thuật toán mới** không? | **KHÔNG.** Set cover, MMR, Hungarian, RoleSim đều đã biết |
| Có phải **formulation mới** không? | **CÓ, ở mức vừa phải.** Bài toán "chọn k distractor cực đại plausibility **dưới ràng buộc tồn tại rationale phân biệt tối thiểu**" chưa xuất hiện trong Umematsu (k=1 fact, class do người chọn), chưa có trong Okuhara (dist-based, không có rationale phân biệt), và chưa có trong dòng distractor-generation dựa embedding |
| Hay chỉ là **kết hợp kỹ thuật đã biết**? | Phần cài đặt: đúng, là kết hợp. Phần phát biểu bài toán: không |

**Novelty được phép tuyên bố (theo thứ tự sức mạnh):**

- **N1.** *Problem formulation*: joint optimisation plausibility + minimal discriminating rationale cho MCQ trên KG.
- **N2.** *Structural result* (Bổ đề 3.3): khả thi phân rã theo từng distractor, `|R*| ≤ k`; set cover tổng quát NP-hard nhưng setting MCQ giải **chính xác** trong `O(m·2^k)`.
- **N3.** *Nới lỏng có định lượng* điều kiện "unique predicate" từ `ρ=1` sang `ρ ≤ 3`, kèm đường cong yield rate. Đây là đóng góp thực nghiệm **rẻ nhất và thuyết phục nhất** bạn có.
- **N4.** *Tích hợp một admissible role-similarity (LRoleSim)* làm plausibility ranker, kèm bảng ablation 5 độ đo (rolesim / _d / _e / _ed / _edt) — chưa ai làm cho distractor generation.
- **N5.** *Phân loại bằng chứng dưới OWA* (L2/L1/L0) + báo cáo tỉ lệ.

**KHÔNG được tuyên bố:** "we propose a new similarity measure", "we extend LRoleSim", "we solve NP-hard set cover", "we find the optimal class", "our method guarantees the rationale is correct".

---

## 4. Kết luận rút ra từ luận văn Umematsu

Trích dẫn nguyên văn và hệ quả:

| Câu hỏi của bạn | Bằng chứng trong luận văn | Kết luận |
|---|---|---|
| Người tạo câu hỏi có được chỉ định class không? | 第4章 mở đầu: *"正答となる入力単語から誤答候補となりうるクラスを抽出し, 誤答候補の個数と回答根拠となる述語の個数を**問題作成者に選んで貰う**"*; §5.2: *"提案手法では正答語句から**出題者にクラスを指定し**"* | **CÓ. Class do người ra đề chỉ định.** Đây là thiết kế gốc, không phải hạn chế |
| Class dùng để thu hẹp tập ứng viên hay là bài toán tối ưu trung tâm? | §4.3: *"2-hop の場合でも平均して 278540 個存在しており, この中から最大マッチングのものを問題を作成するたび探索するのは適切とは言えない. **この問題を LOD に標準的に備わっているクラスデータを参照することで解決した**"* | **Thuần tuý để THU HẸP không gian tìm kiếm.** Không phải bài toán tối ưu |
| Luận văn có chứng minh "best class" duy nhất không? | **KHÔNG.** Ngược lại, §5.2 dùng *"クラス候補の中から**ランダムに**選択したクラス"* cho bản so sánh | **Không có khái niệm "best class"** trong tiền lệ |
| Ba chế độ manual / automatic ranked / hybrid top-N có hợp lý không? | Có. Manual = đúng Umematsu; automatic = mở rộng của bạn; hybrid = thực dụng | **HỢP LÝ, và trung thực hơn code hiện tại** |
| Nên tìm "first feasible / top-ranked usable class" hay "optimal class"? | Kết luận luận văn còn nêu hạn chế: *"本手法ではそのような金属原子を有していることを指し示すクラスが存在しないため, このような問題は作成できない"* — tức class là **ràng buộc dữ liệu**, không phải biến tối ưu | **First feasible.** Đổi tên `choose_best_class_for_answer()` → `first_feasible_class()`. Trong paper viết *"we select the highest-ranked **usable** class"*, không viết *"optimal"* |

**Điểm cực kỳ quan trọng, thường bị bỏ sót:** Umematsu §4.4 mô tả thuật toán sinh rationale gồm đúng 2 bước:

1. *"正答が Wikidata 上に有する述語中から**目的語が一意に決まる述語集合**を抽出する"* → **lọc functional predicate**.
2. *"述語候補と選択肢候補の中で正答の目的語と同じものを除いていく"* → **loại ứng viên có cùng object**.

Nghĩa là Umematsu làm việc ở mức **(predicate, object) với predicate functional** — tức mức **L2 (positive contrast)** trong bảng §3.4. Code v2 của bạn ở mức **L0**. Đây là một **bước lùi** so với tiền lệ mà reviewer chắc chắn sẽ phát hiện.

**Về hai URI bạn đã kiểm tra** (`Makoto_Kobayashi_(physicist)` → `dbc:J._J._Sakurai_Prize…`, `Akira_Suzuki_(chemist)` → `dbc:Japanese_chemists`): xác nhận **không được** mặc định rằng mọi URI có hậu tố ngoặc cần redirect. Bằng chứng phản bác đủ mạnh, xem §Phụ lục A.

---

## 5. Audit từng file

Ký hiệu mức độ: **C** = critical (chặn thí nghiệm) · **H** = high · **M** = medium · **L** = low.
Cột "Trước TN?" = có bắt buộc sửa trước khi chạy 100 MCQ không.

### 5.1 `category_extractor_ClaudeWeb_v2.py` (518 dòng)

| # | Mức | Hàm / dòng | Vấn đề | Tác động | Sửa nhỏ nhất | Trước TN? |
|---|---|---|---|---|---|---|
| CE-1 | **C** | tên file | Tên file là `category_extractor_ClaudeWeb_v2.py` nhưng module khác import `category_extractor` | ImportError | Đổi tên file thành `category_extractor.py` (lưu bản cũ vào `legacy/`) | **CÓ** |
| CE-2 | **H** | `choose_best_class_for_answer()` **445–450** | Chữ "best" không có cơ sở (§4) | Reviewer bác bỏ tuyên bố | Đổi tên `first_feasible_class()`; giữ alias deprecated | Không (nhưng trước khi viết paper) |
| CE-3 | **H** | `rank_categories()` **405–417** | Khi `local_index != None`, gọi `get_nodes_in_class()` **cho mỗi class** → phá vỡ tuyên bố "2 truy vấn" (header dòng 8) và tốn ~N round-trip | Chậm ~15 s/answer; header sai | Gộp thành **một** truy vấn `VALUES ?cat { … } ?x dct:subject ?cat` rồi group theo cat | **CÓ** (nếu dùng `local_index`) |
| CE-4 | **H** | `_get_sbert()` **336–346**, `_init_wordnet()` **251–263** | Lazy-init **không thread-safe**, nhưng `batch_rank_classes()` (dòng 475–493) chạy 6 thread | Nạp model 6 lần; NLTK corpus load đồng thời có thể hỏng | Bọc `threading.Lock()`, hoặc gọi cưỡng bức **một lần** trước khi mở pool | **CÓ** nếu dùng `batch_rank_classes` |
| CE-5 | **H** | `batch_rank_classes()` **483** truyền `nlp` vào thread | `spacy.Language.__call__` **không** được đảm bảo thread-safe | Kết quả leak-check không xác định | Dùng `ProcessPoolExecutor`, hoặc `nlp.pipe()` tuần tự ngoài pool, hoặc `nlp` riêng mỗi thread | **CÓ** nếu dùng |
| CE-6 | **M** | `get_nodes_in_class()` **229–240** | `LIMIT 2000` **không có `ORDER BY`** | Tập ứng viên **không tất định** khi cache miss; class 3000 member bị cắt âm thầm | Thêm `ORDER BY ?x` và cảnh báo khi `len == limit` | **CÓ** (tái lập) |
| CE-7 | **M** | `rank_categories()` **427** `model.encode(abstract)` | `all-MiniLM-L6-v2` có `max_seq_length = 256` word-piece → abstract DBpedia bị **cắt âm thầm** | Điểm SBERT chỉ phản ánh 1–2 câu đầu | Chunk abstract thành đoạn ≤ 200 token, encode theo lô, lấy mean-pooling; ghi số chunk vào audit | Nên, trước khi viết paper |
| CE-8 | **M** | `SparqlCache` **62–98** | Không có `schema_version`, `lang`, `ttl`, không đọc cột `ts` (dòng 96) | Không thể invalidate; không phân biệt snapshot cũ/mới | Thêm bảng `meta(key, value)` với `schema_version`, `created_at`, `endpoint`, `dbpedia_release`; thêm `--refresh-older-than` | Nên |
| CE-9 | **M** | `_idf()` **349–352** + `rank_categories()` **438** | `TOTAL_ENTITIES = 6_000_000` là **hằng số hard-code**; và IDF vs cosine khác phân phối (§2.2) | α mất ý nghĩa; số không tái lập khi DBpedia đổi | Truy vấn `COUNT(DISTINCT ?x){?x dct:subject ?c}` một lần, lưu vào cache meta; chuẩn hoá `sbert` và `idf` bằng **rank trong cùng answer** trước khi cộng | Nên |
| CE-10 | **M** | `remove_parenthetical()` **279–282** | Xoá **mọi** cặp ngoặc. Đã chạy (T2.5): `Phosphorus(V)_oxide → "Phosphorus oxide"`, `Iron(III)_chloride → "Iron chloride"` | Với leak-check: hậu quả nhẹ (tầng lemma dòng 315–325 vẫn bắt được gốc từ). Với display: **sai thực thể** | **Không sửa hàm này** (nó chỉ phục vụ leak-check, dòng 295–308). Thêm hàm **riêng** `format_display_label()` — §Phụ lục B | **CÓ** nếu bạn định dùng cho display |
| CE-11 | **M** | `leaks_answer()` **315–325** | Tầng lemma/synonym mở rộng **toàn bộ WordNet synset** cho mọi token ≥ 3 ký tự | Quá nhạy: "Japanese chemists" vs "Akira Suzuki" — nếu label có từ chung nào là loại. Có thể loại hết class hợp lệ | Chỉ mở rộng synonym cho **content word** (loại stopword + tính từ dân tộc); ghi lại số class bị loại vì lý do này để báo cáo | Nên |
| CE-12 | **L** | `fetch_answer_info()` **164–176** | Ba `OPTIONAL` trong một `SELECT` → **tích Descartes** label × abstract × cat | Payload phình (30 cat × 1 abstract dài) | Tách thành 2 truy vấn, hoặc dùng `GROUP_CONCAT` cho `?cat` | Không |
| CE-13 | **L** | `rank_categories()` **366** | `alpha=0.7` không truyền được qua `rank_classes_for_answer()` (dòng 453–462) | Không chạy được ablation α | Thêm tham số `alpha` xuyên suốt | Nên |
| CE-14 | **L** | `rank_categories()` **440** | `kept.sort(key=..., reverse=True)` không có tie-break tường minh | Thực tế **vẫn tất định** vì `answer.categories` đã `sorted()` (dòng 194) và sort của Python ổn định | Ghi chú lại; nếu muốn chắc: `key=(-score, category)` | Không |

**Trả lời trực tiếp các câu hỏi mục VI của bạn:**

| Câu hỏi | Trả lời |
|---|---|
| Có thực sự cần redirect/canonical URI trong mọi trường hợp không? | **KHÔNG.** Không có dòng redirect nào trong code v2, và hai URI bạn test chạy tốt. → DEFER (Phụ lục A) |
| Có nên đổi class selection thành manual/automatic/hybrid không? | **CÓ.** Phù hợp Umematsu (§4) |
| `choose_best_class_for_answer()` có phóng đại chữ "best" không? | **CÓ.** CE-2 |
| TF-IDF có thực chất chỉ là IDF vì TF ≡ 1 không? | **ĐÚNG HOÀN TOÀN.** `TF(c,e) ∈ {0,1}` (slide Step 1) và ta chỉ xét c mà e thuộc về ⟹ TF ≡ 1. Trong code, `cd.score = cd.idf` khi `method="tfidf"` (dòng 434) — **đã đúng về mặt cài đặt**, chỉ cần **đổi tên trong paper thành IDF**, đừng gọi TF–IDF |
| Combined score có cùng thang đo không? | Cùng **khoảng** [0,1] nhưng **không cùng phân phối** → CE-9 |
| SBERT có bị truncation không? | **CÓ**, 256 word-piece. CE-7 |
| Có nên encode abstract theo chunk không? | **CÓ.** CE-7 |
| Cache có phân biệt query failure / zero-result / empty category / all-rejected? | Phân biệt được **failure vs zero-result** (dòng 128 chỉ ghi khi thành công; dòng 137–138 trả None không ghi) ✔. **Không** phân biệt "empty category" với "all categories rejected" — cả hai đều là `[]` từ `rank_classes_for_answer()` (dòng 458–461 vs 463). **Phải sửa** để đo yield rate |
| Cache có metadata/version/refresh không? | **KHÔNG.** CE-8 |
| Có cache kết quả thất bại như kết quả hợp lệ không? | **KHÔNG** (đúng) — dòng 137–138 |
| ThreadPool có an toàn với SQLite, spaCy, SBERT không? | SQLite: **AN TOÀN** (`check_same_thread=False` + `threading.Lock`, dòng 73–74, 87, 92). spaCy: **KHÔNG** (CE-5). SBERT/WordNet lazy-init: **KHÔNG** (CE-4) |
| Ranking có deterministic không? | **CÓ** với cùng input (CE-14), **nhưng** input không tất định vì CE-6 và vì SBERT trên GPU có thể khác CPU |
| Nên xếp hạng class theo "utility for MCQ" hay chỉ kiểm feasibility? | **Feasibility trước, utility sau.** Utility chỉ có nghĩa nếu bạn định nghĩa và đo được nó — mà bạn chưa. Dùng thứ tự: (a) khả thi (đủ ứng viên trong KG cục bộ + tồn tại rationale), (b) trong số khả thi mới xếp theo IDF/SBERT |
| `remove_parenthetical()` có làm hỏng hóa học không? | **CÓ**, đã chứng minh bằng test T2.5. CE-10 |

### 5.2 `extract_221_and_select_distractors_ClaudeWeb_v2.py` (602 dòng)

| # | Mức | Hàm / dòng | Vấn đề | Tác động | Sửa nhỏ nhất | Trước TN? |
|---|---|---|---|---|---|---|
| EX-1 | **C** | import **37–43** | Import từ `category_extractor` — tên module không khớp file thật | ImportError, pipeline không chạy | Đổi tên file v2 (CE-1) | **CÓ** |
| EX-2 | **C** | toàn file | **Không có bất kỳ import nào tới `MCQ_lrolesim`.** `rank_candidates()` (345–382) chỉ dùng Overlap | LRoleSim vắng mặt khỏi pipeline; mâu thuẫn slide + README | Thêm ranker `LRoleSimRanker` (§9) | **CÓ** |
| EX-3 | **C** | `select_distractor_set()` **450–455**, `build_choices()` **507–510** | Chỉ chấp nhận **\|R\| = 1** (đã chạy T2.3) | Loại bỏ câu hỏi hợp lệ; yield rate thấp giả tạo | Thay bằng set cover bitmask (§9, mã mẫu §3.3) | **CÓ** |
| EX-4 | **H** | `_edgeset_cache` **115**, `extended_edgeset()` **118–132** | Khoá cache **chỉ bằng `node_idx`**, bỏ qua `kg` và `use_in` (đã chạy T2.1) | Kết quả **sai âm thầm** khi chạy ablation `use_in=True/False` trong cùng process | `key = (id(kg), node_idx, use_in)`, hoặc đưa cache vào `KG` | **CÓ** nếu chạy ablation |
| EX-5 | **H** | `rank_candidates()` **377**, **381**; `select_distractor_set()` **426** | `score_norm` **không được dùng** (T2.2) | Entity bậc lớn (Aristotle) vẫn thắng — đúng lỗi mà chú thích 374–375 nói đã sửa | Đổi dòng 381 → `-c.score_norm`; dòng 426 → `c.score_norm / max_norm` | **CÓ** |
| EX-6 | **H** | `distinguishing_facts()` **389–396** | Coi *thiếu triple* = *contrast* → vi phạm OWA (§3.4) | Rationale có thể sai; lùi so với Umematsu §4.4 | Thêm `evidence_level()`: chỉ nhận L2 (p functional trên d, d có giá trị khác) hoặc L1 | **CÓ** |
| EX-7 | **H** | `select_distractor_set()` **429–431** | MMR đo đa dạng trên **tập cạnh**, không trên **tập rationale** | Không đảm bảo "mỗi distractor bị loại vì một lý do khác" như chú thích 409–411 tuyên bố | Đổi `red` sang Jaccard trên `E_D(f)`-signature: `sig(d) = F(A) \ F(d)` | Nên |
| EX-8 | **M** | `AbstractStore.fetch_abstracts()` **215** | `[:1000]` ký tự **rồi mới ghi cache** | Mất dữ liệu vĩnh viễn; không thể encode theo chunk về sau | Ghi **full text** vào cache; cắt (nếu cần) lúc encode | Nên |
| EX-9 | **M** | `AbstractStore._vec` **164, 235–251** | Vector SBERT **chỉ trong RAM** | Mỗi lần chạy lại phải encode lại ~10⁴ object (~vài phút GPU) | Lưu `float16` vào SQLite hoặc `.npy` + index; khoá = `(uri, model_name)` | Nên |
| EX-10 | **M** | `AbstractStore.sim()` **257–259** | Trả `0.0` khi thiếu vector | Nhầm "không có dữ liệu" với "không giống" | Trả `None` và loại cặp đó khỏi ma trận matching; đếm số cặp bị loại | Nên |
| EX-11 | **M** | `_max_matching()` **292–302** | Fallback thứ ba là **greedy** (không tối ưu), khác `_max_weight_matching()` của LRoleSim (fallback là Munkres, tối ưu) | Kết quả khác nhau tuỳ máy có scipy hay không | Bỏ nhánh greedy, `raise` nếu thiếu cả scipy lẫn munkres; ghi solver đã dùng vào output | **CÓ** (tái lập) |
| EX-12 | **M** | `build_choices()` **518–521** | Trường tên `"object"` cho **cả** cạnh IN — nhưng với `direction = IN`, phần tử thứ ba là **subject** | Verbalization ở Step 5 sẽ tạo câu sai chiều | Đổi thành `{"predicate", "direction", "other"}` hoặc tách `"subject"/"object"` theo `direction` | **CÓ** |
| EX-13 | **M** | `rank_candidates()` **381** | Sort không có tie-break; thứ tự `cand_idx` đến từ SPARQL không `ORDER BY` (CE-6) | Không tất định | `key=lambda c: (c.rejected is not None, -c.score_norm, c.uri)` | **CÓ** |
| EX-14 | **M** | định nghĩa "unique" | Slide Step 4 định nghĩa unique ở mức **(predicate, direction)** với **tập object rời nhau**; code làm ở mức **(p, d, o)** với hiệu tập hợp | Hai định nghĩa **khác nhau** → paper và code lệch nhau | Thống nhất: dùng mức (p,d) + rời nhau (mạnh hơn, và là mức L2 dưới OWA) | **CÓ** |
| EX-15 | **L** | `main()` **533–535** | `DATA_DIR`, `OUTPUT_DIR` gán nhưng không dùng (pyflakes xác nhận) | Đường dẫn `--out` vẫn tương đối | Dùng `OUTPUT_DIR / args.out` | Nên |
| EX-16 | **L** | `KG` **75** | Chú kiểu `index_url: list` nhưng `read_ttl.load_obj()` trả **dict** (`read_ttl.py` dòng 70) | Chỉ sai chú kiểu | `index_url: dict` | Không |
| EX-17 | **L** | `select_top100()` **592–598** | `raise NotImplementedError` nhưng vẫn nhận đủ tham số cũ | Gây nhầm | Xoá hẳn hoặc chuyển sang `legacy/` | Không |

**Trả lời trực tiếp mục VIII của bạn:**

| # | Câu hỏi | Trả lời |
|---|---|---|
| 1 | File có thật sự gọi `rank_by_similarity()` không? | **KHÔNG** (EX-2) |
| 2 | Hay vẫn chỉ dùng OverlapStrict/OverlapLoose? | **ĐÚNG, chỉ dùng Overlap** (dòng 371–373) |
| 3 | Import có trỏ đúng file v2 không? | **KHÔNG** (EX-1) |
| 4 | `_edgeset_cache` khoá chỉ bằng node index → sai khi đổi KG/`use_in`? | **ĐÚNG, đã chứng minh** (EX-4, T2.1) |
| 5 | `score_norm` có được dùng để sort/MMR không? | **KHÔNG** (EX-5, T2.2) |
| 6 | Abstract có bị cắt `[:1000]` không? | **CÓ**, dòng 215 (EX-8) |
| 7 | SBERT vector persistent hay chỉ RAM? | **Chỉ RAM**, dòng 164 (EX-9) |
| 8 | SPARQL có `ORDER BY` tất định không? | **KHÔNG** (CE-6) |
| 9 | Matching fallback có exact không? | **KHÔNG** — nhánh 3 là greedy (EX-11) |
| 10 | IN-edge output có đặt tên field sai không? | **CÓ**, dòng 519–520 (EX-12) |
| 11 | MMR có đảm bảo rationale diversity không? | **KHÔNG** (EX-7) |
| 12 | Phần `common = a_edges` rồi trừ dần — có chỉ chấp nhận một fact phân biệt toàn bộ không? | **CÓ** (EX-3, đã chạy T2.3) |
| 13 | Có bỏ qua trường hợp ≥2 fact cùng bao phủ không? | **CÓ, bỏ qua hoàn toàn** |
| 14 | Có cần bitmask DP với k=3 không? | **CÓ**, và rất rẻ: `O(m·2^k) = O(8m)`. Đã cài + chạy (T2.4) |
| 15 | Có coi missing triple là false dưới OWA không? | **CÓ** (EX-6) |
| 16 | Candidate rankers có chung interface để chạy ablation không? | **KHÔNG.** Chỉ có một hàm cứng `rank_candidates()`. Cần `Protocol` chung (§9) |

### 5.3 `MCQ_lrolesim_ClaudeWeb_v2.py` (828 dòng)

#### 5.3.1 Có giữ đúng định nghĩa LRoleSim của Journal 1 không?

**CÓ — với bằng chứng số học đã chạy thật.**

| Thành phần | Definition Journal 1 | Cài đặt v2 | Kết luận |
|---|---|---|---|
| `N′(v) = I′(v) ∪ O′(v)` (Def. 10) | tập cạnh mở rộng | `precompute_groups()` **167–170** gộp cả `in_neighbor` và `out_neighbor` | ✔ |
| `max{\|N′(u)\|, \|N′(v)\|}` | số **cạnh** kề, không phải số láng giềng phân biệt | `node_degree()` **175–177** = `sum(len(v) …)` | ✔ (T1 xác nhận \|N′(Kamagatani)\| = 4) |
| `S⁰ = 1 ∀u,v` | | `Sim.__getitem__` **129** trả `1.0` mặc định | ✔ |
| `S^k = (1−β)·w^{k−1}(M)/max{…} + β` | | `lrolesim_iteration()` **250** | ✔ |
| Phân hoạch theo lớp tương đương, Hungarian **từng lớp**, cộng dồn (Algorithm 1) | | **247–249** | ✔ |
| `L_ed`, `L_edt`, … | Def. 13 | `_key_function()` **93–104** ↔ class **37–70** | ✔ |

**Kiểm chứng số học (T1, đã chạy):** trên lõi HanamiSpots 8 node tái dựng từ Example 2/7/8 + file entity type, iteration 1 cho ra **chính xác** giá trị Bảng 1 của `Explainability_of_LRoleSim.pdf`:

```
rolesim      k1 = 1.000   (paper 1.000)  KHỚP
lrolesim_d   k1 = 1.000   (paper 1.000)  KHỚP
lrolesim_e   k1 = 1.000   (paper 1.000)  KHỚP
lrolesim_ed  k1 = 1.000   (paper 1.000)  KHỚP
lrolesim_edt k1 = 0.600   (paper 0.600)  KHỚP   ← giá trị đặc trưng nhất
```

Giá trị `edt = 0.600` chỉ ra được khi **toàn bộ** chuỗi (đọc entity type theo URL → khoá `(p, d, type)` → matching theo lớp → chuẩn hoá theo `max{|N′|}` → `β = 0.2`) đều đúng. Đây là bằng chứng mạnh.

#### 5.3.2 Những thay đổi CÓ THỂ làm đổi số liệu Journal 1

| # | Mức | Hàm / dòng | Thay đổi | Ảnh hưởng |
|---|---|---|---|---|
| LR-1 | **H** | `lrolesim()` **256** | `max_iter=20, tol=1e-4` thay cho `range(3)` (`MCQ_lrolesim.py` dòng 961) | Theorem 3: `S^k` đơn điệu giảm ⟹ giá trị hội tụ **< giá trị k=3**. Xếp hạng **có thể đổi**. **Không tái lập được Journal 1** |
| LR-2 | **H** | `make_sorted_list_fn()` **464** | Phá hoà bằng `index_url` thay vì chỉ số node | Sửa **đúng**, nhưng MRR/NDCG **sẽ khác** Journal 1 |
| LR-3 | **H** | `compute_ndcg()` **528–531** | `skip_undefined=True` mặc định | NDCG **sẽ khác** Journal 1. Muốn tái lập phải `skip_undefined=False` |
| LR-4 | **M** | `precompute_groups()` **167–170** | Dùng `list.append` → **không khử triple trùng lặp** (đã chạy: thêm 1 triple lặp làm \|N′\| từ 4 → 5). `read_ttl.py` dòng 111–113 **không** khử trùng | `N′(v)` theo Def. 10 là **tập hợp**. Nếu TTL có triple lặp, mẫu số bị thổi phồng. **Bản cũ cũng vậy** → số Journal 1 giữ nguyên, nhưng định nghĩa thì sai |
| LR-5 | **M** | dòng **256–257** | Có dòng bị comment `#max_iter: int = 3` với ghi chú `?????? add temporarily` | Giá trị siêu tham số **phụ thuộc lần sửa file gần nhất** → không tái lập | Đưa ra CLI `--max-iter` (mặc định 3), xoá comment |

#### 5.3.3 Các vấn đề còn lại

| # | Mức | Hàm / dòng | Vấn đề | Sửa nhỏ nhất | Trước TN? |
|---|---|---|---|---|---|
| LR-6 | **C** | `DEFAULT_TYPE_FILE` **579** | Trỏ tới `jikken_Hanami_EnglishVersion_EntityType` **không có đuôi `.txt`**, nhưng file thật là `…EntityType.txt` | Thêm `.txt`, hoặc `next(DATA_DIR.glob("jikken_Hanami_*"))` | **CÓ** (chặn `--check-hanami`) |
| LR-7 | **H** | `lrolesim_iteration()` **231** | `combinations(index_list, 2)` — **toàn bộ cặp**. Với `max_nodes=4000` (dòng 349) → 7,998,000 cặp/vòng. Đo được ~2–5 µs/cặp | Giảm `max_nodes` xuống ~800, **hoặc** cài đánh giá theo nhu cầu (demand-driven, §9) | **CÓ** |
| LR-8 | **H** | `Sim.max_delta()` **142** | `keys = set(self.dict) \| set(other.dict)` — vật chất hoá hợp của **toàn bộ** khoá. Đo được **+167,8 MB** ở \|Sim\|=719k ⟹ **~1,9 GB** ở n=4000 | Duyệt không tạo set: lặp `self.dict.items()` rồi bù các khoá chỉ có trong `other` | **CÓ** |
| LR-9 | **M** | `lrolesim()` **275–277** | `new_s` và `s` tồn tại đồng thời | Đỉnh RAM = 2×\|Sim\| + tập khoá của LR-8 | Tính `delta` **trong** `lrolesim_iteration()`, giải phóng `s` trước | Nên |
| LR-10 | **M** | `build_subgraph()` **314–321** | Khi vượt `max_nodes`, cắt theo bậc; **tie-break là thứ tự duyệt `set`** | Không tất định qua các lần sinh pickle; **sampling bias** có hệ thống (ưu tiên node bậc thấp) | `key=lambda x: (deg(x), x)`; và **ghi vào paper** rằng có cắt, kèm số node bị cắt | **CÓ** (tái lập) |
| LR-11 | **M** | `rank_by_similarity()` **365** | `edge_count(r_in)[0] + edge_count(r_out)[0]` — **đếm mỗi cạnh 2 lần**. So sánh: `build_hanami_spots()` dòng 685 chỉ dùng `edge_count(r_out)` (đúng) | Log sai gấp đôi; nếu đưa vào bảng "Statistics of datasets" thì sai số liệu paper | Chỉ dùng `edge_count(r_out)[0]`; nhãn cạnh lấy hợp của hai bên | **CÓ** nếu số này vào paper |
| LR-12 | **M** | `check_hanami_spots()` **733–741** | Chỉ kiểm `lrolesim_iteration()`. **Không** gọi `lrolesim()`, **không** gọi `rank_by_similarity()`, **không** gọi `build_subgraph()` với `max_nodes` hữu hạn | Regression test **không phủ** đúng những hàm mà Journal 2 dùng | Thêm 3 test: (a) `lrolesim(max_iter=3)` phải trùng `check_hanami_spots` k=3; (b) `build_subgraph` tất định qua 2 lần chạy; (c) `rank_by_similarity` trên HanamiSpots | **CÓ** |
| LR-13 | **M** | `check_hanami_spots()` **757** | `exp = expected.get(name, beta)` — node không liệt kê thì **mặc định β**. Nhưng nếu bạn đổi `beta` thì "expected" đổi theo, test luôn tự khớp | Test yếu | Liệt kê **đủ 13 node** trong `HANAMI_EXPECTED_FINAL`, `raise` nếu thiếu | Nên |
| LR-14 | **M** | `check_hanami_spots()` **746** | So `results[measure][3]` với cột **"Final similarity"** | Giả định "Final = iteration 3". Đúng theo mô tả của bạn, **nhưng** bài báo không nói vậy | Ghi rõ giả định vào docstring; nếu "Final" nghĩa là hội tụ thì phải so với `lrolesim(tol=…)` | **CÓ** |
| LR-15 | **L** | `load_entity_types()` **646–649** | `[x.strip() for x in line.split(",")]` — nếu URI chứa `", "` (dấu phẩy + khoảng trắng) thì khoảng trắng bị mất khi ghép lại | Với DBpedia (space → `_`) hiện an toàn, nhưng mong manh | `line.split(",", 2)` | Không |
| LR-16 | **L** | `from pathlib import Path` **575** | Import giữa file | Chỉ là style | Đưa lên đầu | Không |
| LR-17 | **L** | `main()` **773–789** | Không có `--type-file`, không có `--max-iter`, không có `--tol` | Không chạy được ablation qua CLI | Thêm 3 tham số | Nên |

**Trả lời trực tiếp mục VII của bạn:**

| Câu hỏi | Trả lời |
|---|---|
| Có giữ đúng định nghĩa LRoleSim của Journal 1 không? | **CÓ** — đã kiểm chứng số học (§5.3.1) |
| Thay đổi nào có thể đổi số liệu Journal 1? | LR-1 (hội tụ vs k=3), LR-2 (tie-break), LR-3 (NDCG). Xem §5.3.2 |
| Có regression test đủ không? | **KHÔNG** — LR-12, LR-13 |
| Có phân biệt fixed-3-iterations vs convergence không? | **CÓ phân biệt trong code** (`check_hanami_spots` dùng `n_iter=3`, `lrolesim` dùng `max_iter=20`) nhưng **KHÔNG phân biệt trong tài liệu/CLI** → nguy hiểm. LR-1, LR-5 |
| `build_subgraph()` có deterministic không? | Với **cùng một pickle**: gần như có (hash của int ổn định). Qua **các lần sinh pickle khác nhau**: **KHÔNG** (`read_ttl.py` dòng 73 duyệt một `set`). LR-10 |
| `max_nodes` có tạo sampling/truncation bias không? | **CÓ**, và là bias **có hệ thống** (ưu tiên bậc thấp) — phải khai báo trong paper. LR-10 |
| Edge count có bị tính hai lần từ in/out không? | **CÓ**, tại dòng 365. LR-11 |
| Tie-breaking có phụ thuộc node index không? | Trong `make_sorted_list_fn()`: **KHÔNG còn** (đã sửa, dòng 464). Trong `build_subgraph()`: **CÓ**. Trong `rank_candidates()` của file kia: **CÓ** |
| Hanami regression có thật sự kiểm numerical equivalence không? | **CÓ** cho `lrolesim_iteration()` tại k=1,2,3 — **nhưng chưa chạy được** ở đây (thiếu pickle). **KHÔNG** cho `lrolesim()`, `rank_by_similarity()`, `build_subgraph()`. LR-12 |
| `rank_by_similarity()` có phải API phù hợp cho Journal 2 không? | **Chữ ký thì đúng, chi phí thì sai.** Cần thêm: (a) cache theo class, (b) `max_iter` tường minh, (c) trả về cả metadata đồ thị con. LR-7 |
| File có thực sự sinh rationale không? | **KHÔNG.** Không có hàm nào liên quan rationale |
| File có xây MCQ evidence bipartite graph không? | **KHÔNG.** Việc đó ở `build_bipartite_and_draw_ExtendedVersion.py` |
| Có đang nhầm hai loại bipartite graph không? | **KHÔNG nhầm trong code v2** — file này chỉ có bipartite của **matching** (`_max_weight_matching`, dòng 187). Nhưng **rủi ro nhầm trong paper là rất cao** vì cả hai đều gọi là "bipartite graph". **Đặt tên khác nhau ngay từ bây giờ**: `matching bipartite graph BG_ij` (Journal 1, Algorithm 1) vs **`choice–evidence bipartite graph`** (Journal 2) |
| Nên tuyên bố "extend LRoleSim" hay "apply/incorporate"? | **"apply / incorporate LRoleSim into an MCQ-generation framework"**. Không có dòng nào thay đổi Definition 11 |
| Có nên thêm rationale generation vào LRoleSim không? | **KHÔNG.** Ranh giới module đúng: xem §9 |

### 5.4 Các file phụ (không nằm trong yêu cầu nhưng chặn thí nghiệm)

| # | Mức | File / dòng | Vấn đề |
|---|---|---|---|
| AUX-1 | **C** | `all_in_one.py` **369–370** | **SyntaxError**: `pickle_file = DATA_DIR /` xuống dòng rồi mới `"infobox…"`. File **không import được** |
| AUX-2 | **C** | `treat_entity_type.py` **189** | `time.sleep(wait_time)` nhưng file chỉ có `import requests` (dòng 1) → **NameError** (xem §7) |
| AUX-3 | **H** | `mcq_generation.py` **224 / 231 / 239** | `distractor_urls` (dòng 231, Plato) **không bao giờ được dùng**; dòng 239 dùng `distractors_url` (dòng 224, Yamanaka). Kết quả: **Answer = Plato nhưng distractor = Maskawa/Nozaki/Tomonaga** |
| AUX-4 | **H** | `mcq_generation.get_diff_fact()` **93–97** | Nhánh `else` coi *predicate vắng mặt* ở distractor là contrast → vi phạm OWA |
| AUX-5 | **H** | `mcq_generation.generate_long_question()` **176–182** | So sánh `uf2` (fact **đầu tiên** phân biệt A với `dd`) với `o_i` → phụ thuộc thứ tự dict, sinh **false negative** "không tìm được unique fact" |
| AUX-6 | **M** | `get_redirects.py` **141** | `sameAs_list.append(same)` — `same` chưa định nghĩa (đúng ra là `sameas_links`). NameError bị nuốt bởi `except: pass` dòng 142–143 → **mất dữ liệu âm thầm** (code Okuhara) |
| AUX-7 | **M** | `calc_dist.py` **36–48** | `mecab`, `np`, `spatial`, `word2vec_model` chưa định nghĩa (code Okuhara) |
| AUX-8 | **M** | `build_bipartite_….py` `get_popularity()` | `except: return 999999` — nuốt mọi lỗi mạng thành "rất phổ biến" ⟹ rarity ranking sai âm thầm khi DBpedia chậm |

---

## 6. Dependency / API inconsistencies

### 6.1 Bảng phụ thuộc thực tế

| Module import | Tên được import | Tồn tại trong `category_extractor.py` (bản CŨ)? | Tồn tại trong bản v2? |
|---|---|---|---|
| `extract_221…_v2` dòng 37–43 | `run_sparql` | **KHÔNG** | CÓ (dòng 104) |
| | `get_nodes_in_class` | **KHÔNG** | CÓ (dòng 229) |
| | `rank_classes_for_answer` | **KHÔNG** | CÓ (dòng 453) |
| | `DBPEDIA_ENDPOINT` | **KHÔNG** | CÓ (dòng 36) |
| | `DBPEDIA_LANG` | **KHÔNG** | CÓ (dòng 37) |
| `extract_221…` (bản CŨ) dòng 17 | `get_dbpedia_abstract` | CÓ (dòng 166) | **KHÔNG** ← chiều ngược lại cũng vỡ |

⟹ **Bất kể bạn đặt tên file thế nào, một trong hai chiều sẽ vỡ.** Bắt buộc phải chuyển bản cũ vào `legacy/` và **không** để `legacy/` trên `sys.path`.

### 6.2 Các bất nhất API khác

| # | Vấn đề | Vị trí |
|---|---|---|
| API-1 | **Quy ước hướng ngược nhau!** `extract_221…_v2` dòng 66: `OUT, IN = 1, 0`. `MCQ_lrolesim_v2` dòng 29: `IN, OUT = 0, 1`. Giá trị **trùng khớp** (IN=0, OUT=1) nhưng thứ tự khai báo ngược → **cực dễ sửa nhầm sau này**. Thống nhất một chỗ, import lẫn nhau |
| API-2 | `lrolesim()` đổi ngữ nghĩa: bản cũ (`MCQ_lrolesim.py` dòng 413) = **một vòng lặp**, nhận `s`; bản v2 (dòng 254) = **toàn bộ vòng lặp**, không nhận `s`. Cùng tên, khác nghĩa |
| API-3 | `edge_count()` được dùng nhất quán ở `build_hanami_spots` (dòng 685) nhưng sai ở `rank_by_similarity` (dòng 365) |
| API-4 | Không có **interface chung cho candidate ranker** ⟹ không chạy được ablation (Overlap vs LRoleSim vs random) — mà đây chính là thí nghiệm README yêu cầu ("Do not replace LRoleSim without an ablation experiment") |
| API-5 | `read_ttl.load_obj()` trả `index_type` **toàn số 0** (`read_ttl.py` dòng 85). Docstring của `load_entity_types()` (dòng 630–634) đã ghi đúng điều này ✔. Nhưng `MCQ_lrolesim_v2.main()` dòng 800–801 lấy `index_type` **thẳng từ pickle** rồi truyền vào `rank_by_similarity` (dòng 820) ⟹ **`lrolesim_edt` suy biến thành `lrolesim_ed`** mà không cảnh báo. **Cần `assert len(set(index_type.values())) > 1` khi `measure == "lrolesim_edt"`** |

---

## 7. Root cause của NameError

Chạy `pyflakes` trên toàn bộ 20 file Python trong Project, có **4** tên chưa định nghĩa:

```
treat_entity_type.py:189   undefined name 'time'          ← NGUYÊN NHÂN GỐC
get_redirects.py:141       undefined name 'same'          (code Okuhara)
calc_dist.py:36,37,39,41,46,47,48   mecab / np / spatial / word2vec_model   (code Okuhara)
all_in_one.py:369          invalid syntax  (SyntaxError, không phải NameError)
```

### Nguyên nhân gốc: `treat_entity_type.py` dòng 189

```python
   1  import requests                       # ← CHỈ CÓ import này
  ...
 177      retries = 3
 178      while retries > 0:
 179          try:
 180              response = requests.get(endpoint_url, params={...})
 181              data = response.json()
 183              if "boolean" in data:
 185                  return data["boolean"]
 186          except Exception as e:
 187              print(f"Error = {e} at ...")
 188              retries -= 1
 189              wait_time = 2 ** (3-retries)
 190              time.sleep(wait_time)      # ← NameError: name 'time' is not defined
```

**Vì sao lỗi này khó thấy và rất dễ gặp:**

1. Nó nằm **trong nhánh `except`**. Khi DBpedia chạy tốt, `try` thành công → không bao giờ chạm tới dòng 190. Code chạy tốt hàng tháng.
2. Nó chỉ nổ **đúng lúc DBpedia trả 502/503/timeout** — mà chính chú thích của `run_sparql()` (`category_extractor_ClaudeWeb_v2.py` dòng 107–112) mô tả đây là chuyện **thường xuyên**.
3. Nó **thay thế** exception gốc: bạn thấy `NameError: name 'time' is not defined` chứ **không** thấy `HTTPError 502`. Thông điệp lỗi trỏ sai hoàn toàn.
4. Nó **giết vòng retry**: `NameError` không bị `except Exception` bắt (vì đang ở *trong* handler), nên hàm thoát ngay, `entity_type_update()` không trả về gì → `index_type` sai/thiếu → `lrolesim_edt` suy biến (API-5).

**Sửa (1 dòng):**
```python
import requests
import time          # ← thêm
```

**Sửa phòng ngừa (khuyến nghị):** thêm `import time` **và** `raise` lại lỗi gốc sau khi hết retry, thay vì `return False` âm thầm (dòng 192).

**Lưu ý:** nếu `NameError` bạn gặp **không** phải cái này, hai ứng viên tiếp theo là (a) `mcq_generation.py` dòng 231/239 (biến `distractor_urls` vs `distractors_url` — thực ra là logic bug, không phải NameError), và (b) `all_in_one.py` dòng 369 (SyntaxError sẽ hiện ra là `SyntaxError`, không phải `NameError`). Hãy gửi tôi **traceback đầy đủ** nếu vẫn còn.

---

## 8. Danh sách sửa chữa

### 8.1 BẮT BUỘC trước khi chạy 100 MCQ (12 mục)

| Ưu tiên | ID | Việc | File / dòng |
|---|---|---|---|
| 1 | AUX-2 | `import time` | `treat_entity_type.py` dòng 1 |
| 2 | CE-1 / EX-1 | Đổi tên `category_extractor_ClaudeWeb_v2.py` → `src/category_extractor.py`; chuyển bản cũ vào `legacy/` | — |
| 3 | LR-6 | Sửa `DEFAULT_TYPE_FILE` thêm `.txt` | `MCQ_lrolesim_v2` dòng 579 |
| 4 | AUX-1 | Sửa SyntaxError | `all_in_one.py` dòng 369 |
| 5 | **EX-3** | Thay điều kiện \|R\|=1 bằng **set cover bitmask** | `extract_221_v2` dòng 450–455, 507–510 |
| 6 | **EX-2** | Nối `rank_by_similarity()` của LRoleSim vào pipeline (dù chỉ như một ranker tuỳ chọn) | `extract_221_v2` |
| 7 | EX-5 | Dùng `score_norm` cho sort + MMR | dòng 381, 426 |
| 8 | EX-4 | Sửa khoá `_edgeset_cache` | dòng 115, 125–131 |
| 9 | EX-6 | Thêm `evidence_level()` (L2/L1/L0), 100 câu chỉ dùng L2 | `distinguishing_facts()` dòng 389 |
| 10 | EX-12 | Sửa tên field cho cạnh IN | dòng 518–521 |
| 11 | LR-7 + LR-8 | `max_nodes` mặc định 4000 → 800; sửa `max_delta()` không tạo set hợp | dòng 349, 142 |
| 12 | CE-6 + EX-13 + EX-11 | `ORDER BY ?x`; tie-break tường minh; bỏ greedy fallback | CE dòng 235; EX dòng 381, 292–302 |

### 8.2 NÊN sửa trước khi viết paper (9 mục)

| ID | Việc |
|---|---|
| CE-2 | Đổi tên `choose_best_class_for_answer()` → `first_feasible_class()`; bỏ chữ "best" khỏi mọi log và paper |
| CE-3 | Gộp truy vấn `n_local` thành 1 SPARQL |
| CE-7 / EX-8 | Encode abstract theo chunk; lưu **full text** vào cache |
| CE-9 | Chuẩn hoá SBERT/IDF theo rank trong cùng answer; ablation α |
| CE-8 | Thêm metadata/version cho cache — đây là *bằng chứng tái lập* bạn nộp kèm paper |
| LR-1 / LR-5 / LR-17 | `--max-iter` (mặc định **3**), `--tol`, `--type-file` |
| LR-11 | Sửa đếm cạnh gấp đôi (dòng 365) — quan trọng nếu số này vào bảng thống kê |
| LR-12 / LR-13 | Bổ sung 3 regression test còn thiếu; liệt kê đủ 13 node kỳ vọng |
| EX-7 / EX-14 | MMR đo trên rationale signature; thống nhất định nghĩa "unique" ở mức (p, d) |

### 8.3 CÓ THỂ TRÌ HOÃN (6 mục)

| ID | Việc | Lý do trì hoãn |
|---|---|---|
| — | **Redirect / canonical URI** | Chưa có bằng chứng hỏng; hai URI bạn test chạy tốt. Chỉ làm khi audit log cho thấy tỉ lệ "no category" cao (Phụ lục A) |
| CE-11 | Tinh chỉnh tầng lemma/synonym | Cần dữ liệu yield rate trước |
| CE-12 | Tách truy vấn tích Descartes | Chỉ ảnh hưởng băng thông |
| CE-4 / CE-5 | Thread-safety | Nếu bạn chạy tuần tự (`max_workers=1`) thì không cần ngay |
| EX-9 | Persist vector SBERT | Có RTX 5090, encode lại rẻ |
| LR-4 | Khử triple trùng lặp | Ảnh hưởng nhỏ, nhưng **phải ghi vào Limitations** |

---

## 9. Kiến trúc tối thiểu được đề xuất

**Nguyên tắc:** LRoleSim là một **thư viện độ tương tự**, không biết gì về MCQ. Rationale là một **module riêng**, không biết gì về LRoleSim. Pipeline nối chúng lại.

```
src/
├── kg/
│   ├── loader.py           # load_kg(), KG dataclass, extended_edgeset()
│   │                       #   → cache khoá (id(kg), node, use_in)   [sửa EX-4]
│   └── sparql.py           # SparqlCache + run_sparql + metadata     [CE-8]
│
├── lrolesim/               # ===== ĐÓNG BĂNG. Không thêm gì liên quan MCQ =====
│   ├── core.py             # Sim, precompute_groups, lrolesim_iteration,
│   │                       #   lrolesim(max_iter=3)                  [LR-1, LR-8]
│   ├── measures.py         # MEASURES registry, _key_function
│   ├── subgraph.py         # build_subgraph (tie-break tường minh)   [LR-10]
│   └── metrics.py          # MRR / NDCG / P@k  (chỉ dùng cho Journal 1 ablation)
│
├── selection/
│   ├── ranker.py           # ↓ INTERFACE CHUNG — chìa khoá của ablation  [API-4]
│   │     class CandidateRanker(Protocol):
│   │         name: str
│   │         def rank(self, answer: int, cands: Sequence[int],
│   │                  kg: KG) -> list[tuple[float, int]]: ...
│   ├── overlap_ranker.py   # OverlapStrict/Loose (baseline)
│   ├── lrolesim_ranker.py  # gọi lrolesim/subgraph — CACHE THEO CLASS  [LR-7]
│   ├── random_ranker.py    # baseline của Umematsu (class ngẫu nhiên)
│   └── select.py           # MMR + ràng buộc (C1)(C2)(C3)             [EX-3, EX-7]
│
├── rationale/              # ===== MODULE MỚI, ĐỘC LẬP =====
│   ├── evidence.py         # evidence_level(f, A, d) -> L2 | L1 | L0  [EX-6]
│   ├── setcover.py         # minimum_rationale() bằng bitmask O(m·2^k) [EX-3]
│   └── verbalize.py        # triple -> câu tiếng Anh
│
├── classes/
│   └── selector.py         # manual | recommended | first_feasible    [CE-2]
│
└── pipeline.py             # orchestration + audit JSONL
```

### 9.1 Ba can thiệp tạo ra khác biệt lớn nhất

**(A) Set cover bitmask — thay dòng 450–455.** Đã chạy thật (T2.4):

```python
def minimum_rationale(a_edges, d_edges_list, rho=3):
    """R* nhỏ nhất phủ hết distractor. O(m * 2^k). Trả None nếu |R*| > rho."""
    k = len(d_edges_list); full = (1 << k) - 1
    masks = {}
    for f in a_edges:
        m = sum(1 << i for i, de in enumerate(d_edges_list) if f not in de)
        if m and m not in masks:
            masks[m] = f
    best = {0: []}
    for _ in range(min(k, rho)):
        nxt = dict(best)
        for cov, sol in best.items():
            for m, f in masks.items():
                nc = cov | m
                if nc not in nxt or len(sol) + 1 < len(nxt[nc]):
                    nxt[nc] = sol + [f]
        best = nxt
    R = best.get(full)
    return R if (R is not None and len(R) <= rho) else None
```

**(B) Cache LRoleSim theo CLASS, không theo câu hỏi.** Hiện `build_choices()` gọi `rank_candidates()` cho từng Answer. Nhưng đồ thị con của **cùng một class** gần như không đổi. Nếu 100 Answer trải trên ~40 class ⟹ giảm ~2,5×. Cụ thể: khoá cache = `(class, measure, beta, max_iter, max_nodes, pickle_hash)`, lưu `Sim` xuống đĩa.

**(C) Đánh giá theo nhu cầu (demand-driven) — nếu (B) chưa đủ.** Bạn không cần toàn bộ ma trận `n²`. Với `k` vòng lặp cố định, `S^k(A,d)` chỉ phụ thuộc các cặp cách `(A,d)` không quá `k` bước trong **đồ thị cặp**. Cài đặt đệ quy có memo:

```
S(u, v, 0) = 1
S(u, v, t) = (1-β) · Σ_{key ∈ K(u)∩K(v)} maxmatch{ S(x, y, t-1) } / max(|N'(u)|,|N'(v)|) + β
```

gọi từ `{(A,d) : d ∈ C}` với `t = 3`. Số cặp thực sự chạm tới thường **nhỏ hơn `n²` vài bậc** trên đồ thị thưa như DBpedia. **Đây có thể trở thành một đóng góp kỹ thuật phụ hợp lệ của bài báo 2** ("query-driven evaluation of LRoleSim for top-k candidate ranking"), miễn là bạn **chứng minh nó cho ra đúng cùng giá trị** với đánh giá toàn ma trận tại cùng `k` (điều này đúng vì công thức là bottom-up thuần tuý).

### 9.2 Ranh giới module đúng (trả lời câu hỏi cuối mục VII)

| Việc | Thuộc module | KHÔNG thuộc |
|---|---|---|
| Tính `S_LRoleSim(A, d)` | `lrolesim/` | — |
| Chọn đồ thị con | `lrolesim/subgraph.py` | — |
| Xếp hạng ứng viên | `selection/lrolesim_ranker.py` | `lrolesim/` |
| Kiểm tra tồn tại rationale | `rationale/setcover.py` | `lrolesim/`, `selection/` |
| Phân loại bằng chứng OWA | `rationale/evidence.py` | — |
| Vẽ **choice–evidence bipartite graph** | `rationale/` (hoặc `viz/`) | `lrolesim/` — đây là bipartite graph **khác** với `BG_ij` của Algorithm 1 |

**Tuyệt đối không** thêm hàm sinh rationale vào `MCQ_lrolesim*.py`. Nó sẽ khiến reviewer tưởng bạn sửa LRoleSim, và bạn sẽ phải chứng minh admissibility lại từ đầu.

---

## 10. Acceptance criteria cho ba file v3

Mỗi tiêu chí phải **chạy được** và **cho ra output kiểm chứng được**. Không tiêu chí nào được đánh dấu đạt bằng mắt thường.

### 10.1 `src/lrolesim/` (thay `MCQ_lrolesim_ClaudeWeb_v2.py`)

| # | Tiêu chí | Cách kiểm chứng |
|---|---|---|
| L1 | `pytest tests/test_hanami.py` **chạy được và pass** | Tái lập **đủ 13 node × 3 vòng lặp × 5 độ đo** = 195 giá trị của Bảng 1, dung sai 5e-4 |
| L2 | `lrolesim(beta=0.2, max_iter=3)` cho **cùng ma trận** với `check_hanami_spots(n_iter=3)` | `assert Sim.max_delta(...) < 1e-12` |
| L3 | `build_subgraph()` **tất định** | Chạy 2 lần trong 2 process ⟹ list node **giống hệt**; test có `max_nodes` nhỏ để **kích hoạt** nhánh cắt (dòng 314–321) |
| L4 | `rank_by_similarity()` trên HanamiSpots trả đúng thứ tự Bảng 1 (cột `lrolesim_ed`, k=3) | Assert top-3 |
| L5 | Cảnh báo khi `measure="lrolesim_edt"` mà `index_type` chỉ có một giá trị | `pytest.warns` hoặc `raise ValueError` |
| L6 | `edge_count` nhất quán | `rank_by_similarity` in ra **15** cho HanamiSpots, không phải 30 |
| L7 | RAM: `lrolesim()` với n = 2000 không vượt **1,5 GB** | `tracemalloc`, ghi vào log test |
| L8 | Bản cũ được giữ nguyên tại `legacy/MCQ_lrolesim_journal1_archive.py` và **không** nằm trên `sys.path` | `pytest` import thất bại có chủ đích |
| L9 | Không có identifier nào chứa `rationale`, `mcq`, `distractor`, `choice` | `grep -i` trả rỗng |
| L10 | Mọi siêu tham số qua CLI: `--measure --beta --max-iter --tol --hops --max-nodes --type-file` | `--help` liệt kê đủ 7 |

### 10.2 `src/classes/selector.py` (thay `category_extractor_ClaudeWeb_v2.py`)

| # | Tiêu chí | Cách kiểm chứng |
|---|---|---|
| C1 | Ba chế độ `mode ∈ {manual, recommended, first_feasible}` chạy được | Test với `Makoto_Kobayashi_(physicist)` và `Akira_Suzuki_(chemist)`; cả hai **phải** ra class (đúng kết quả bạn đã kiểm) |
| C2 | Không còn identifier/log/docstring nào chứa chữ `best` | `grep -i "best" src/classes/` trả rỗng |
| C3 | Audit output cho **mỗi** answer: `{original_uri, canonical_or_query_uri, display_label, n_categories, n_rejected_by_reason, chosen_class, mode}` | JSONL, 100 dòng cho 100 answer |
| C4 | Phân biệt được 4 trạng thái: `QUERY_FAILED` / `NO_CATEGORY` / `ALL_REJECTED` / `OK` | Test bằng cách mock `run_sparql` trả `None`, `[]`, và list đầy category rác |
| C5 | Với `local_index != None`, số truy vấn SPARQL ≤ **3** cho mỗi answer | Đếm bằng counter trong `run_sparql` |
| C6 | Cache có bảng `meta` với `schema_version`, `endpoint`, `lang`, `created_at`; `--refresh` hoạt động | `sqlite3 … "SELECT * FROM meta"` |
| C7 | `format_display_label()` pass **toàn bộ** bộ test ở Phụ lục B (7 case) | `pytest` |
| C8 | `remove_parenthetical()` **chỉ** được gọi bên trong `leaks_answer()` | `grep -n "remove_parenthetical" src/` — tối đa 4 chỗ, đều trong hàm đó |
| C9 | Chạy 100 answer với `max_workers=6` cho **cùng kết quả** với `max_workers=1` | So sánh 2 file JSONL |
| C10 | `ORDER BY ?x` trong mọi truy vấn có `LIMIT`; cảnh báo khi `len(kết quả) == LIMIT` | grep + test |

### 10.3 `src/selection/` + `src/rationale/` (thay `extract_221_and_select_distractors_ClaudeWeb_v2.py`)

| # | Tiêu chí | Cách kiểm chứng |
|---|---|---|
| S1 | Ít nhất **3** ranker cài cùng `CandidateRanker` protocol: `overlap`, `lrolesim_ed`, `random` | `--ranker` chạy được cả ba; bảng ablation sinh tự động |
| S2 | `--ranker lrolesim_ed` **thực sự** gọi `lrolesim.rank_by_similarity()` | Counter/`assert_called_once` |
| S3 | Test T2.3 của tôi **phải PASS** (câu hỏi 2-fact được **giữ lại**, không bị loại) | Đưa nguyên KG tổng hợp đó vào `tests/` |
| S4 | `minimum_rationale()` trùng kết quả brute-force trên 1000 case ngẫu nhiên (k ≤ 5, m ≤ 20) | Property-based test |
| S5 | Mỗi rationale xuất ra kèm `evidence_level`; **0 câu** trong 100 câu cuối có `L0` | Đếm trong JSONL |
| S6 | Với `direction = IN`, trường được đặt tên `subject` (không phải `object`) | Schema check |
| S7 | `extended_edgeset(n, kg, use_in=False)` ≠ `extended_edgeset(n, kg, use_in=True)` khi node có cạnh IN | `pytest` (chính là T2.1) |
| S8 | Sắp xếp ứng viên **tất định**: chạy 2 lần cho cùng thứ tự | So sánh JSONL |
| S9 | Không có nhánh matching greedy; thiếu scipy ⟹ `raise` | Test bằng `monkeypatch` che scipy |
| S10 | **Yield rate được báo cáo** cho `ρ = 1, 2, 3` trên cùng 100 answer | Bảng 3 dòng — **đây là bảng kết quả chính của bài báo** |
| S11 | Toàn bộ 100 MCQ end-to-end chạy < **60 phút** trên máy của bạn | `time` + log |
| S12 | Output JSONL đủ trường tái lập: `{answer, class, mode, ranker, measure, beta, max_iter, rho, distractors[], rationale[{fact, evidence_level, source}], sparql_cache_sha256}` | Schema validation |

---

## Phụ lục A — Redirect, canonical URI và display label

### A.1 Bốn khái niệm — định nghĩa tách bạch

| Khái niệm | Định nghĩa | Ai dùng |
|---|---|---|
| `original_uri` | URI người dùng/dataset cung cấp, giữ **nguyên văn**, không bao giờ sửa | khoá chính của mọi bản ghi audit |
| `canonical_or_query_uri` | URI dùng để **gọi SPARQL**. Mặc định = `original_uri`. Chỉ khác khi đã giải redirect | `fetch_answer_info()`, `get_nodes_in_class()` |
| `local_kg_uri` | URI **tồn tại trong pickle** (`url_index`). Có thể khác cả hai trên (TTL infobox là snapshot cũ hơn endpoint) | `KG.idx()` |
| `display_label` | Chuỗi hiển thị cho học sinh | chỉ tầng trình bày |

**Bốn khái niệm này hiện đang bị trộn.** `build_choices()` dòng 488 dùng `answer_uri` cho `kg.idx()` **và** dòng 493 cho `rank_classes_for_answer()` — tức `local_kg_uri` và `canonical_or_query_uri` bị giả định bằng nhau.

### A.2 Đánh giá phương án tối giản của bạn

Phương án bạn đề xuất — dùng nguyên URI trước; chỉ truy vấn `dbo:wikiPageRedirects` khi (không label) ∨ (không category) ∨ (không có trong KG cục bộ) ∨ (không ánh xạ được remote↔local); không sửa khoá pickle âm thầm; lưu cả original và canonical vào audit output — **là ĐỦ, và đúng mức**.

**Bằng chứng ủng hộ:**
- `Makoto_Kobayashi_(physicist)` → `dbc:J._J._Sakurai_Prize…` và `Akira_Suzuki_(chemist)` → `dbc:Japanese_chemists` **đều trả về category hợp lệ** ⟹ giả thuyết "URI có ngoặc cần canonicalize" **bị bác bỏ**.
- Code v2 **hiện không có** một dòng redirect nào ⟹ đây là *tính năng chưa có*, không phải *lỗi đang gây hại*.
- Bốn điều kiện kích hoạt của bạn đúng là **tập các triệu chứng quan sát được**, không phải suy đoán.

**Có làm code phức tạp quá mức không?** Nếu bạn cài **đúng như mô tả** (lazy, chỉ 4 điều kiện, không ghi đè pickle) thì **không** — thêm khoảng 25 dòng. Nó sẽ phức tạp quá mức nếu bạn (a) canonicalize mọi URI ngay từ đầu, (b) viết lại khoá pickle, hoặc (c) canonicalize cả **object** của triple (số lượng gấp ~20 lần).

### A.3 Khuyến nghị

**DEFER.** Trước tiên chạy 100 answer với chế độ `first_feasible` và ghi log `NO_CATEGORY` / `NOT_IN_LOCAL_KG` (tiêu chí C4). **Nếu tỉ lệ < 5%** thì đừng cài redirect — hãy dành 3 tháng cho set cover + OWA + ablation, những thứ tạo ra novelty. **Nếu > 15%**, hãy cài đúng phương án tối giản trên.

---

## Phụ lục B — Chính sách xử lý phần trong ngoặc

### B.1 Chẩn đoán hiện trạng

| Câu hỏi của bạn | Trả lời |
|---|---|
| `remove_parenthetical()` có xoá quá rộng không? | **CÓ.** Regex `\([^)]*\)` (dòng 282) không phân biệt gì cả. Đã chứng minh (T2.5) |
| Đang dùng cho display label hay chỉ leak detection? | **CHỈ leak detection** — 4 chỗ gọi, đều trong `leaks_answer()` (dòng 295, 296, 305, 308). **Không** hàm nào dùng nó để hiển thị |
| Có nguy cơ làm sai entity hóa học không? | Với **leak detection**: rủi ro thấp (tầng lemma dòng 315–325 vẫn bắt gốc từ "phosphorus"/"iron"). Với **display**: **rủi ro cao** — `Iron(III) chloride` và `Iron(II) chloride` sẽ hiển thị giống hệt nhau ⟹ câu hỏi vô hiệu |
| Nên dùng `rdfs:label` trước không? | **CÓ.** `fetch_answer_info()` đã lấy sẵn (dòng 169, 184–185). Label xử lý dấu và ký tự đặc biệt đúng hơn phần cuối URI (`Kantō_region` → "Kantō region"). Nhưng label **vẫn chứa** disambiguator ("Makoto Kobayashi (physicist)") nên vẫn cần các luật dưới |

### B.2 Chính sách `format_display_label()` — tổng quát, không hard-code, kiểm thử được

**Nguyên tắc nền:** chỉ bỏ ngoặc khi nó là **disambiguator của Wikipedia** — nhận diện được bằng **hình thức cú pháp** cộng với **một danh sách trắng sinh tự động từ chính KG**. Mọi trường hợp khác: **GIỮ**.

Áp dụng theo thứ tự, dừng ở luật đầu tiên khớp:

| Luật | Điều kiện | Hành động | Ví dụ |
|---|---|---|---|
| **R0** | — | Lấy `rdfs:label`@lang; không có thì `unquote(uri.rsplit("/",1)[-1]).replace("_"," ")` | `Kantō_region` → `Kantō region` |
| **R1** | Không có `(` | **GIỮ** | `Plato` |
| **R2** | Ngoặc **không** ở cuối chuỗi | **GIỮ** | `Phosphorus(V) oxide`, `Iron(III) chloride` |
| **R3** | **Không có khoảng trắng ngay trước `(`** | **GIỮ** | `Phosphorus(V)` — disambiguator Wikipedia **luôn** có khoảng trắng/`_` trước `(` |
| **R4** | Nội dung ngoặc khớp `^[IVXLCDM]+$` (số La Mã) hoặc `^[0-9±+\-.,/ ]+$` | **GIỮ** | `(V)`, `(III)`, `(1,2)` |
| **R5** | Ngoặc ở cuối + có khoảng trắng trước + nội dung **có trong danh sách trắng disambiguator** | **BỎ** | `(physicist)`, `(chemist)`, `(Tokyo)`, `(disambiguation)` |
| **R6** | Còn lại (không chắc chắn) | **GIỮ** | `Vitamin B12 (cobalamin)`, `(the younger)` |

**Danh sách trắng sinh tự động — đây là điểm mấu chốt "không hard-code từng Answer":**

```sparql
SELECT ?dis (COUNT(DISTINCT ?x) AS ?n) WHERE {
  ?x rdfs:label ?l . FILTER(lang(?l) = 'en')
  BIND(REPLACE(STR(?l), "^.* \\((.*)\\)$", "$1") AS ?dis)
  FILTER(?dis != STR(?l))
} GROUP BY ?dis HAVING (COUNT(DISTINCT ?x) > 50)
```

Chạy **một lần**, lưu vào `data/disambiguators.txt`, **công bố kèm bài báo**. `physicist`, `chemist`, `film`, `album`, `band`, `footballer`, `Tokyo`… sẽ xuất hiện với hàng nghìn entity; `cobalamin`, `the younger` thì không.

### B.3 Bất biến bắt buộc — quan trọng hơn cả luật xoá

Mối lo "Answer node bị leak" **không** được giải quyết bằng việc xoá ngoặc, mà bằng hai bất biến:

> **INV-1 (Uniformity).** Cùng một chính sách phải áp dụng cho **cả 4 lựa chọn**. Nếu một lựa chọn giữ ngoặc và ba lựa chọn kia không, đó **chính là** leak.
>
> **INV-2 (Distinctness).** Nếu sau khi áp dụng, hai lựa chọn bất kỳ có **cùng** `display_label`, thì **hoàn nguyên cả bốn** về nhãn đầy đủ. Ví dụ `Iron(II) chloride` và `Iron(III) chloride` không bao giờ được cùng hiển thị "Iron chloride".

Hai bất biến này biến "khi không chắc thì nên giữ hay xoá?" thành một câu trả lời có nguyên tắc: **GIỮ**. Chi phí của việc giữ = nhãn dài hơn một chút (chấp nhận được). Chi phí của việc xoá = (a) sai thực thể hóa học, (b) hai lựa chọn trùng nhãn ⟹ câu hỏi vô hiệu, (c) leak bất đối xứng. Cả ba đều nghiêm trọng hơn.

### B.4 Bộ test bắt buộc (tiêu chí C7)

```python
assert display("<…/Makoto_Kobayashi_(physicist)>")        == "Makoto Kobayashi"
assert display("<…/Akira_Suzuki_(chemist)>")              == "Akira Suzuki"
assert display("<…/Tamagawa_Station_(Tokyo)>")            == "Tamagawa Station"
assert display("<…/Phosphorus(V)_oxide>")                 == "Phosphorus(V) oxide"
assert display("<…/Iron(III)_chloride>")                  == "Iron(III) chloride"
assert display("<…/Vitamin_B12_(cobalamin)>")             == "Vitamin B12 (cobalamin)"
assert display("<…/Kantō_region>")                        == "Kantō region"

# INV-2
labels = format_choice_labels([iron_ii_chloride, iron_iii_chloride, x, y])
assert len(set(labels)) == 4
```

---

## Phụ lục C — Lộ trình 3 tháng (đề xuất)

| Tuần | Việc | Đầu ra kiểm chứng được |
|---|---|---|
| 1 | §8.1 mục 1–4 (4 lỗi chặn) + đổi cấu trúc thư mục theo §9 | `pytest` chạy được; `--check-hanami` pass |
| 2 | §8.1 mục 5, 9 (set cover + evidence level) | Test T2.3 pass; `minimum_rationale` property test pass |
| 3 | §8.1 mục 6, 7, 8, 10–12 | 3 ranker cùng interface, chạy được `--ranker` |
| 4 | **Chạy 100 answer, đo yield rate cho ρ = 1, 2, 3** | **Bảng kết quả chính của paper** |
| 5–6 | Ablation 5 độ đo LRoleSim × 3 ranker; §8.2 | Bảng ablation |
| 7 | Verbalization + choice–evidence bipartite graph | 100 MCQ hoàn chỉnh |
| 8 | Đánh giá con người (giáo sư + vài sinh viên) trên mẫu 30 câu | Bảng đánh giá |
| 9–11 | Viết bài | Bản nháp |
| 12 | Sửa + nộp | — |

**Cột mốc quan trọng nhất là tuần 4.** Con số "yield rate tăng từ X% (ρ=1) lên Y% (ρ=3)" chính là câu chuyện của bài báo. Mọi thứ khác là hỗ trợ.

---

## Phụ lục D — Mã kiểm thử đã dùng

Ba script sau đã được **chạy thật** trong lượt này; bạn nên đưa vào `tests/`:

- `t1_lrolesim_kernel.py` — kiểm chứng số học kernel LRoleSim trên lõi HanamiSpots
- `t2_distractor_bugs.py` — cache key, `score_norm`, set-cover gap, bitmask, parenthetical
- `t3_cost.py` — benchmark thời gian + bộ nhớ

*(Nội dung được kèm riêng cùng báo cáo này.)*
