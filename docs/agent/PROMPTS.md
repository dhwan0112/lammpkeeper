# Cursor 프롬프트 모음 (LammpKeeper)

Cursor CLI에 그대로 붙여 넣어 쓰는 프롬프트입니다. `<…>` 부분만 바꾸면 됩니다.
모든 프롬프트는 `AGENTS.md`와 `.cursor/rules/`를 전제로 하므로, 그 내용을 프롬프트에서 다시 설명하지 않습니다.
권장 실행 방식: 작업마다 새 worktree를 만듭니다 (`agent -w <id>`).

---

## P0. 첫 세션 — 이해도 점검 (읽기 전용)

`agent --mode=ask`로 시작합니다.

```
AGENTS.md, MIGRATION.md, docs/adr/0001-general-purpose-architecture.md, docs/agent/BACKLOG.md를 읽어줘.
그 다음 아래를 보고만 해줘. 파일은 수정하지 마.
1) 이 저장소의 목표와 현재 상태를 5줄로 요약
2) 지침 문서와 실제 코드가 어긋나는 부분 (파일:라인 포함)
3) BACKLOG Phase 1 순서에서 의존성상 문제가 있으면 지적
4) 각 주장에 measured / inferred / guessed 표시
```

## P1. ADR-0001 검토 — 결정은 사람이 함

```
/architect docs/adr/0001-general-purpose-architecture.md를 검토해줘.
- 제안된 레이어 경계가 현재 코드(lammps_pre/, lammps_post/, lammpkeeper/)에 어떻게 대응하는지 표로 정리
- "Open questions" 1~5 각각에 대해 선택지 2~3개와 trade-off 제시 (재현성 / 범용성 / 하위호환 관점)
- 빠졌거나 과한 결정이 있으면 지적
ADR 상태는 proposed로 유지. 수정 제안은 diff로만 보여주고 커밋하지 마.
```

필요하면 이어서 `/interrogate`로 다른 모델 계열의 의견을 받으십시오.

## P2. Bug fix — BACKLOG 항목 1건

```
/poteto-mode docs/agent/BACKLOG.md의 <MSD 항목(PHYS-2 + PHYS-1)>을 처리해줘. 기준 브랜치: <main>.
- 커밋 순서는 BACKLOG에 적힌 대로 (PHYS-2 → PHYS-1 → golden 재설정)
- 재현: tests/pending_review_findings.py의 해당 테스트를 수집되는 test_*.py 모듈로 옮기고, 실패하는 출력을 먼저 보여줘
- 수정은 범용 형태로: 종(species)은 타입 집합(set), 주기 경계는 pbc=(bool,bool,bool). Fe 전용 땜질 금지
- golden 값이 바뀌면 별도 test(golden) 커밋으로 분리하고, 커밋 전에 나에게 승인 요청
done when: BACKLOG의 "Done when" 충족 + /verify-lkpr full PASS + /blast-radius 결과 첨부
```

## P3. HPC job script 안전성 (HPC-1)

```
/poteto-mode BACKLOG HPC-1을 처리해줘. .cursor/rules/hpc-job-scripts.mdc를 따를 것.
- 생성된 run.sh를 임시 디렉터리에서 stub mpirun / cp로 실행하는 테스트를 먼저 작성
  (사례: 복사 성공 / 복사 실패 / scratch 진입 실패)
- LAMMPS 입력 파일이나 물리 설정은 건드리지 마. 스크립트의 안전 로직만 수정
done when: 세 사례 모두 기대한 종료 코드·scratch 보존 여부 일치 + bash -n 통과 + /verify-lkpr full PASS
```

## P4. golden 재설정 (TEST-2) — 사람 승인 필수

```
/poteto-mode BACKLOG TEST-2: <PHYS-1, PHYS-2> 수정으로 바뀐 golden을 재설정하려 해.
키마다 다음 표를 먼저 보여주고, 내가 승인하기 전에는 커밋하지 마:
| key | old 요약값 | new 요약값 | 물리적 이유 | 독립 검증 방법과 결과 |
독립 검증은 brute-force 또는 해석해가 있는 합성 계(synthetic case)로 할 것. 기존 golden 해시를 그대로 맞추는 방향은 금지.
```

## P5. 범용화 단계 (GEN 항목)

```
/poteto-mode docs/agent/BACKLOG.md의 <GEN-1>을 진행해줘. 전제: ADR-0001이 accepted 상태.
순서:
1) /architect로 공개 API(클래스·함수 시그니처, 모듈 위치) 제안 → 나에게 승인 요청 후 대기
2) strangler 방식: 새 경로 추가 → 호출부를 하나씩 이전 → 기존 경로는 shim으로 유지
3) 임의 라벨("A","B") 테스트 + Fe-O golden 불변 증명
done when: BACKLOG "Done when" 충족, Fe-O golden 변화 없음, /verify-lkpr full PASS, /interrogate 결과 중 "act on" 항목 처리 완료
```

## P6. 두 번째 기준 계 (GEN-8)

```
/poteto-mode BACKLOG GEN-8. 기준 계는 <계 이름, 예: LJ argon 액체 / 다른 계>로 정했어.
- 작은 fixture(원자 500개 이하, 프레임 50개 이하)를 만드는 스크립트를 먼저 작성. 실제 LAMMPS 실행은 내가 직접 해서 결과를 넣을게
- 해답이 알려진 behavior 테스트를 설계 (RDF 첫 피크 위치, MSD 영역, 분자 수 등)
- 지금 코드에서 Fe/O를 가정해서 실패하는 지점을 목록으로 정리
fixture 추가는 사람 승인 사항이니, 파일 목록과 크기를 보여주고 대기.
```

## P7. 숫자가 이상할 때 (조사)

```
/poteto-mode investigation (읽기 전용): <analyze msd 결과에서 Fe MSD가 17 Å²로 나옴. 1200 K 결정 고체치고는 너무 큼>.
원칙 explain-the-number, prove-it-works를 적용해서:
- 원인 가설을 세우고, 각각을 확인하는 최소 실험 (synthetic 또는 fixture 일부)
- 원인을 확정하면 BACKLOG 항목 초안을 작성해줘 (위치, 근거, 수정 방향, Done when)
코드 수정은 하지 마.
```

## P8. 세션 재개

```
/poteto-mode session pickup: 브랜치 <gen/GEN-1-species-map> 작업을 이어서 진행.
git log, BACKLOG 상태, 열린 PR을 읽고 남은 단계를 task list로 복원해줘. 진행 전에 요약을 보여줘.
```

## P9. 정기 유지보수

```
/maintain-verification-skill verify-lkpr
```
```
/reflect 이번 세션에서 반복된 실수와 교훈을 정리해줘.
AGENTS.md나 .cursor/rules 변경 제안은 diff로만 보여주고 적용하지 마.
우선순위: 코드·테스트로 고정 > scoped rule > AGENTS.md.
```

## P10. 무인 빠른 점검 (헤드리스)

```bash
agent -p "/verify-lkpr quick 실행하고 summary.txt 내용만 그대로 출력해줘. 파일 수정 금지." --output-format text
```

헤드리스 모드에서는 쓰기 권한이 전부 열려 있습니다. 검증 같은 읽기 위주 작업에만 쓰십시오.

## P11. 완료된 브랜치 마무리 — push와 PR

```
브랜치 <fix/test-1-skip-reporting>의 작업을 마무리해줘. 기준 브랜치: main.
1) git diff main...HEAD를 요약하고, 커밋 메시지가 BACKLOG ID와 결과 수치를 담고 있는지 확인
2) /verify-lkpr full 실행, summary.txt를 그대로 인용 (SKIP 항목 포함)
3) 리뷰 메모가 BACKLOG 항목에 있으면 먼저 반영 (별도 커밋)
4) git push -u origin <브랜치> 후 gh pr create (ready-for-review, draft 아님). PR 본문: 목적, 재현 → 수정 결과, 검증 증거, BACKLOG ID
merge는 하지 마. PR URL만 보고해줘.
```

## P12. OPS-1 — 히스토리 파일 무한 증가

```
/poteto-mode docs/agent/BACKLOG.md의 OPS-1을 처리해줘. 기준 브랜치: main.
- 대상: lammpkeeper/shell.py, lammpkeeper/common/hosted.py (세 개의 히스토리 파일 모두)
- 재현 테스트 먼저: 임시 HOME에 5,000줄짜리 히스토리를 만들고 셸을 시작·종료한 뒤 줄 수가 2,000 이하인지 확인. LKPR_NO_HISTORY=1이면 HOME에 파일이 생기지 않는지도 확인
- ~/ 아래의 기존 대용량 히스토리 파일은 건드리지 마 (내가 직접 정리할 것)
done when: BACKLOG "Done when" 충족 + /verify-lkpr quick PASS
```

## P13. 지침 파일을 저장소에 커밋 (한 번만)

```
현재 untracked인 에이전트 지침 파일을 main 기준 브랜치 docs/agent-kit에 커밋해줘.
- 대상: AGENTS.md, .cursor/, docs/agent/, docs/adr/, tests/pending_review_findings.py, CHANGELOG.md, docs/reproducibility.md
- 제외: "Claude outputs/" (삭제 대상, 건드리지 마), .pytest_cache/
- 먼저 git status --short로 목록을 보여주고, 위 목록과 다르면 멈추고 물어봐
- 커밋 메시지: "docs: agent instructions, backlog, ADR-0001 draft, verify-lkpr skill, REL-0 draft"
- git push -u origin docs/agent-kit 후 gh pr create (ready-for-review). merge는 하지 마.
코드 파일은 한 줄도 바꾸지 마.
```
