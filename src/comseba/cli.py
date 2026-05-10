"""InteractiveCLI — orchestrates all modules with step-by-step prompts.

Resume 가능하도록 설계: 각 스텝의 결과물을 즉시 디스크에 저장하고
session.json 의 `completed_steps` 에 기록한다. 재개 시 완료된 스텝은
디스크에서 로드만 하고 LLM 을 다시 호출하지 않는다.

questionary 호출은 `_io` 모듈에 격리해 테스트에서 mock 가능하도록 분리.
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import questionary

from comseba.criteria_extractor import (
    Criterion,
    EvaluationCriteriaExtractor,
)
from comseba.model_answer_generator import ModelAnswerGenerator
from comseba.profile_builder import StudentProfile, StudentProfileBuilder
from comseba.report_generator import ReportGenerator
from comseba.sms_generator import SmsContentGenerator
from comseba.storage import LocalStorage
from comseba.subject import SUBJECT_PRESETS, Subject
from comseba.submission_evaluator import (
    CriterionFeedback,
    SubmissionEvaluator,
)
from comseba.suggestion_engine import (
    AssessmentIdea,
    AssessmentSuggestionEngine,
)

# 각 스텝에 부여한 이름 — session.json 의 completed_steps 에 기록되는 키.
STEP_PROFILE = "profile"
STEP_SUBJECT = "subject"
STEP_CRITERIA = "criteria"
STEP_SUGGESTIONS = "suggestions"
STEP_EVALUATION = "evaluation"
STEP_MODEL_ANSWER = "model_answer"
STEP_REPORT = "report"
STEP_SMS = "sms"


@dataclass
class _Modules:
    """Bag of module instances — constructed once, injected for tests."""

    profile_builder: StudentProfileBuilder
    criteria_extractor: EvaluationCriteriaExtractor
    suggestion_engine: AssessmentSuggestionEngine
    submission_evaluator: SubmissionEvaluator
    model_answer_generator: ModelAnswerGenerator
    report_generator: ReportGenerator
    sms_generator: SmsContentGenerator


@dataclass
class _SessionContext:
    """All state that flows between steps within one session."""

    storage: LocalStorage
    session_path: Path
    student_name: str
    completed: set[str] = field(default_factory=set)

    profile: StudentProfile | None = None
    profile_updated_at: str | None = None  # ISO 시각, session.json 영속화
    profile_action: str | None = None      # "reused" / "updated" / "rebuilt" / "created"
    subject: Subject | None = None
    criteria: list[Criterion] | None = None
    suggestions: list[AssessmentIdea] = field(default_factory=list)
    evaluation: list[CriterionFeedback] | None = None
    model_answer: str | None = None
    assessment_name: str | None = None

    def mark(self, step: str) -> None:
        if step in self.completed:
            return
        self.completed.add(step)
        self.storage.mark_step_completed(self.session_path, step)


# ---------------------------------------------------------------------------
# IO layer — questionary calls. Tests substitute this whole module-level shim.
# ---------------------------------------------------------------------------


def _ask_text(message: str, default: str = "") -> str:
    answer = questionary.text(message, default=default).ask()
    if answer is None:  # Ctrl-C
        raise KeyboardInterrupt
    return answer


def _ask_multiline(message: str) -> str:
    print(message + " (입력을 마치려면 빈 줄에서 Ctrl-D)")
    lines = sys.stdin.read()
    return lines


def _ask_path_list(message: str) -> list[Path]:
    raw = _ask_text(f"{message} (쉼표로 여러 개, 비우면 건너뜀)", default="")
    if not raw.strip():
        return []
    return [Path(p.strip()).expanduser() for p in raw.split(",") if p.strip()]


def _ask_confirm(message: str, default: bool = True) -> bool:
    answer = questionary.confirm(message, default=default).ask()
    if answer is None:
        raise KeyboardInterrupt
    return bool(answer)


def _ask_select(message: str, choices: list[str]) -> str:
    answer = questionary.select(message, choices=choices).ask()
    if answer is None:
        raise KeyboardInterrupt
    return str(answer)


_CAREER_SOURCE_TEXT = "직접 텍스트 입력"
_CAREER_SOURCE_HWP = "HWP / HWPX 파일 업로드"
_CAREER_SOURCE_MIXED = "혼합 (텍스트 + HWP 파일)"
_HWP_SUFFIXES = {".hwp", ".hwpx"}


def _ask_career_inputs() -> tuple[str | None, list[Path], str]:
    """Ask for the student's career info via one of three modes.

    Returns:
        (career_text, hwp_paths, source_label) where source_label is one of
        "text" / "hwp" / "mixed" — persisted to session.json so reports / future
        sessions know how the input was supplied.
    """
    choice = _ask_select(
        "학생 진로 정보를 어떻게 입력하시겠어요?",
        [_CAREER_SOURCE_TEXT, _CAREER_SOURCE_HWP, _CAREER_SOURCE_MIXED],
    )
    if choice == _CAREER_SOURCE_TEXT:
        return _ask_text("학생의 진로 / 목표를 적어주세요"), [], "text"

    if choice == _CAREER_SOURCE_HWP:
        paths = _filter_hwp_paths(_ask_path_list("HWP / HWPX 파일 경로"))
        if not paths:
            print("HWP / HWPX 파일이 필요합니다. 텍스트로 다시 시도해주세요.")
            return _ask_text("학생의 진로 / 목표를 적어주세요"), [], "text"
        return None, paths, "hwp"

    # mixed
    text = _ask_text("학생의 진로 / 목표를 적어주세요 (HWP 와 합쳐져 분석됩니다)")
    paths = _filter_hwp_paths(_ask_path_list("HWP / HWPX 파일 경로"))
    return text, paths, "mixed"


def _filter_hwp_paths(paths: list[Path]) -> list[Path]:
    """Drop paths whose extension isn't .hwp / .hwpx so HwpParser doesn't see
    them and raise — caller can supply more files if needed."""
    kept: list[Path] = []
    for p in paths:
        if p.suffix.lower() in _HWP_SUFFIXES:
            kept.append(p)
        else:
            print(f"  (무시) HWP/HWPX 가 아닙니다: {p}")
    return kept


_SUBJECT_CUSTOM_LABEL = "직접 입력"


def _ask_subject() -> Subject:
    """Ask the teacher for the subject of this assessment.

    Seven presets + free-text fallback. Returns a `Subject` value.
    """
    choices = list(SUBJECT_PRESETS) + [_SUBJECT_CUSTOM_LABEL]
    choice = _ask_select("어떤 과목의 수행평가인가요?", choices)
    if choice == _SUBJECT_CUSTOM_LABEL:
        custom = _ask_text("과목명을 입력하세요").strip()
        return Subject.custom(custom)
    return Subject.preset(choice)


# ---------------------------------------------------------------------------
# Pipeline — pure orchestration, no questionary calls. Tests drive this directly.
# ---------------------------------------------------------------------------


class Pipeline:
    """Runs the 7 LLM-driven steps over a session, with resume support.

    The CLI shell handles all questionary I/O and constructs the session
    context. This class only orchestrates the modules and persists state.
    """

    def __init__(self, modules: _Modules) -> None:
        self._m = modules

    def run_profile(
        self,
        ctx: _SessionContext,
        career_text: str | None = None,
        kakao_paths: list[Path] | None = None,
        career_hwp_paths: list[Path] | None = None,
        career_source: str = "text",
        force_rebuild: bool = False,
        now: datetime | None = None,
    ) -> StudentProfile:
        """Build (or reuse) the student-level profile.

        Behaviour matrix:
        - already loaded for this session → return as-is.
        - force_rebuild=False AND student profile exists on disk → load it,
          mark step done, no LLM call (action: 'reused').
        - force_rebuild=True OR no student profile on disk → call LLM,
          archive previous (if any) into profile_history/, write new
          students/{name}/profile.json (action: 'updated' or 'created').
        """
        if STEP_PROFILE in ctx.completed and ctx.profile is not None:
            return ctx.profile

        storage = ctx.storage
        had_existing = storage.has_profile(ctx.student_name)

        if not force_rebuild and had_existing:
            data = storage.load_profile(ctx.student_name)
            ctx.profile = _profile_from_dict(data)
            ctx.profile_updated_at = data.get("updated_at")
            ctx.profile_action = "reused"
            self._record_profile_session_meta(ctx)
            ctx.mark(STEP_PROFILE)
            return ctx.profile

        profile = self._m.profile_builder.build(
            ctx.student_name,
            career_text=career_text,
            kakao_image_paths=(kakao_paths or None),
            career_hwp_paths=(career_hwp_paths or None),
        )
        stamp = (now or datetime.now()).strftime("%Y-%m-%dT%H:%M:%S")
        payload = {
            **_profile_to_dict(profile),
            "career_source": career_source,
            "updated_at": stamp,
        }
        storage.save_profile(
            ctx.student_name, payload, archive_previous=had_existing, now=now
        )
        ctx.profile = profile
        ctx.profile_updated_at = stamp
        ctx.profile_action = "updated" if had_existing else "created"
        self._record_profile_session_meta(ctx)
        ctx.mark(STEP_PROFILE)
        return profile

    @staticmethod
    def _record_profile_session_meta(ctx: _SessionContext) -> None:
        """Persist profile_updated_at + profile_action into session.json so
        sessions remain reproducible (we know exactly which profile snapshot
        each session ran against)."""
        state = ctx.storage.load_session_state(ctx.session_path)
        state["profile_updated_at"] = ctx.profile_updated_at
        state["profile_action"] = ctx.profile_action
        ctx.storage.save_json(ctx.session_path, "session.json", state)

    def run_subject(
        self, ctx: _SessionContext, subject: Subject
    ) -> Subject:
        """Persist the chosen subject. Pure metadata step — no LLM call."""
        if STEP_SUBJECT in ctx.completed and ctx.subject is not None:
            return ctx.subject
        ctx.subject = subject
        # session.json 에 직렬화 형태로 저장 → 재개 시 복원.
        state = ctx.storage.load_session_state(ctx.session_path)
        state["subject"] = subject.to_dict()
        ctx.storage.save_json(ctx.session_path, "session.json", state)
        ctx.mark(STEP_SUBJECT)
        return subject

    def run_criteria(
        self, ctx: _SessionContext, image_paths: list[Path]
    ) -> list[Criterion]:
        if STEP_CRITERIA in ctx.completed and ctx.criteria is not None:
            return ctx.criteria
        criteria = self._m.criteria_extractor.extract(
            image_paths, subject=ctx.subject
        )
        ctx.criteria = criteria
        ctx.storage.save_json(
            ctx.session_path,
            "rubric.json",
            {"criteria": EvaluationCriteriaExtractor.to_dict_list(criteria)},
        )
        ctx.mark(STEP_CRITERIA)
        return criteria

    def run_suggestions(
        self,
        ctx: _SessionContext,
        skip: bool,
        count: int = 4,
    ) -> list[AssessmentIdea]:
        if STEP_SUGGESTIONS in ctx.completed:
            return ctx.suggestions
        if skip:
            ctx.suggestions = []
        else:
            assert ctx.profile is not None and ctx.criteria is not None
            ctx.suggestions = self._m.suggestion_engine.suggest(
                ctx.profile, ctx.criteria, count=count, subject=ctx.subject
            )
        ctx.storage.save_json(
            ctx.session_path,
            "suggestions.json",
            {"ideas": [asdict(i) for i in ctx.suggestions]},
        )
        ctx.mark(STEP_SUGGESTIONS)
        return ctx.suggestions

    def run_evaluation(
        self,
        ctx: _SessionContext,
        submission_text: str | None,
        image_paths: list[Path],
        pdf_paths: list[Path],
    ) -> list[CriterionFeedback]:
        if STEP_EVALUATION in ctx.completed and ctx.evaluation is not None:
            return ctx.evaluation
        assert ctx.criteria is not None
        evaluation = self._m.submission_evaluator.evaluate(
            ctx.criteria,
            submission_text=submission_text,
            submission_image_paths=image_paths or None,
            submission_pdf_paths=pdf_paths or None,
            subject=ctx.subject,
        )
        ctx.evaluation = evaluation
        ctx.storage.save_json(
            ctx.session_path,
            "evaluation.json",
            {"feedback": [asdict(f) for f in evaluation]},
        )
        ctx.mark(STEP_EVALUATION)
        return evaluation

    def run_model_answer(self, ctx: _SessionContext) -> str:
        if STEP_MODEL_ANSWER in ctx.completed and ctx.model_answer is not None:
            return ctx.model_answer
        assert ctx.profile is not None and ctx.criteria is not None
        ctx.model_answer = self._m.model_answer_generator.generate(
            ctx.criteria,
            ctx.profile,
            evaluation=ctx.evaluation,
            subject=ctx.subject,
        )
        ctx.storage.save_text(ctx.session_path, "model_answer.txt", ctx.model_answer)
        ctx.mark(STEP_MODEL_ANSWER)
        return ctx.model_answer

    def run_report(self, ctx: _SessionContext) -> str:
        if STEP_REPORT in ctx.completed:
            return ctx.storage.load_text(ctx.session_path, "report.md")
        assert (
            ctx.profile is not None
            and ctx.criteria is not None
            and ctx.evaluation is not None
            and ctx.model_answer is not None
        )
        report = self._m.report_generator.generate(
            ctx.profile,
            ctx.criteria,
            ctx.evaluation,
            ctx.model_answer,
            profile_updated_at=ctx.profile_updated_at,
            subject=ctx.subject,
        )
        ctx.storage.save_text(ctx.session_path, "report.md", report)
        ctx.mark(STEP_REPORT)
        return report

    def run_sms(self, ctx: _SessionContext, assessment_name: str) -> str:
        if STEP_SMS in ctx.completed:
            return ctx.storage.load_text(ctx.session_path, "sms.txt")
        assert ctx.profile is not None and ctx.evaluation is not None
        ctx.assessment_name = assessment_name
        sms = self._m.sms_generator.generate(
            ctx.profile,
            ctx.evaluation,
            assessment_name=assessment_name,
            subject=ctx.subject,
        )
        ctx.storage.save_text(ctx.session_path, "sms.txt", sms)
        ctx.mark(STEP_SMS)
        return sms


# ---------------------------------------------------------------------------
# Serialization helpers — keep dataclasses in code, dicts on disk.
# ---------------------------------------------------------------------------


def _profile_to_dict(profile: StudentProfile) -> dict:
    return asdict(profile)


def _profile_from_dict(data: dict) -> StudentProfile:
    return StudentProfile(
        name=data["name"],
        career_goal=data["career_goal"],
        inferred_needs=list(data.get("inferred_needs") or []),
        communication_style=data.get("communication_style"),
    )


def _criteria_from_dict(data: dict) -> list[Criterion]:
    return [
        Criterion(
            name=c["name"],
            description=c["description"],
            max_score=c.get("max_score"),
        )
        for c in data["criteria"]
    ]


def _suggestions_from_dict(data: dict) -> list[AssessmentIdea]:
    return [
        AssessmentIdea(
            title=i["title"], description=i["description"], rationale=i["rationale"]
        )
        for i in data.get("ideas", [])
    ]


def _evaluation_from_dict(data: dict) -> list[CriterionFeedback]:
    return [
        CriterionFeedback(
            criterion=f["criterion"], feedback=f["feedback"], met=f["met"]
        )
        for f in data["feedback"]
    ]


def _restore_state(ctx: _SessionContext) -> None:
    """Rehydrate dataclass state from disk for any already-completed step."""
    sp = ctx.session_path
    if STEP_PROFILE in ctx.completed:
        # 학생 단위 프로필이 source of truth. 구 세션의 세션 안 profile.json 은
        # _run() 진입 시 마이그레이션이 학생 레벨로 끌어올렸을 것.
        if ctx.storage.has_profile(ctx.student_name):
            data = ctx.storage.load_profile(ctx.student_name)
            ctx.profile = _profile_from_dict(data)
        else:
            # 마이그레이션이 실패한 매우 구 세션 — 호환을 위해 세션 디렉토리 fallback.
            ctx.profile = _profile_from_dict(ctx.storage.load_json(sp, "profile.json"))
        state = ctx.storage.load_session_state(sp)
        ctx.profile_updated_at = state.get("profile_updated_at")
        ctx.profile_action = state.get("profile_action")
    if STEP_SUBJECT in ctx.completed:
        state = ctx.storage.load_session_state(sp)
        subject_data = state.get("subject")
        if subject_data:
            ctx.subject = Subject.from_dict(subject_data)
    if STEP_CRITERIA in ctx.completed:
        ctx.criteria = _criteria_from_dict(ctx.storage.load_json(sp, "rubric.json"))
    if STEP_SUGGESTIONS in ctx.completed:
        ctx.suggestions = _suggestions_from_dict(
            ctx.storage.load_json(sp, "suggestions.json")
        )
    if STEP_EVALUATION in ctx.completed:
        ctx.evaluation = _evaluation_from_dict(
            ctx.storage.load_json(sp, "evaluation.json")
        )
    if STEP_MODEL_ANSWER in ctx.completed:
        ctx.model_answer = ctx.storage.load_text(sp, "model_answer.txt")


# ---------------------------------------------------------------------------
# Top-level CLI loop — questionary prompts wired into Pipeline.
# ---------------------------------------------------------------------------


def _build_modules() -> _Modules:
    return _Modules(
        profile_builder=StudentProfileBuilder(),
        criteria_extractor=EvaluationCriteriaExtractor(),
        suggestion_engine=AssessmentSuggestionEngine(),
        submission_evaluator=SubmissionEvaluator(),
        model_answer_generator=ModelAnswerGenerator(),
        report_generator=ReportGenerator(),
        sms_generator=SmsContentGenerator(),
    )


def _open_or_create_session(storage: LocalStorage, student_name: str) -> _SessionContext:
    existing = storage.list_sessions(student_name)
    if existing:
        choices = ["새 세션 시작"] + [s.name for s in existing]
        choice = _ask_select("어떤 세션으로 진행할까요?", choices)
        if choice != "새 세션 시작":
            session_path = next(s for s in existing if s.name == choice)
            state = storage.load_session_state(session_path)
            ctx = _SessionContext(
                storage=storage,
                session_path=session_path,
                student_name=student_name,
                completed=set(state.get("completed_steps") or []),
            )
            _restore_state(ctx)
            return ctx

    session_path = storage.new_session(student_name)
    return _SessionContext(
        storage=storage, session_path=session_path, student_name=student_name
    )


_PROFILE_REUSE = "그대로 사용"
_PROFILE_UPDATE = "업데이트 (새 진로 정보 입력 → 기존은 history 로 보존)"
_PROFILE_REBUILD = "처음부터 다시 만들기 (기존을 history 로 보존)"


def _summarize_profile(data: dict) -> str:
    needs = ", ".join(data.get("inferred_needs") or []) or "(없음)"
    updated = data.get("updated_at") or "(시각 정보 없음)"
    return (
        f"  진로: {data.get('career_goal', '(없음)')[:80]}\n"
        f"  니즈: {needs}\n"
        f"  마지막 갱신: {updated}"
    )


def _run(debug: bool = False) -> int:
    print("=== 수행평가 보조 AI (comseba) ===\n")
    storage = LocalStorage()
    pipeline = Pipeline(_build_modules())

    student_name = _ask_text("학생 이름을 입력하세요").strip()
    if not student_name:
        print("학생 이름이 비어 있어 종료합니다.")
        return 1

    # 구 세션 (학생 디렉토리에 profile.json 없음 + 세션 안에는 있음) → 1회성 끌어올림.
    if storage.migrate_session_profile_to_student(student_name):
        print("(이전 세션의 학생 프로필을 학생 디렉토리로 이동했습니다.)\n")

    ctx = _open_or_create_session(storage, student_name)
    print(f"세션 경로: {ctx.session_path}\n")

    # Step 1-2: profile
    if STEP_PROFILE not in ctx.completed:
        force_rebuild = False
        if storage.has_profile(student_name):
            existing = storage.load_profile(student_name)
            print("[기존 학생 프로필 발견]")
            print(_summarize_profile(existing))
            print()
            choice = _ask_select(
                "프로필을 어떻게 처리할까요?",
                [_PROFILE_REUSE, _PROFILE_UPDATE, _PROFILE_REBUILD],
            )
            if choice == _PROFILE_REUSE:
                pipeline.run_profile(ctx, force_rebuild=False)
                print("✓ 기존 프로필을 그대로 사용합니다.\n")
            else:
                # update / rebuild 모두 새 LLM 호출 + 기존을 history 로 백업.
                career_text, hwp_paths, source = _ask_career_inputs()
                kakao_paths = _ask_path_list("카카오톡 스크린샷 경로")
                pipeline.run_profile(
                    ctx,
                    career_text=career_text,
                    kakao_paths=kakao_paths,
                    career_hwp_paths=hwp_paths,
                    career_source=source,
                    force_rebuild=True,
                )
                print("✓ 프로필을 갱신했습니다. (이전 버전은 profile_history/ 에 보관)\n")
        else:
            career_text, hwp_paths, source = _ask_career_inputs()
            kakao_paths = _ask_path_list("카카오톡 스크린샷 경로")
            pipeline.run_profile(
                ctx,
                career_text=career_text,
                kakao_paths=kakao_paths,
                career_hwp_paths=hwp_paths,
                career_source=source,
                force_rebuild=force_rebuild,
            )
            print("✓ 학생 프로필 생성 완료\n")

    # Step 2.5: subject (이번 수행평가의 과목 — 다운스트림 system prompt 에 컨텍스트로)
    if STEP_SUBJECT not in ctx.completed:
        subject = _ask_subject()
        pipeline.run_subject(ctx, subject)
        print(f"✓ 과목 선택: {subject.name}\n")

    # Step 3: criteria
    if STEP_CRITERIA not in ctx.completed:
        rubric_paths = _ask_path_list("평가 기준 이미지 경로 (최소 1장)")
        if not rubric_paths:
            print("평가 기준 이미지가 필요합니다. 종료합니다.")
            return 1
        criteria = pipeline.run_criteria(ctx, rubric_paths)
        pipeline._m.criteria_extractor.display(criteria)
        if not _ask_confirm("위 평가 기준이 맞나요?"):
            print("재시도가 필요한 경우 세션을 새로 시작해주세요.")
            return 1

    # Step 4: suggestions (skippable)
    if STEP_SUGGESTIONS not in ctx.completed:
        skip = not _ask_confirm("수행평가 아이디어를 제안받을까요?", default=True)
        ideas = pipeline.run_suggestions(ctx, skip=skip)
        if ideas:
            print("\n=== 수행평가 아이디어 ===")
            for i, idea in enumerate(ideas, 1):
                print(f"{i}. {idea.title}\n   {idea.description}\n   (이유: {idea.rationale})")
            print()

    # Step 5: evaluation
    if STEP_EVALUATION not in ctx.completed:
        mode = _ask_select(
            "제출물을 어떻게 입력하시겠어요?",
            ["파일 (PDF / 이미지)", "직접 텍스트 입력"],
        )
        if mode == "파일 (PDF / 이미지)":
            pdfs = [p for p in _ask_path_list("PDF 경로") if p.suffix.lower() == ".pdf"]
            imgs = [
                p
                for p in _ask_path_list("이미지 경로")
                if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
            ]
            text = None
        else:
            text = _ask_multiline("제출물 텍스트를 붙여넣으세요")
            pdfs, imgs = [], []
        pipeline.run_evaluation(ctx, text, imgs, pdfs)
        print("✓ 항목별 피드백 생성 완료\n")

    # Step 6: model answer
    if STEP_MODEL_ANSWER not in ctx.completed:
        pipeline.run_model_answer(ctx)
        print("✓ 예시 답안 생성 완료\n")

    # Step 7: report
    if STEP_REPORT not in ctx.completed:
        pipeline.run_report(ctx)
        print(f"✓ 보고서 저장: {ctx.session_path / 'report.md'}\n")

    # Step 8: SMS
    if STEP_SMS not in ctx.completed:
        assessment_name = _ask_text("수행평가명을 입력하세요 (예: 환경 보고서 글쓰기)")
        if not assessment_name.strip():
            print("수행평가명이 비어 있어 SMS 단계를 건너뜁니다.")
        else:
            pipeline.run_sms(ctx, assessment_name=assessment_name)
            print(f"✓ 학부모 문자 초안 저장: {ctx.session_path / 'sms.txt'}\n")

    print(f"=== 완료 — 세션 결과: {ctx.session_path} ===")
    return 0


def main() -> int:
    debug = "--debug" in sys.argv[1:]
    try:
        return _run(debug=debug)
    except KeyboardInterrupt:
        print("\n사용자가 중단했습니다. 진행한 단계는 저장되어 있습니다.")
        return 130
    except Exception as exc:  # noqa: BLE001 — top-level user-facing wrapper
        if debug:
            traceback.print_exc()
        else:
            print(f"\n오류가 발생했습니다: {exc}", file=sys.stderr)
            print("자세한 내용을 보려면 `--debug` 플래그로 다시 실행하세요.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
