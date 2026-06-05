# ACE Fe-O Examples 시뮬레이션 요약

## 개요
Bienvenu et al. (2025) 논문의 ACE Fe-O 포텐셜 예제 스크립트.
Fe3O4 (magnetite) 벌크 구조에 대한 MD 및 spin equilibration.

---

## 1. `regular_MD/run_md.lammps` (일반 MD)

| 항목 | 설정 |
|------|------|
| **힘장** | ACE (`ACE_Fe-O.yace`), pair_style pace |
| **단위계** | metal |
| **atom_style** | atomic |
| **주기성** | p p p (전방향 주기적) |
| **시스템** | Fe3O4 magnetite (`POSCAR_Fe3O4_FeM.lmp`), 2x2x2 supercell |
| **온도** | 1200 K |
| **압력** | 10 bar (NPT aniso) |
| **timestep** | 0.001 ps = 1 fs |

### 시뮬레이션 단계
| 단계 | 설명 | 스텝 수 | 앙상블 |
|------|------|---------|--------|
| 온도 평형화 | NVT @ 1200 K | 100 | NVT |
| 생산 MD | NPT @ 1200 K, 10 bar | 2,000 | NPT (aniso) |
| 구조 최적화 | box/relax + CG minimize | - | 정적 |

### 출력
- thermo/dump 간격: 10 steps
- 최종 relaxation: aniso 0.0 bar, vmax 0.001

---

## 2. `spin_equilibration_MD/run_spin_eq_md.lammps` (MC-MD 하이브리드)

| 항목 | 설정 |
|------|------|
| **힘장** | ACE (`ACE_Fe-O.yace`), pair_style pace |
| **단위계** | metal |
| **atom_style** | atomic |
| **주기성** | p p p |
| **시스템** | Fe3O4 magnetite, 2x2x2 supercell (448 atoms) |
| **온도** | 1200 K |
| **압력** | 0 bar (NPT aniso) |
| **timestep** | 0.001 ps = 1 fs |

### MC Spin Equilibration
- `fix atom/swap`: 10 MD steps마다 100회 swap 시도
- semi-grand, types 1 2 (Fe-up <-> Fe-down)
- mu 0.0 0.0 (화학 퍼텐셜 차이 = 0)
- iron group: type 1 & 2

### 시뮬레이션 단계
| 단계 | 설명 | 스텝 수 | 앙상블 |
|------|------|---------|--------|
| Phase 1 | NVT 사전 평형화 | 2,000 | NVT |
| Phase 2 | MC spin 설정 | - | - |
| Phase 3 | NPT 생산 MD + spin eq | 50,000 | NPT (aniso) |
| Phase 4 | 구조 최적화 | - | 정적 |

### 모니터링
- Fe-up/Fe-down 개수 실시간 추적 (`v_n_up`, `v_n_down`)

### 출력
- thermo 간격: 100 steps
- dump 간격: 100 steps

### 비고
- Bienvenu et al. 논문의 공식 예제
- MC-MD 하이브리드: MD 도중 자기 자유도를 열역학적 평형으로 유도
