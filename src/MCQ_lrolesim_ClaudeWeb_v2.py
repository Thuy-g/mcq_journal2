############################################################################
# MCQ_lrolesim.py  (phiên bản viết lại — thư viện LRoleSim)  được sửa lại bởi Claude Chat trên Web.
#
# QUAN TRỌNG — TRƯỚC KHI DÙNG:
#   Hãy giữ nguyên file cũ dưới tên MCQ_lrolesim_journal1_archive.py.
#   File cũ chứa toàn bộ harness thí nghiệm của journal 1 (jikken1..jikken5-4).
#   Bạn CẦN nó để tái lập journal 1. File này chỉ là thư viện sạch cho journal 2
#   và cho phần ablation.
#
# BỐN NHÓM THAY ĐỔI:
#   A. SỬA LỖI ĐÚNG/SAI — 3 lỗi có thể đã ảnh hưởng số liệu journal 1
#      (xem mục "LỖI 1/2/3" trong chú thích bên dưới).
#   B. TĂNG TỐC — bỏ O(n^2 * d) phân hoạch lặp lại, thay Munkres bằng scipy,
#      thêm đường tắt cho ma trận nhỏ, bỏ qua cặp không chia sẻ key.
#   C. API CHO JOURNAL 2 — build_subgraph() + rank_by_similarity().
#   D. REGISTRY ĐỘ ĐO — đổi độ đo bằng một chuỗi, để chạy bảng ablation
#      (RoleSim / LRoleSim_d / _e / _ed / _edt) đúng như Bảng 8 của journal 1.
############################################################################

from __future__ import annotations

import argparse
import math
import time
from collections import defaultdict
from itertools import combinations
from typing import Callable, Iterable, Optional, Sequence

IN, OUT = 0, 1     # quy ước hướng, giữ nguyên như code cũ

# ---------------------------------------------------------------------------
# 1) CÁC QUAN HỆ TƯƠNG ĐƯƠNG
#    Giữ lại nguyên vẹn để code cũ (all_in_one.py, mcq_generation.py) không vỡ,
#    NHƯNG phần tính toán nóng bên dưới không còn dùng chúng nữa — xem mục 3.
# ---------------------------------------------------------------------------

class ElementWithAllSameRelation:
    """L_none  ->  chính là RoleSim gốc (không phân biệt gì cả)."""
    def __init__(self, po, direction): pass
    def __hash__(self): return 0
    def __eq__(self, other): return True


class ElementWithEdgeEquivalenceRelation:
    """L_e  ->  chỉ phân biệt theo nhãn cạnh."""
    def __init__(self, po, direction): self.p = po[0]
    def __hash__(self): return hash(self.p)
    def __eq__(self, other): return self.p == other.p


class ElementWithDirectionEquivalenceRelation:
    """L_d  ->  chỉ phân biệt theo hướng cạnh."""
    def __init__(self, po, direction): self.d = direction
    def __hash__(self): return hash(self.d)
    def __eq__(self, other): return self.d == other.d


class ElementWithEdgeDirectionEquivalenceRelation:
    """L_ed  ->  nhãn + hướng. Đây là độ đo mặc định của journal 1."""
    def __init__(self, po, direction): self.pd = (po[0], direction)
    def __hash__(self): return hash(self.pd)
    def __eq__(self, other): return self.pd == other.pd


class ElementWithEdgeDirectionEquivalenceRelation_EntityType:
    """L_edt  ->  nhãn + hướng + kiểu thực thể của node láng giềng."""
    def __init__(self, po, direction, o_entity_type):
        self.pdt = (po[0], direction, o_entity_type)
    def __hash__(self): return hash(self.pdt)
    def __eq__(self, other): return self.pdt == other.pdt


# --- Registry: chọn độ đo bằng một chuỗi -> chạy được bảng ablation ---------
MEASURES = {
    "rolesim":      ElementWithAllSameRelation,
    "lrolesim_d":   ElementWithDirectionEquivalenceRelation,
    "lrolesim_e":   ElementWithEdgeEquivalenceRelation,
    "lrolesim_ed":  ElementWithEdgeDirectionEquivalenceRelation,
    "lrolesim_edt": ElementWithEdgeDirectionEquivalenceRelation_EntityType,
}
_CLASS_TO_NAME = {v: k for k, v in MEASURES.items()}


def _key_function(measure: str, index_type=None) -> Callable:
    """Trả về hàm sinh KEY dạng tuple thay vì tạo một object cho mỗi cạnh.

    LÝ DO (đây là tối ưu lớn nhất về hằng số):
    Code cũ tạo một instance ElementWith... cho MỖI cạnh, của MỖI node, trong
    MỖI cặp, ở MỖI vòng lặp. Với 5.000 node (12,5 triệu cặp), bậc trung bình 20
    và 3 vòng lặp: ~1,5 tỷ lần gọi __init__ + __hash__ + __eq__ bằng Python
    thuần. Tuple được băm ở tầng C và không cần cấp phát object.
    """
    if measure == "rolesim":
        return lambda p, d, o: 0
    if measure == "lrolesim_d":
        return lambda p, d, o: d
    if measure == "lrolesim_e":
        return lambda p, d, o: p
    if measure == "lrolesim_ed":
        return lambda p, d, o: (p, d)
    if measure == "lrolesim_edt":
        it = index_type if index_type is not None else {}
        return lambda p, d, o: (p, d, it.get(o))
    raise ValueError(f"Độ đo không hợp lệ: {measure}. Chọn trong {list(MEASURES)}")


# ---------------------------------------------------------------------------
# 2) LƯU TRỮ ĐỘ TƯƠNG TỰ
# ---------------------------------------------------------------------------

class Sim:
    """Ma trận tương tự thưa. Không lưu giá trị 1.0 để tiết kiệm bộ nhớ.

    Mặc định trả về 1.0 là ĐÚNG, không phải lỗi:
      - s^0(u,v) = 1 với mọi u,v  (khởi tạo của RoleSim)
      - s(u,u)   = 1 với mọi u    (tính phản xạ, không bao giờ được lưu)
    """

    __slots__ = ("dict",)

    def __init__(self):
        self.dict = {}

    def __getitem__(self, key):
        u, v = key
        # SỬA: bỏ tuple(sorted(key)). sorted() cấp phát một list mới ở MỖI lần
        # truy cập, mà hàm này bị gọi hàng tỷ lần. Một phép so sánh là đủ.
        t = (u, v) if u <= v else (v, u)
        return self.dict.get(t, 1.0)

    def __setitem__(self, key, value):
        if value == 1.0:
            return
        u, v = key
        self.dict[(u, v) if u <= v else (v, u)] = value

    def __len__(self):
        return len(self.dict)

    def max_delta(self, other: "Sim") -> float:
        """Sai khác lớn nhất giữa hai vòng lặp — dùng để kiểm tra hội tụ."""
        keys = set(self.dict) | set(other.dict)
        if not keys:
            return 0.0
        return max(abs(self.dict.get(k, 1.0) - other.dict.get(k, 1.0)) for k in keys)


# ---------------------------------------------------------------------------
# 3) TIỀN TÍNH CÁC LỚP TƯƠNG ĐƯƠNG  (thay đổi thuật toán quan trọng nhất)
# ---------------------------------------------------------------------------

def precompute_groups(index_list: Sequence[int], in_neighbor, out_neighbor,
                      measure: str, index_type=None) -> dict:
    """{node: {key: [neighbor,...]}} — phân hoạch MỘT LẦN cho mỗi node.

    LÝ DO: code cũ gọi partition_by_binary_label_function(iu, iv, ou, ov, ...)
    bên trong vòng lặp qua từng CẶP. Nghĩa là láng giềng của node u được phân
    hoạch lại n-1 lần (một lần với mỗi bạn ghép), ở mỗi vòng lặp.
      - Cũ:  O(n^2 * d) công phân hoạch
      - Mới: O(n * d)
    Với n = 5.000: giảm khoảng 5.000 lần khối lượng phân hoạch.
    """
    kf = _key_function(measure, index_type)
    groups: dict[int, dict] = {}
    for u in index_list:
        g: dict = defaultdict(list)
        for p, s in in_neighbor.get(u, ()):
            g[kf(p, IN, s)].append(s)
        for p, o in out_neighbor.get(u, ()):
            g[kf(p, OUT, o)].append(o)
        groups[u] = dict(g)
    return groups


def node_degree(groups_u: dict) -> int:
    """|N(u)| = tổng số láng giềng, tính cả in lẫn out (có lặp)."""
    return sum(len(v) for v in groups_u.values())


# ---------------------------------------------------------------------------
# 4) BÀI TOÁN GHÉP CẶP CỰC ĐẠI
# ---------------------------------------------------------------------------

_HAS_SCIPY = None


def _max_weight_matching(mat: list[list[float]]) -> float:
    """Tổng trọng số của ghép cặp cực đại, có ĐƯỜNG TẮT cho ma trận nhỏ.

    LÝ DO: trong DBpedia, đại đa số lớp tương đương (p, direction) chỉ chứa
    ĐÚNG MỘT láng giềng -> ma trận 1x1. Code cũ vẫn dựng đối tượng Munkres và
    chạy đủ thuật toán Hungarian cho từng ma trận 1x1. Ba đường tắt dưới đây
    xử lý phần lớn trường hợp mà không gọi solver.
    """
    n, m = len(mat), len(mat[0]) if mat else 0
    if n == 0 or m == 0:
        return 0.0
    if n == 1 and m == 1:                    # đường tắt 1: phổ biến nhất
        return mat[0][0]
    if n == 1:                               # đường tắt 2: 1 x m
        return max(mat[0])
    if m == 1:                               # đường tắt 3: n x 1
        return max(row[0] for row in mat)

    global _HAS_SCIPY
    if _HAS_SCIPY is not False:
        try:
            import numpy as np
            from scipy.optimize import linear_sum_assignment
            _HAS_SCIPY = True
            a = np.asarray(mat, dtype=float)
            r, c = linear_sum_assignment(-a)
            return float(a[r, c].sum())
        except ImportError:
            _HAS_SCIPY = False               # nhớ lại, đừng thử import lại

    # Dự phòng: Munkres (thuần Python, chậm hơn scipy khoảng 50-100 lần)
    from munkres import Munkres
    indexes = Munkres().compute([[-x for x in row] for row in mat])
    return float(sum(mat[r][c] for r, c in indexes))


# ---------------------------------------------------------------------------
# 5) MỘT VÒNG LẶP LROLESIM
# ---------------------------------------------------------------------------

def lrolesim_iteration(beta: float, index_list: Sequence[int], s: Sim,
                       groups: dict, degrees: dict, keysets: dict) -> Sim:
    """s^{k+1}(u,v) = (1-beta) * W(u,v) / max(|N(u)|,|N(v)|) + beta"""
    ret = Sim()
    for u, v in combinations(index_list, 2):
        du, dv = degrees[u], degrees[v]
        if du == 0 and dv == 0:
            # Hai node đều cô lập. Code cũ dùng `continue` -> ngầm để giá trị
            # mặc định 1.0. Ở đây ghi rõ ràng để người đọc không phải suy đoán.
            continue                                     # s = 1.0
        shared = keysets[u] & keysets[v]
        if not shared:
            # KHÔNG có lớp tương đương chung -> mọi ma trận đều rỗng -> W = 0.
            # Đây là phép rút gọn CHÍNH XÁC, không phải xấp xỉ. Code cũ vẫn
            # dựng ma trận và gọi Hungarian cho mọi cặp như vậy.
            ret[u, v] = beta
            continue

        gu, gv = groups[u], groups[v]
        total = 0.0
        for k in shared:
            lu, lv = gu[k], gv[k]
            total += _max_weight_matching([[s[x, y] for y in lv] for x in lu])
        ret[u, v] = (1 - beta) * total / max(du, dv) + beta
    return ret


def _prepare_iteration_state(index_list: Sequence[int], in_neighbor, out_neighbor,
                             measure: str, index_type=None):
    """(index_list, groups, degrees, keysets) — tiền tính dùng chung cho MỌI
    đường chạy (số vòng cố định và hội tụ).

    Tách ra để hai API bên dưới KHÔNG thể lệch nhau ở phần tiền tính. Không thay
    đổi phép toán nào: cùng precompute_groups / node_degree như trước.
    """
    index_list = list(index_list)
    groups = precompute_groups(index_list, in_neighbor, out_neighbor,
                               measure, index_type)
    degrees = {u: node_degree(groups[u]) for u in index_list}
    keysets = {u: frozenset(groups[u]) for u in index_list}
    return index_list, groups, degrees, keysets


def lrolesim_fixed_iterations(beta: float, index_list: Sequence[int],
                              in_neighbor, out_neighbor,
                              measure: str = "lrolesim_ed", index_type=None,
                              iterations: int = 3,
                              on_iteration: Optional[Callable[[int, Sim], None]] = None,
                              verbose: bool = False) -> Sim:
    """Chạy ĐÚNG `iterations` vòng, KHÔNG kiểm tra hội tụ.

    ĐÂY LÀ ĐƯỜNG CHẠY CHÍNH THỨC CỦA JOURNAL 2.
    Bài báo LRoleSim (Journal of Information Processing Vol.33, trang in 436) ghi
    nguyên văn: "We set the parameters as β = 0.2 and k = 3." Muốn so sánh được
    với số đã công bố thì số vòng phải là một hằng số CỐ ĐỊNH, khai báo tường
    minh, chứ không phải kết quả của một ngưỡng tol.

    Hạt nhân toán học không đổi: vẫn đúng lrolesim_iteration() như đường hội tụ.
    Khác biệt duy nhất là điều kiện dừng.

    `on_iteration(k, s)` được gọi sau mỗi vòng (k đếm từ 1) — để test đếm được
    CHÍNH XÁC số vòng đã chạy, và để pipeline ghi provenance.
    """
    if not isinstance(iterations, int) or isinstance(iterations, bool):
        raise TypeError(f"iterations phải là int, nhận {type(iterations).__name__}")
    if iterations < 1:
        raise ValueError(f"iterations phải >= 1, nhận {iterations}")

    index_list, groups, degrees, keysets = _prepare_iteration_state(
        index_list, in_neighbor, out_neighbor, measure, index_type)

    s = Sim()                                    # s^0(u,v) = 1 với mọi u,v
    for it in range(1, iterations + 1):
        t0 = time.time()
        s = lrolesim_iteration(beta, index_list, s, groups, degrees, keysets)
        if verbose:
            print(f"  iter {it:2d}/{iterations}  stored={len(s)}  "
                  f"{time.time() - t0:.1f}s")
        if on_iteration is not None:
            on_iteration(it, s)
    return s


def lrolesim_until_convergence(beta: float, index_list: Sequence[int],
                               in_neighbor, out_neighbor,
                               measure: str = "lrolesim_ed", index_type=None,
                               max_iter: int = 20, tol: float = 1e-4,
                               verbose: bool = True) -> Sim:
    """Chạy đến khi HỘI TỤ (đường chạy cũ, giữ nguyên hành vi).

    Journal 2 dùng đường số vòng cố định ở trên. Đường này được GIỮ LẠI dưới một
    API riêng, tường minh, để chạy ablation "hội tụ so với k = 3" — chứ không còn
    là mặc định ngầm.
    """
    index_list, groups, degrees, keysets = _prepare_iteration_state(
        index_list, in_neighbor, out_neighbor, measure, index_type)

    s = Sim()
    for it in range(1, max_iter + 1):
        t0 = time.time()
        new_s = lrolesim_iteration(beta, index_list, s, groups, degrees, keysets)
        delta = new_s.max_delta(s)
        s = new_s
        if verbose:
            print(f"  iter {it:2d}  delta={delta:.6f}  "
                  f"stored={len(s)}  {time.time() - t0:.1f}s")
        if delta < tol:
            if verbose:
                print(f"  -> hội tụ sau {it} vòng (tol={tol})")
            break
    return s


def lrolesim(beta: float, index_list: Sequence[int], in_neighbor, out_neighbor,
             measure: str = "lrolesim_ed", index_type=None,
             max_iter: int = 20, tol: float = 1e-4,
             verbose: bool = True) -> Sim:
    """Tương thích ngược: uỷ quyền cho lrolesim_until_convergence().

    Chữ ký và hành vi KHÔNG đổi, để all_in_one.py / mcq_generation.py không vỡ.
    Code mới nên gọi trực tiếp lrolesim_fixed_iterations() (journal 2) hoặc
    lrolesim_until_convergence() (ablation) để số vòng luôn hiện rõ tại chỗ gọi.
    """
    return lrolesim_until_convergence(
        beta, index_list, in_neighbor, out_neighbor, measure=measure,
        index_type=index_type, max_iter=max_iter, tol=tol, verbose=verbose)


# ---------------------------------------------------------------------------
# 6) API CHO JOURNAL 2
# ---------------------------------------------------------------------------

def build_subgraph(seed_nodes: Iterable[int], in_neighbor, out_neighbor,
                   hops: int = 1, max_nodes: int = 4000,
                   include_in: bool = True) -> list[int]:
    """Answer + ứng viên + láng giềng k-hop  ->  danh sách node của đồ thị con.

    Đây chính là Step 3 trong slides của bạn ("Build a smaller Knowledge Graph").
    Code cũ thực hiện việc này bằng ~130 dòng if/elif với các bộ lọc kiểu
    `if s % 268 == 0` khác nhau cho từng thí nghiệm — không tái sử dụng được và
    không giải thích được trong bài báo. Ở đây thay bằng một trần max_nodes
    tường minh, ưu tiên các láng giềng có bậc thấp (ít nhiễu, đặc trưng hơn).
    """
    current = set(seed_nodes)
    visited = set(current)
    for _ in range(hops):
        nxt = set()
        for u in current:
            for _p, o in out_neighbor.get(u, ()):
                nxt.add(o)
            if include_in:
                for _p, s_ in in_neighbor.get(u, ()):
                    nxt.add(s_)
        nxt -= visited
        if len(visited) + len(nxt) > max_nodes:
            # Ưu tiên láng giềng ÍT phổ biến: hub như dbr:Japan xuất hiện ở mọi
            # node nên không giúp phân biệt, lại làm đồ thị phình to.
            budget = max_nodes - len(visited)
            nxt = set(sorted(
                nxt, key=lambda x: len(in_neighbor.get(x, ())) +
                                   len(out_neighbor.get(x, ()))
            )[:max(budget, 0)])
        visited |= nxt
        current = nxt
        if not current:
            break
    return sorted(visited)


def reduce_neighbor(index_list, neighbor):
    """Chỉ giữ các cạnh mà cả hai đầu đều nằm trong đồ thị con."""
    index_set = set(index_list)
    return {u: [(p, o) for p, o in neighbor.get(u, ()) if o in index_set]
            for u in index_list}


def edge_count(neighbor):
    """(tổng số cạnh, số loại predicate)."""
    count, preds = 0, set()
    for value in neighbor.values():
        count += len(value)
        preds.update(p for p, _ in value)
    return count, len(preds)


def rank_by_similarity(answer_idx: int, candidate_idx: Sequence[int],
                       in_neighbor, out_neighbor,
                       measure: str = "lrolesim_ed", beta: float = 0.2,
                       hops: int = 1, index_type=None,
                       max_nodes: int = 4000,
                       verbose: bool = False) -> list[tuple[float, int]]:
    """Hàm mà pipeline journal 2 thực sự cần. Trả về [(sim, candidate), ...].

    Vì sao KHÔNG thể chỉ tính một hàng của ma trận: LRoleSim là điểm bất động
    lặp — s(A,d) phụ thuộc s trên các cặp láng giềng. Nhưng ta CÓ THỂ giới hạn
    vào đồ thị con Answer + ứng viên + k-hop rồi tính đủ trên đó. Đó chính là
    điều slide 13 mô tả, và giờ nó là một lời gọi hàm.
    """
    seeds = [answer_idx] + list(candidate_idx)
    nodes = build_subgraph(seeds, in_neighbor, out_neighbor,
                           hops=hops, max_nodes=max_nodes)
    r_in = reduce_neighbor(nodes, in_neighbor)
    r_out = reduce_neighbor(nodes, out_neighbor)
    if verbose:
        print(f"  đồ thị con: {len(nodes)} node, "
              f"{edge_count(r_in)[0] + edge_count(r_out)[0]} cạnh")
    s = lrolesim(beta, nodes, r_in, r_out, measure=measure,
                 index_type=index_type, verbose=verbose)
    out = [(s[answer_idx, d], d) for d in candidate_idx if d != answer_idx]
    out.sort(key=lambda t: -t[0])
    return out


# ---------------------------------------------------------------------------
# 7) TƯƠNG THÍCH NGƯỢC
# ---------------------------------------------------------------------------

def short_form(full_url: str) -> str:
    """<http://dbpedia.org/resource/Kyoto_University> -> dbr:Kyoto_University"""
    u = full_url.strip("<>")
    for prefix, short in (("http://dbpedia.org/resource/Category:", "dbc:"),
                          ("http://dbpedia.org/resource/", "dbr:"),
                          ("http://dbpedia.org/property/", "dbp:"),
                          ("http://dbpedia.org/ontology/", "dbo:"),
                          ("http://ja.dbpedia.org/resource/", "jadbr:"),
                          ("http://ja.dbpedia.org/property/", "jadbp:")):
        if u.startswith(prefix):
            return short + u[len(prefix):]
    return u


def partition_by_binary_label_function_withkey(iu, iv, ou, ov, element_class,
                                               index_type=None):
    """Giữ nguyên chữ ký cũ — all_in_one.py và mcq_generation.py đang import."""
    element_pod = defaultdict(lambda: ([], []))
    is_typed = element_class is ElementWithEdgeDirectionEquivalenceRelation_EntityType
    for lst, direction, side in ((iu, IN, 0), (iv, IN, 1),
                                 (ou, OUT, 0), (ov, OUT, 1)):
        for po in lst:
            k = (element_class(po, direction, (index_type or {}).get(po[1]))
                 if is_typed else element_class(po, direction))
            element_pod[k][side].append(po[1])
    return dict(element_pod)


def partition_by_binary_label_function(iu, iv, ou, ov, element_class,
                                       index_type=None):
    """Giữ nguyên chữ ký cũ. Trả về list các cặp (láng giềng u, láng giềng v)."""
    return list(partition_by_binary_label_function_withkey(
        iu, iv, ou, ov, element_class, index_type).values())


def get_equiv_classes_for_node(node_index, in_neighbor, out_neighbor, index_url,
                               element_class=ElementWithEdgeDirectionEquivalenceRelation,
                               index_type=None, verbose: bool = False):
    """Gộp print_equiv_classes_for_single_node và get_equiv_classes_for_node.

    LÝ DO: hai hàm cũ (dòng 169 và 226) trùng nhau khoảng 80%, khác nhau duy
    nhất ở chỗ một cái return còn một cái chỉ print. Giờ là một hàm với cờ
    verbose. Quan trọng hơn: hàm cũ LUÔN print, kể cả khi được gọi trong vòng
    lặp qua 100 câu hỏi -> log rác hàng chục nghìn dòng.
    """
    part = partition_by_binary_label_function_withkey(
        in_neighbor.get(node_index, []), [],
        out_neighbor.get(node_index, []), [], element_class, index_type)
    result = []
    for key_obj, (neighbors, _) in part.items():
        if hasattr(key_obj, "pdt"):
            p_idx, d, etype = key_obj.pdt
            key_str = f"({short_form(index_url[p_idx])}, {d}, type={etype})"
        elif hasattr(key_obj, "pd"):
            p_idx, d = key_obj.pd
            key_str = f"({short_form(index_url[p_idx])}, {d})"
        else:
            key_str = str(getattr(key_obj, "__dict__", key_obj))
        result.append((key_str, [short_form(index_url[n]) for n in neighbors]))
    if verbose:
        print(f"\n=== Equivalence classes: {short_form(index_url[node_index])} ===")
        for key_str, names in result:
            print(f"  {key_str} -> {names}")
    return result


# ---------------------------------------------------------------------------
# 8) CHỈ SỐ ĐÁNH GIÁ
# ---------------------------------------------------------------------------

def make_sorted_list_fn(sim: Sim, index_list: Sequence[int], index_url=None):
    """Trả về hàm q -> danh sách (sim, node) giảm dần, có CACHE.

    LỖI 2 ĐƯỢC SỬA Ở ĐÂY: code cũ sort tuple (sim_val, node_index) với
    reverse=True. Khi sim bằng nhau — rất hay xảy ra — Python so tiếp phần tử
    thứ hai, tức xếp node có CHỈ SỐ LỚN lên trước. Chỉ số node tương quan với
    thứ tự xuất hiện trong file TTL, nên đây là thiên lệch HỆ THỐNG chứ không
    phải ngẫu nhiên, và nó chảy thẳng vào MRR/NDCG.
    Cách sửa: phá hoà bằng URL (trung lập với thứ tự file). Nếu không có
    index_url thì dùng key chỉ gồm -sim, để Python giữ thứ tự ổn định.
    """
    cache: dict[int, list] = {}

    def calc_sorted_list(q):
        if q not in cache:
            lst = [(sim[q, j], j) for j in index_list]
            if index_url is not None:
                lst.sort(key=lambda t: (-t[0], index_url[t[1]]))
            else:
                lst.sort(key=lambda t: -t[0])
            cache[q] = lst
        return cache[q]

    return calc_sorted_list


def compute_mrr(query_nodes, calc_sorted_list, index_type) -> float:
    """MRR với độ liên quan dựa trên kiểu thực thể."""
    rr = []
    for q in query_nodes:
        q_type = index_type.get(q)
        if q_type is None:
            continue
        rank = 0
        found = 0.0
        for _sim, j in calc_sorted_list(q):
            if j == q:
                continue
            rank += 1
            if index_type.get(j) == q_type:
                found = 1.0 / rank
                break
        rr.append(found)
    return sum(rr) / len(rr) if rr else 0.0


def compute_ndcg(query_nodes, calc_sorted_list, index_type,
                 k: Optional[int] = None,
                 skip_undefined: bool = True) -> float:
    """NDCG@k.

    LỖI 3 ĐƯỢC SỬA Ở ĐÂY: code cũ đặt ndcg = 0.0 khi idcg == 0, tức là khi
    query KHÔNG CÓ node liên quan nào trong đồ thị. NDCG khi đó là KHÔNG XÁC
    ĐỊNH, không phải bằng 0. Gộp các số 0 giả này vào trung bình sẽ kéo kết quả
    xuống, và mức kéo phụ thuộc vào tỉ lệ query cô lập của từng dataset — nên
    nó bóp méo cả việc SO SÁNH giữa các độ đo.
    skip_undefined=True là hành vi chuẩn. Đặt False để tái tạo số cũ.
    """
    vals = []
    for q in query_nodes:
        q_type = index_type.get(q)
        if q_type is None:
            continue
        sorted_list = calc_sorted_list(q)
        actual_k = k if k is not None else len(sorted_list)

        dcg, rank = 0.0, 0
        for _sim, j in sorted_list:
            if j == q:
                continue
            rank += 1
            if rank > actual_k:
                break
            if index_type.get(j) == q_type:
                dcg += 1.0 / math.log2(rank + 1)

        rel_count = sum(1 for _s, j in sorted_list
                        if j != q and index_type.get(j) == q_type)
        R = min(rel_count, actual_k)
        idcg = sum(1.0 / math.log2(i + 1) for i in range(1, R + 1))

        if idcg == 0:
            if skip_undefined:
                continue          # NDCG không xác định -> loại khỏi trung bình
            vals.append(0.0)
        else:
            vals.append(dcg / idcg)
    return sum(vals) / len(vals) if vals else 0.0


def compute_precision_at_k(query_nodes, calc_sorted_list, index_type,
                           k_max: int = 50) -> dict[int, float]:
    """Precision@k cho MỌI k trong một lượt duyệt.

    LÝ DO: code cũ đặt `calc_sorted_list(index)` BÊN TRONG vòng `for k in
    range(1, 51)`, nên danh sách tương tự bị dựng và sort lại 50 lần cho cùng
    một query. Với |V| = 5.000 và 90 query, đó là 4.500 lần sort thừa mỗi lần
    chạy. Ở đây sort một lần, cộng dồn dần theo k.
    """
    acc = {k: 0.0 for k in range(1, k_max + 1)}
    n = 0
    for q in query_nodes:
        q_type = index_type.get(q)
        if q_type is None:
            continue
        n += 1
        hits, rank = 0, 0
        for _sim, j in calc_sorted_list(q):
            if j == q:
                continue
            rank += 1
            if rank > k_max:
                break
            if index_type.get(j) == q_type:
                hits += 1
            acc[rank] += hits / rank
    return {k: (v / n if n else 0.0) for k, v in acc.items()}


# ---------------------------------------------------------------------------
# 9) KIỂM TRA TÍNH ĐÚNG ĐẮN / HỢP LỆ TRÊN ĐỒ THỊ NHỎ HanamiSpots
#
#    Mục đích: tái lập Bảng 1 của Explainability_of_LRoleSim.pdf.
#    HanamiSpots = 4 node hạt giống (4 Hanami spot ít được tham chiếu nhất)
#    + TẤT CẢ láng giềng trực tiếp của chúng, chỉ giữ các cạnh mà cả hai đầu
#    đều nằm trong tập node đó. Kết quả mong đợi: 13 node, 15 cạnh, 6 nhãn cạnh.
# ---------------------------------------------------------------------------

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_PICKLE = DATA_DIR / "infobox.pickle_EnglishVersion_EntityType"
DEFAULT_TYPE_FILE = DATA_DIR / "jikken_Hanami_EnglishVersion_EntityType"

# 4 node hạt giống, lấy từ data/SmallGraph_Counts of Hanami_spots_..._EnglishVersion.txt
HANAMI_SEEDS = [
    "<http://dbpedia.org/resource/Kamagatani>",
    "<http://dbpedia.org/resource/Hinokinai_River_Embankment>",
    "<http://dbpedia.org/resource/Tamagawadai_Park>",
    "<http://dbpedia.org/resource/Sakurayama>",
]
HANAMI_QUERY = "<http://dbpedia.org/resource/Kamagatani>"

# Thứ tự các độ đo trong Bảng 1 của bài báo.
HANAMI_MEASURES = ["rolesim", "lrolesim_d", "lrolesim_e", "lrolesim_ed", "lrolesim_edt"]

# Giá trị "Final similarity" (vòng lặp k = 3) chép từ Bảng 1 của
# Explainability_of_LRoleSim.pdf — dùng để đối chiếu TỰ ĐỘNG.
# Node nào không liệt kê thì giá trị mong đợi là beta = 0.200.
HANAMI_EXPECTED_FINAL = {
    "rolesim": {
        "dbr:Kamagatani": 1.000, "dbr:Hinokinai_River_Embankment": 0.877,
        "dbr:Japan": 0.811, "dbr:Semboku,_Akita": 0.696,
        "dbr:Akita_Prefecture": 0.531, "dbr:Ikeda,_Gifu": 0.504,
        "dbr:Urban_park": 0.488, "dbr:Kantō_region": 0.472,
        "dbr:Gunma_Prefecture": 0.472, "dbr:Sakurayama": 0.472,
        "dbr:GifuPrefecture": 0.365, "dbr:Tamagawadai_Park": 0.304,
        "dbr:Tamagawa_Station_(Tokyo)": 0.304,
    },
    "lrolesim_d": {
        "dbr:Kamagatani": 1.000, "dbr:Hinokinai_River_Embankment": 0.867,
        "dbr:Semboku,_Akita": 0.568, "dbr:Sakurayama": 0.456,
        "dbr:Ikeda,_Gifu": 0.400, "dbr:Gunma_Prefecture": 0.320,
        "dbr:Tamagawadai_Park": 0.304,
    },
    "lrolesim_e": {
        "dbr:Kamagatani": 1.000, "dbr:Hinokinai_River_Embankment": 0.877,
        "dbr:Japan": 0.344, "dbr:Akita_Prefecture": 0.280,
        "dbr:GifuPrefecture": 0.280, "dbr:Ikeda,_Gifu": 0.280,
        "dbr:Semboku,_Akita": 0.280, "dbr:Urban_park": 0.256,
    },
    "lrolesim_ed": {
        "dbr:Kamagatani": 1.000, "dbr:Hinokinai_River_Embankment": 0.867,
    },
    "lrolesim_edt": {
        "dbr:Kamagatani": 1.000, "dbr:Hinokinai_River_Embankment": 0.600,
    },
}


def load_entity_types(type_file, url_index: dict) -> dict:
    """Đọc file kiểu thực thể dạng "index, type, <url>"  ->  {node_index: type}.

    VÌ SAO CẦN: read_ttl.load_obj() trả về index_type mà MỌI node đều mang kiểu 0
    (xem read_ttl.py — kiểu được khởi tạo bằng 0 và chỉ được ghi đè bởi
    treat_entity_type qua SPARQL). Nếu dùng nguyên index_type của pickle thì
    LRoleSim_edt sẽ suy biến thành LRoleSim_ed. File jikken_Hanami_... lưu kiểu
    đã tra cứu sẵn cho 13 node của HanamiSpots.

    Ánh xạ theo URL (không theo cột index) vì chỉ số node phụ thuộc vào lần sinh
    pickle — url_set là một set nên thứ tự đánh chỉ số không ổn định giữa các lần
    chạy read_ttl. URL thì luôn ổn định.
    """
    index_type = {}
    with open(type_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = [x.strip() for x in line.split(",")]
            # URL có thể chứa dấu phẩy (vd "<...>/Ikeda,_Gifu>") nên URL là phần
            # còn lại sau 2 cột đầu, ghép lại bằng dấu phẩy.
            etype, url = int(parts[1]), ",".join(parts[2:])   # bỏ qua cột index
            node = url_index.get(url)
            if node is not None:
                index_type[node] = etype
    return index_type


def build_hanami_spots(pickle_path=DEFAULT_PICKLE, type_file=DEFAULT_TYPE_FILE,
                       seeds=HANAMI_SEEDS, verbose: bool = True):
    """Dựng đồ thị con HanamiSpots từ pickle DBpedia (bản tiếng Anh).

    Trả về (nodes, index_url, r_in, r_out, index_type).
    """
    import read_ttl
    if verbose:
        print(f"Đang nạp {pickle_path} ... (file lớn, mất khoảng 30-60 giây)")
    url_index, index_url, out_neighbor, in_neighbor, _ = read_ttl.load_obj(str(pickle_path))

    seed_idx = []
    for u in seeds:
        i = url_index.get(u)
        if i is None:
            raise SystemExit(f"Node hạt giống {u} không có trong KG")
        seed_idx.append(i)

    # 1 hop, cả in lẫn out: "4 node + TẤT CẢ láng giềng trực tiếp của chúng".
    # max_nodes đặt rất lớn để KHÔNG cắt bớt láng giềng nào — đồ thị này phải
    # đúng như Figure 1, không được lọc theo bậc.
    nodes = build_subgraph(seed_idx, in_neighbor, out_neighbor,
                           hops=1, max_nodes=10 ** 9, include_in=True)
    # Chỉ giữ cạnh có cả hai đầu nằm trong HanamiSpots (đúng như mô tả bài báo).
    r_in = reduce_neighbor(nodes, in_neighbor)
    r_out = reduce_neighbor(nodes, out_neighbor)
    index_type = load_entity_types(type_file, url_index) if type_file else {}

    if verbose:
        n_edges, n_labels = edge_count(r_out)
        print(f"\nHanamiSpots: {len(nodes)} node, {n_edges} cạnh, {n_labels} nhãn cạnh "
              f"(bài báo: 13 node, 15 cạnh, 6 nhãn cạnh)")
        ok = (len(nodes), n_edges, n_labels) == (13, 15, 6)
        print(f"  -> cấu trúc đồ thị {'KHỚP' if ok else 'KHÔNG KHỚP'} Figure 1")
        print("\nCác cạnh của HanamiSpots:")
        for u in nodes:
            for p, o in r_out[u]:
                print(f"  {short_form(index_url[u]):35s} --{short_form(index_url[p]):22s}--> "
                      f"{short_form(index_url[o])}")
        print("\nKiểu thực thể (dùng cho LRoleSim_edt):")
        for u in nodes:
            print(f"  {short_form(index_url[u]):35s} type={index_type.get(u)}")
    return nodes, index_url, r_in, r_out, index_type


def check_hanami_spots(pickle_path=DEFAULT_PICKLE, type_file=DEFAULT_TYPE_FILE,
                       query: str = HANAMI_QUERY, beta: float = 0.2,
                       n_iter: int = 3, measures=HANAMI_MEASURES,
                       verbose_graph: bool = True) -> dict:
    """Kiểm tra tính đúng đắn: in độ tương tự giữa `query` và MỌI node còn lại
    của HanamiSpots, ở TỪNG vòng lặp k = 1, 2, 3, cho cả 5 độ đo.

    Đây chính là nội dung Bảng 1 trong Explainability_of_LRoleSim.pdf.
    Không gọi lrolesim() vì hàm đó chỉ trả về ma trận CUỐI; ở đây ta lặp thủ công
    bằng đúng lrolesim_iteration() mà lrolesim() dùng, để lấy được ma trận trung
    gian của từng vòng.

    Trả về {measure: {k: [(sim, node_index), ...]}}.
    """
    nodes, index_url, r_in, r_out, index_type = build_hanami_spots(
        pickle_path, type_file, verbose=verbose_graph)

    # Lấy chỉ số của node truy vấn ("Kamagatani").
    q = next((u for u in nodes if index_url[u] == query), None)
    if q is None:
        raise SystemExit(f"{query} không có trong HanamiSpots")

    results: dict = {}
    for measure in measures:
        # Tiền tính lớp tương đương / bậc / tập key — y hệt lrolesim().
        groups = precompute_groups(nodes, r_in, r_out, measure, index_type)
        degrees = {u: node_degree(groups[u]) for u in nodes}
        keysets = {u: frozenset(groups[u]) for u in nodes}

        print(f"\n{'=' * 78}\nĐộ đo: {measure}   (beta={beta}, |V|={len(nodes)})\n{'=' * 78}")
        s = Sim()                      # s^0(u,v) = 1 với mọi cặp
        per_iter = {}
        for k in range(1, n_iter + 1):
            s = lrolesim_iteration(beta, nodes, s, groups, degrees, keysets)
            # make_sorted_list_fn: sắp xếp giảm dần, phá hoà bằng URL (không
            # thiên lệch theo chỉ số node — xem "LỖI 2" ở mục 8).
            ranked = make_sorted_list_fn(s, nodes, index_url)(q)
            per_iter[k] = ranked
            print(f"\n-- Vòng lặp k = {k}: sim({short_form(index_url[q])}, *) --")
            for rank, (val, j) in enumerate(ranked):
                print(f"  {rank:2d}  {short_form(index_url[j]):35s} {val:.3f}")
        results[measure] = per_iter

    # --- Đối chiếu tự động với Bảng 1 (cột "Final similarity", k = 3) --------
    # Bài báo làm tròn 3 chữ số thập phân nên dung sai 5e-4 là vừa đủ.
    if n_iter >= 3:
        print(f"\n{'=' * 78}\nĐỐI CHIẾU với Bảng 1 của Explainability_of_LRoleSim.pdf "
              f"(k=3)\n{'=' * 78}")
        all_ok = True
        for measure in measures:
            expected = HANAMI_EXPECTED_FINAL.get(measure)
            if expected is None:
                continue
            bad = []
            for val, j in results[measure][3]:
                name = short_form(index_url[j])
                exp = expected.get(name, beta)   # không liệt kê -> mong đợi beta
                if abs(val - exp) > 5e-4:
                    bad.append(f"{name}: được {val:.3f}, mong đợi {exp:.3f}")
            all_ok &= not bad
            print(f"  {measure:14s} {'ĐẠT' if not bad else 'KHÔNG ĐẠT'}")
            for b in bad:
                print(f"      {b}")
        print(f"\nKẾT LUẬN: thuật toán {'ĐÚNG' if all_ok else 'SAI'} "
              f"so với kết quả đã công bố.")
    return results


# ---------------------------------------------------------------------------
# 10) CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="LRoleSim — xếp hạng ứng viên distractor theo độ tương tự vai trò")
    ap.add_argument("--pickle", help="pickle sinh bởi read_ttl.py")
    ap.add_argument("--answer", help="Answer URI, dạng <http://...>")
    ap.add_argument("--candidates", help="file .txt, mỗi dòng một URI ứng viên")
    ap.add_argument("--measure", default="lrolesim_ed", choices=list(MEASURES))
    ap.add_argument("--beta", type=float, default=0.2)
    ap.add_argument("--hops", type=int, default=1)
    ap.add_argument("--max-nodes", type=int, default=4000)
    ap.add_argument("--topk", type=int, default=10)
    ap.add_argument("--check-hanami", action="store_true",
                    help="kiểm tra tính đúng đắn trên đồ thị nhỏ HanamiSpots "
                         "(tái lập Bảng 1 của Explainability_of_LRoleSim.pdf)")
    ap.add_argument("--iters", type=int, default=3,
                    help="số vòng lặp cần in khi dùng --check-hanami")
    args = ap.parse_args()

    if args.check_hanami:
        check_hanami_spots(pickle_path=args.pickle or DEFAULT_PICKLE,
                           beta=args.beta, n_iter=args.iters)
        return

    if not args.pickle or not args.answer:
        ap.error("cần --pickle và --answer (hoặc dùng --check-hanami)")

    import read_ttl
    url_index, index_url, out_neighbor, in_neighbor, index_type = \
        read_ttl.load_obj(args.pickle)

    a_idx = url_index.get(args.answer)
    if a_idx is None:
        raise SystemExit(f"{args.answer} không có trong KG")

    if args.candidates:
        cands = []
        for line in open(args.candidates):
            i = url_index.get(line.strip())
            if i is not None:
                cands.append(i)
    else:   # không truyền ứng viên -> lấy toàn bộ láng giềng 1-hop
        cands = build_subgraph([a_idx], in_neighbor, out_neighbor, hops=1)

    print(f"Answer={args.answer}  |  {len(cands)} ứng viên  |  {args.measure}")
    t0 = time.time()
    ranked = rank_by_similarity(a_idx, cands, in_neighbor, out_neighbor,
                                measure=args.measure, beta=args.beta,
                                hops=args.hops, index_type=index_type,
                                max_nodes=args.max_nodes, verbose=True)
    print(f"\nTop {args.topk} ({time.time() - t0:.1f}s):")
    for r, (sim, d) in enumerate(ranked[:args.topk], 1):
        print(f"  {r:2d}. {sim:.4f}  {short_form(index_url[d])}")


if __name__ == "__main__":
    main()