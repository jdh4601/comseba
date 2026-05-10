"""CLI Pipeline tests — orchestration and resume logic.

questionary 호출과 LLM 호출은 모두 mock. 파일 I/O 만 실제 (tmp_path).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from comseba.cli import (
    STEP_CRITERIA,
    STEP_EVALUATION,
    STEP_MODEL_ANSWER,
    STEP_PROFILE,
    STEP_REPORT,
    STEP_SMS,
    STEP_SUGGESTIONS,
    Pipeline,
    _Modules,
    _SessionContext,
    _restore_state,
)
from comseba.criteria_extractor import Criterion
from comseba.profile_builder import StudentProfile
from comseba.storage import LocalStorage
from comseba.submission_evaluator import CriterionFeedback
from comseba.suggestion_engine import AssessmentIdea


def _profile() -> StudentProfile:
    return StudentProfile(
        name="홍길동",
        career_goal="간호사",
        inferred_needs=["사례 학습"],
        communication_style="조심스러움",
    )


def _criteria() -> list[Criterion]:
    return [
        Criterion("주제 적합성", "주제 일치", 5),
        Criterion("표현력", "어휘", 5),
    ]


def _feedback() -> list[CriterionFeedback]:
    return [
        CriterionFeedback("주제 적합성", "ok", met=True),
        CriterionFeedback("표현력", "보완 필요", met=False),
    ]


def _modules() -> _Modules:
    """Return _Modules where every module is a MagicMock."""
    profile_builder = MagicMock()
    profile_builder.build.return_value = _profile()

    criteria_extractor = MagicMock()
    criteria_extractor.extract.return_value = _criteria()
    # to_dict_list is a static method — Pipeline calls it on the class itself,
    # so we don't need to mock the instance attribute.

    suggestion_engine = MagicMock()
    suggestion_engine.suggest.return_value = [
        AssessmentIdea("a", "b", "c"),
        AssessmentIdea("d", "e", "f"),
        AssessmentIdea("g", "h", "i"),
        AssessmentIdea("j", "k", "l"),
    ]

    submission_evaluator = MagicMock()
    submission_evaluator.evaluate.return_value = _feedback()

    model_answer_generator = MagicMock()
    model_answer_generator.generate.return_value = "[AI 생성 예시 답안]\n본문"

    report_generator = MagicMock()
    report_generator.generate.return_value = "# 보고서\n본문"

    sms_generator = MagicMock()
    sms_generator.generate.return_value = "안녕하세요... ^^"

    return _Modules(
        profile_builder=profile_builder,
        criteria_extractor=criteria_extractor,
        suggestion_engine=suggestion_engine,
        submission_evaluator=submission_evaluator,
        model_answer_generator=model_answer_generator,
        report_generator=report_generator,
        sms_generator=sms_generator,
    )


@pytest.fixture
def ctx(tmp_path: Path) -> _SessionContext:
    storage = LocalStorage(base_dir=tmp_path / "students")
    session_path = storage.new_session("홍길동")
    return _SessionContext(
        storage=storage, session_path=session_path, student_name="홍길동"
    )


def test_pipeline_runs_full_happy_path(ctx: _SessionContext) -> None:
    p = Pipeline(_modules())

    p.run_profile(ctx, "간호사가 되고 싶다", kakao_paths=[])
    p.run_criteria(ctx, [Path("rubric.png")])
    p.run_suggestions(ctx, skip=False, count=4)
    p.run_evaluation(ctx, "제출물", image_paths=[], pdf_paths=[])
    p.run_model_answer(ctx)
    p.run_report(ctx)
    p.run_sms(ctx, assessment_name="환경 보고서")

    assert ctx.completed == {
        STEP_PROFILE,
        STEP_CRITERIA,
        STEP_SUGGESTIONS,
        STEP_EVALUATION,
        STEP_MODEL_ANSWER,
        STEP_REPORT,
        STEP_SMS,
    }
    # student-level profile (shared across sessions)
    assert (ctx.session_path.parent / "profile.json").is_file()
    # session-level files
    assert (ctx.session_path / "rubric.json").is_file()
    assert (ctx.session_path / "suggestions.json").is_file()
    assert (ctx.session_path / "evaluation.json").is_file()
    assert (ctx.session_path / "model_answer.txt").is_file()
    assert (ctx.session_path / "report.md").is_file()
    assert (ctx.session_path / "sms.txt").is_file()
    # session.json carries profile snapshot reference
    state = ctx.storage.load_session_state(ctx.session_path)
    assert state["profile_action"] == "created"
    assert state["profile_updated_at"] is not None


def test_pipeline_skip_suggestions_persists_empty_list(
    ctx: _SessionContext,
) -> None:
    p = Pipeline(_modules())
    p.run_profile(ctx, "x", [])
    p.run_criteria(ctx, [Path("r.png")])

    ideas = p.run_suggestions(ctx, skip=True)

    assert ideas == []
    assert STEP_SUGGESTIONS in ctx.completed
    saved = ctx.storage.load_json(ctx.session_path, "suggestions.json")
    assert saved == {"ideas": []}


def test_pipeline_skips_already_completed_step(ctx: _SessionContext) -> None:
    modules = _modules()
    p = Pipeline(modules)
    p.run_profile(ctx, "career text 1", [])
    assert modules.profile_builder.build.call_count == 1

    # Second call to run_profile should be a no-op (already completed).
    p.run_profile(ctx, "career text 2", [])
    assert modules.profile_builder.build.call_count == 1


def test_resume_loads_completed_state_from_disk(tmp_path: Path) -> None:
    # First session: run all steps with one Pipeline / context
    storage = LocalStorage(base_dir=tmp_path / "students")
    session_path = storage.new_session("홍길동")
    ctx_a = _SessionContext(
        storage=storage, session_path=session_path, student_name="홍길동"
    )
    p = Pipeline(_modules())
    p.run_profile(ctx_a, "career", [])
    p.run_criteria(ctx_a, [Path("r.png")])
    p.run_evaluation(ctx_a, "submission", [], [])
    p.run_model_answer(ctx_a)

    # New session context simulates a fresh CLI invocation resuming the same dir
    state = storage.load_session_state(session_path)
    ctx_b = _SessionContext(
        storage=storage,
        session_path=session_path,
        student_name="홍길동",
        completed=set(state.get("completed_steps") or []),
    )
    _restore_state(ctx_b)

    assert STEP_PROFILE in ctx_b.completed
    assert STEP_EVALUATION in ctx_b.completed
    assert ctx_b.profile is not None
    assert ctx_b.profile.name == "홍길동"
    assert ctx_b.criteria is not None
    assert len(ctx_b.criteria) == 2
    assert ctx_b.evaluation is not None
    assert ctx_b.model_answer == "[AI 생성 예시 답안]\n본문"
    # Steps that were never run should not be in completed
    assert STEP_REPORT not in ctx_b.completed
    assert STEP_SMS not in ctx_b.completed


def test_resume_does_not_recall_llm_for_completed_steps(tmp_path: Path) -> None:
    storage = LocalStorage(base_dir=tmp_path / "students")
    session_path = storage.new_session("홍길동")
    modules = _modules()

    # Run profile + criteria once
    ctx_a = _SessionContext(
        storage=storage, session_path=session_path, student_name="홍길동"
    )
    p = Pipeline(modules)
    p.run_profile(ctx_a, "career", [])
    p.run_criteria(ctx_a, [Path("r.png")])

    # Resume: load state, then attempt to re-run already-done steps
    state = storage.load_session_state(session_path)
    ctx_b = _SessionContext(
        storage=storage,
        session_path=session_path,
        student_name="홍길동",
        completed=set(state.get("completed_steps") or []),
    )
    _restore_state(ctx_b)

    # Reset call counts
    modules.profile_builder.build.reset_mock()
    modules.criteria_extractor.extract.reset_mock()

    p.run_profile(ctx_b, "different career", [])
    p.run_criteria(ctx_b, [Path("rubric_new.png")])

    modules.profile_builder.build.assert_not_called()
    modules.criteria_extractor.extract.assert_not_called()


def test_pipeline_evaluation_passes_through_text_image_pdf(
    ctx: _SessionContext, tmp_path: Path
) -> None:
    modules = _modules()
    p = Pipeline(modules)
    p.run_profile(ctx, "x", [])
    p.run_criteria(ctx, [Path("r.png")])

    img = tmp_path / "i.png"
    pdf = tmp_path / "p.pdf"
    p.run_evaluation(ctx, "본문", [img], [pdf])

    args, kwargs = modules.submission_evaluator.evaluate.call_args
    assert args[0] == ctx.criteria
    assert kwargs["submission_text"] == "본문"
    assert kwargs["submission_image_paths"] == [img]
    assert kwargs["submission_pdf_paths"] == [pdf]


def test_pipeline_model_answer_uses_evaluation_when_available(
    ctx: _SessionContext,
) -> None:
    modules = _modules()
    p = Pipeline(modules)
    p.run_profile(ctx, "x", [])
    p.run_criteria(ctx, [Path("r.png")])
    p.run_evaluation(ctx, "본문", [], [])

    p.run_model_answer(ctx)

    _, kwargs = modules.model_answer_generator.generate.call_args
    assert kwargs["evaluation"] == ctx.evaluation


# ---------------------------------------------------------------------------
# COM-20: student-level profile reuse / rebuild
# ---------------------------------------------------------------------------


def test_run_profile_creates_student_level_file_with_action_created(
    ctx: _SessionContext,
) -> None:
    modules = _modules()
    p = Pipeline(modules)

    p.run_profile(ctx, "career", [])

    assert ctx.profile_action == "created"
    assert ctx.profile_updated_at is not None
    # 파일은 학생 디렉토리에 (세션 디렉토리 X)
    assert (ctx.session_path.parent / "profile.json").is_file()
    assert not (ctx.session_path / "profile.json").is_file()


def test_run_profile_reuses_existing_without_calling_llm(
    tmp_path: Path,
) -> None:
    storage = LocalStorage(base_dir=tmp_path / "students")
    storage.save_profile(
        "홍길동",
        {
            "name": "홍길동",
            "career_goal": "기존 진로",
            "inferred_needs": ["기존 니즈"],
            "communication_style": None,
            "updated_at": "2026-04-01T10:00:00",
        },
    )
    session_path = storage.new_session("홍길동")
    ctx = _SessionContext(
        storage=storage, session_path=session_path, student_name="홍길동"
    )
    modules = _modules()
    p = Pipeline(modules)

    p.run_profile(ctx, "이번에 입력한 진로 (무시되어야 함)", [])

    modules.profile_builder.build.assert_not_called()
    assert ctx.profile_action == "reused"
    assert ctx.profile is not None
    assert ctx.profile.career_goal == "기존 진로"
    assert ctx.profile_updated_at == "2026-04-01T10:00:00"


def test_run_profile_force_rebuild_archives_previous_and_calls_llm(
    tmp_path: Path,
) -> None:
    storage = LocalStorage(base_dir=tmp_path / "students")
    storage.save_profile("홍길동", {"name": "홍길동", "career_goal": "v1"})
    session_path = storage.new_session("홍길동")
    ctx = _SessionContext(
        storage=storage, session_path=session_path, student_name="홍길동"
    )
    modules = _modules()
    p = Pipeline(modules)

    p.run_profile(
        ctx,
        career_text="새 진로 입력",
        kakao_paths=[],
        force_rebuild=True,
    )

    modules.profile_builder.build.assert_called_once()
    assert ctx.profile_action == "updated"
    history = storage.list_profile_history("홍길동")
    # save_profile 의 archive 1개 (force_rebuild 진입 시점)
    assert len(history) == 1
    archived = json.loads(history[0].read_text(encoding="utf-8"))
    assert archived["career_goal"] == "v1"


def test_run_profile_session_meta_records_action_and_timestamp(
    ctx: _SessionContext,
) -> None:
    p = Pipeline(_modules())

    p.run_profile(ctx, "career", [])

    state = ctx.storage.load_session_state(ctx.session_path)
    assert state["profile_action"] == "created"
    assert state["profile_updated_at"] is not None


def test_run_report_passes_profile_updated_at(ctx: _SessionContext) -> None:
    modules = _modules()
    p = Pipeline(modules)
    p.run_profile(ctx, "career", [])
    p.run_criteria(ctx, [Path("r.png")])
    p.run_evaluation(ctx, "본문", [], [])
    p.run_model_answer(ctx)

    p.run_report(ctx)

    _, kwargs = modules.report_generator.generate.call_args
    assert kwargs["profile_updated_at"] == ctx.profile_updated_at


# ---------------------------------------------------------------------------
# COM-18: subject step persists + flows into all module calls
# ---------------------------------------------------------------------------


def test_run_subject_persists_to_session_json(ctx: _SessionContext) -> None:
    from comseba.cli import STEP_SUBJECT
    from comseba.subject import Subject

    p = Pipeline(_modules())

    p.run_subject(ctx, Subject.preset("국어"))

    assert ctx.subject == Subject.preset("국어")
    assert STEP_SUBJECT in ctx.completed
    state = ctx.storage.load_session_state(ctx.session_path)
    assert state["subject"] == {"name": "국어", "is_custom": False}


def test_run_subject_is_idempotent_when_already_completed(
    ctx: _SessionContext,
) -> None:
    from comseba.subject import Subject

    p = Pipeline(_modules())
    first = Subject.preset("수학")
    p.run_subject(ctx, first)
    # 재호출은 변경 없이 기존 값 반환.
    second = p.run_subject(ctx, Subject.preset("과학"))

    assert second == first
    assert ctx.subject == first


def test_pipeline_passes_subject_to_all_llm_modules(
    ctx: _SessionContext,
) -> None:
    from comseba.subject import Subject

    modules = _modules()
    p = Pipeline(modules)
    p.run_profile(ctx, "career", [])
    p.run_subject(ctx, Subject.preset("역사"))
    p.run_criteria(ctx, [Path("r.png")])
    p.run_suggestions(ctx, skip=False)
    p.run_evaluation(ctx, "본문", [], [])
    p.run_model_answer(ctx)
    p.run_report(ctx)
    p.run_sms(ctx, assessment_name="x")

    expected = Subject.preset("역사")
    assert modules.criteria_extractor.extract.call_args.kwargs["subject"] == expected
    assert modules.suggestion_engine.suggest.call_args.kwargs["subject"] == expected
    assert modules.submission_evaluator.evaluate.call_args.kwargs["subject"] == expected
    assert modules.model_answer_generator.generate.call_args.kwargs["subject"] == expected
    assert modules.report_generator.generate.call_args.kwargs["subject"] == expected
    assert modules.sms_generator.generate.call_args.kwargs["subject"] == expected


def test_resume_restores_subject_from_session_json(tmp_path: Path) -> None:
    from comseba.cli import STEP_SUBJECT, _restore_state
    from comseba.subject import Subject

    storage = LocalStorage(base_dir=tmp_path / "students")
    session_path = storage.new_session("홍길동")
    # Pretend the subject step already ran in a prior session run
    state = storage.load_session_state(session_path)
    state["subject"] = {"name": "음악", "is_custom": True}
    state["completed_steps"] = [STEP_SUBJECT]
    storage.save_json(session_path, "session.json", state)

    ctx = _SessionContext(
        storage=storage,
        session_path=session_path,
        student_name="홍길동",
        completed={STEP_SUBJECT},
    )
    _restore_state(ctx)

    assert ctx.subject == Subject.custom("음악")


# ---------------------------------------------------------------------------
# COM-19: school level flows into every module call from ctx.level
# ---------------------------------------------------------------------------


def test_pipeline_passes_level_to_all_llm_modules(
    ctx: _SessionContext,
) -> None:
    from comseba.level import SchoolLevel
    from comseba.subject import Subject

    ctx.level = SchoolLevel.HIGH
    modules = _modules()
    p = Pipeline(modules)
    p.run_profile(ctx, "career", [])
    p.run_subject(ctx, Subject.preset("국어"))
    p.run_criteria(ctx, [Path("r.png")])
    p.run_suggestions(ctx, skip=False)
    p.run_evaluation(ctx, "본문", [], [])
    p.run_model_answer(ctx)
    p.run_report(ctx)
    p.run_sms(ctx, assessment_name="x")

    assert modules.profile_builder.build.call_args.kwargs["level"] == SchoolLevel.HIGH
    assert modules.criteria_extractor.extract.call_args.kwargs["level"] == SchoolLevel.HIGH
    assert modules.suggestion_engine.suggest.call_args.kwargs["level"] == SchoolLevel.HIGH
    assert modules.submission_evaluator.evaluate.call_args.kwargs["level"] == SchoolLevel.HIGH
    assert modules.model_answer_generator.generate.call_args.kwargs["level"] == SchoolLevel.HIGH
    assert modules.report_generator.generate.call_args.kwargs["level"] == SchoolLevel.HIGH
    assert modules.sms_generator.generate.call_args.kwargs["level"] == SchoolLevel.HIGH


def test_pipeline_passes_none_level_when_not_set(
    ctx: _SessionContext,
) -> None:
    """Regression: omitting level on _SessionContext must propagate as None."""
    modules = _modules()
    p = Pipeline(modules)

    p.run_profile(ctx, "career", [])

    assert modules.profile_builder.build.call_args.kwargs["level"] is None
