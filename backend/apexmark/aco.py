"""
Ant Colony Optimization cho bai toan "chon N trong M khoi" (chon tap con
to hop, khong phai bai toan dinh tuyen/TSP): moi kien xay dung 1 nghiem
bang cach rut n_select ung vien KHONG hoan lai, xac suat chon o moi buoc
ti le voi pheromone_i^alpha * heuristic_i^beta trong so cac ung vien con
lai (cai dat CHINH XAC bang thu thuat Gumbel-top-k). Sau moi vong lap,
pheromone bay hoi toan cuc va duoc tang cuong tren cac khoi ma kien TOT
NHAT cua vong lap da dung (elitist update).

GHI CHU HIEU NANG: viec rut n_select khoi tuan tu cua moi kien duoc cai
dat bang thu thuat Gumbel-top-k thay vi vong lap Python rut ti le tung
buoc. Day la tuong duong chinh xac da biet (Vieira 2014 / Efraimidis-
Spirakis weighted reservoir sampling), bien O(n_select x n_candidates)
moi kien thanh O(n_candidates log n_candidates) -- giup ACO kha thi ve
toc do tren benchmark 18 anh x nhieu tan cong.
"""
from __future__ import annotations

import numpy as np


def _gumbel_topk_sample(desirability: np.ndarray, n_select: int, rng: np.random.RandomState) -> np.ndarray:
    log_w = np.log(desirability + 1e-12)
    u = rng.random_sample(desirability.shape)
    gumbel_noise = -np.log(-np.log(np.clip(u, 1e-12, 1 - 1e-12)))
    perturbed = log_w + gumbel_noise
    idx = np.argpartition(-perturbed, n_select - 1)[:n_select]
    return idx[np.argsort(-perturbed[idx])]


def aco_select_blocks(n_candidates: int, n_select: int, heuristic: np.ndarray,
                       n_ants: int = 20, n_iters: int = 15,
                       alpha: float = 1.0, beta: float = 2.0,
                       evap_rate: float = 0.15, q_deposit: float = 1.0,
                       rng_seed: int = 0, verbose: bool = False):
    """Tra ve (best_indices: np.ndarray do dai n_select, history: list
    best fitness moi vong lap)."""
    rng = np.random.RandomState(rng_seed)
    pheromone = np.ones(n_candidates)
    eta = heuristic ** beta

    best_indices_global = None
    best_fitness_global = -np.inf
    history = []

    for it in range(n_iters):
        desirability = (pheromone ** alpha) * eta

        iter_best_indices = None
        iter_best_fitness = -np.inf

        for ant in range(n_ants):
            chosen = _gumbel_topk_sample(desirability, n_select, rng)
            fitness = float(heuristic[chosen].sum())
            if fitness > iter_best_fitness:
                iter_best_fitness = fitness
                iter_best_indices = chosen

        pheromone *= (1 - evap_rate)
        pheromone[iter_best_indices] += q_deposit

        if iter_best_fitness > best_fitness_global:
            best_fitness_global = iter_best_fitness
            best_indices_global = iter_best_indices.copy()

        history.append(best_fitness_global)
        if verbose:
            print(f"  iter {it+1:3d}/{n_iters}  best_fitness={best_fitness_global:.4f}")

    return best_indices_global, history


def greedy_top_n_blocks(n_select: int, heuristic: np.ndarray) -> np.ndarray:
    """Kiem tra doi chieu: lay don gian top-N khoi theo heuristic."""
    return np.argsort(heuristic)[::-1][:n_select]
