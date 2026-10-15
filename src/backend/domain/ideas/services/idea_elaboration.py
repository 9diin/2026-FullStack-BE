"""아이디어 구체화(Elaboration) 서비스 레이어

스펙 섹션 5(Next Action Items) 중 Backend API 엔드포인트 연계를 담당합니다.
POST /api/v1/idea-generations/{generation_id}/elaboration
"""

from uuid import UUID

from sqlalchemy.orm import Session

from backend.domain.ideas.llm.elaboration_generator import (
    GeminiIdeaElaborationGenerator,
    IdeaElaborationGenerator,
    normalize_evidence_point,
)
from backend.domain.ideas.llm.idea_generator import (
    IdeaGenerationTimeout,
    IdeaGeneratorConfigurationError,
    IdeaGeneratorUnavailable,
    InvalidIdeaGeneration,
)
from backend.domain.ideas.models.idea_generation import (
    IdeaElaboration,
    IdeaGeneration,
    IdeaSuggestion,
)
from backend.domain.ideas.schemas.idea_elaboration import (
    AICoaching,
    ElaborationRequest,
    ElaborationResponse,
    PainPointCycleStepResponse,
    TargetPersona,
)
from backend.domain.ideas.services.idea_generation import IdeaAPIError
from backend.domain.users.models.user import User


class IdeaElaborationService:
    """아이디어 구체화 데이터 생성 및 조회 서비스"""

    def __init__(
        self,
        db: Session,
        generator: IdeaElaborationGenerator | None = None,
    ) -> None:
        self.db = db
        self.generator = generator or GeminiIdeaElaborationGenerator()

    def create_elaboration(
        self,
        user: User,
        generation_id: UUID,
        request: ElaborationRequest,
    ) -> ElaborationResponse:
        """선택한 아이디어에 대한 구체화 데이터를 생성(또는 갱신)하여 저장하고 반환합니다."""
        # 1. 아이디어 생성 결과 소유권 검증
        generation = (
            self.db.query(IdeaGeneration)
            .filter(
                IdeaGeneration.id == generation_id,
                IdeaGeneration.user_id == user.id,
            )
            .first()
        )
        if generation is None:
            raise IdeaAPIError(
                404, "GENERATION_NOT_FOUND", "도출 결과를 찾을 수 없습니다."
            )

        # 2. 선택된 아이디어 제안 유효성 검증
        selected_suggestion: IdeaSuggestion | None = next(
            (
                suggestion
                for suggestion in generation.suggestions
                if suggestion.id == request.selected_idea_id
            ),
            None,
        )
        if selected_suggestion is None:
            raise IdeaAPIError(
                404, "IDEA_NOT_FOUND", "선택한 아이디어를 찾을 수 없습니다."
            )

        # 3. 구체화 데이터 획득: request에 완전한 데이터가 제공되지 않은 경우 LLM 자동 생성
        if (
            request.persona is None
            or request.pain_point_cycle is None
            or request.ai_coaching is None
            or request.summary is None
        ):
            try:
                generated = self.generator.generate(
                    generation.prompt,
                    selected_suggestion.title,
                    selected_suggestion.details,
                    [],
                )
            except IdeaGeneratorConfigurationError as exc:
                raise IdeaAPIError(
                    503,
                    "LLM_CONFIGURATION_ERROR",
                    "Gemini API 키, 모델명 또는 API 설정을 확인해 주세요.",
                ) from exc
            except IdeaGeneratorUnavailable as exc:
                raise IdeaAPIError(
                    503, "LLM_UNAVAILABLE", "아이디어 구체화 서비스를 사용할 수 없습니다."
                ) from exc
            except IdeaGenerationTimeout as exc:
                raise IdeaAPIError(
                    504, "GENERATION_TIMEOUT", "아이디어 구체화 생성 시간이 초과되었습니다."
                ) from exc
            except InvalidIdeaGeneration as exc:
                raise IdeaAPIError(
                    502,
                    "LLM_INVALID_RESPONSE",
                    "유효한 구체화 결과를 생성하지 못했습니다.",
                ) from exc

            title = generated.title
            summary = generated.summary
            persona_dict = {
                "title": generated.persona.title,
                "description": generated.persona.description,
                "evidence_points": [
                    normalize_evidence_point(pt) for pt in generated.persona.evidence_points
                ],
            }
            pain_point_list = [
                {
                    "step": step.step,
                    "step_name": step.step_name,
                    "title": step.title,
                    "description": step.description,
                    "highlight_tag": step.highlight_tag,
                }
                for step in generated.pain_point_cycle
            ]
            solution_evidence = generated.ai_coaching.solution_evidence
            feedback_review = generated.ai_coaching.feedback_review
        else:
            title = request.title or selected_suggestion.title
            summary = request.summary
            persona_dict = {
                "title": request.persona.title,
                "description": request.persona.description,
                "evidence_points": list(request.persona.evidence_points),
            }
            pain_point_list = [
                {
                    "step": step.step,
                    "step_name": step.step_name,
                    "title": step.title,
                    "description": step.description,
                    "highlight_tag": step.highlight_tag,
                }
                for step in request.pain_point_cycle
            ]
            solution_evidence = request.ai_coaching.solution_evidence
            feedback_review = request.ai_coaching.feedback_review

        # 4. DB UPSERT (기존 구체화 데이터가 있으면 다른 아이디어 선택 시 갱신)
        existing = (
            self.db.query(IdeaElaboration)
            .filter(
                IdeaElaboration.generation_id == generation_id,
                IdeaElaboration.user_id == user.id,
            )
            .first()
        )

        if existing is not None:
            existing.suggestion_id = request.selected_idea_id
            existing.title = title
            existing.summary = summary
            existing.persona = persona_dict
            existing.pain_point_cycle = pain_point_list
            existing.solution_evidence = solution_evidence
            existing.feedback_review = feedback_review
            self.db.commit()
            self.db.refresh(existing)
            return self._to_response(existing)

        elaboration = IdeaElaboration(
            generation_id=generation_id,
            suggestion_id=request.selected_idea_id,
            user_id=user.id,
            title=title,
            summary=summary,
            persona=persona_dict,
            pain_point_cycle=pain_point_list,
            solution_evidence=solution_evidence,
            feedback_review=feedback_review,
        )
        self.db.add(elaboration)
        self.db.commit()
        self.db.refresh(elaboration)

        return self._to_response(elaboration)

    def get_elaboration(
        self,
        user: User,
        generation_id: UUID,
    ) -> ElaborationResponse:
        """generation_id에 대한 구체화 데이터를 조회합니다.

        Raises:
            IdeaAPIError(404): 구체화 데이터가 없는 경우
        """
        elaboration = (
            self.db.query(IdeaElaboration)
            .filter(
                IdeaElaboration.generation_id == generation_id,
                IdeaElaboration.user_id == user.id,
            )
            .first()
        )
        if elaboration is None:
            raise IdeaAPIError(
                404,
                "ELABORATION_NOT_FOUND",
                "구체화 데이터를 찾을 수 없습니다.",
            )
        return self._to_response(elaboration)

    @staticmethod
    def _to_response(elaboration: IdeaElaboration) -> ElaborationResponse:
        """ORM 모델을 응답 스키마로 변환합니다."""
        persona_data = elaboration.persona
        pain_point_data = elaboration.pain_point_cycle

        return ElaborationResponse(
            elaboration_id=elaboration.id,
            generation_id=elaboration.generation_id,
            selected_idea_id=elaboration.suggestion_id,
            title=elaboration.title,
            summary=elaboration.summary,
            persona=TargetPersona(
                title=persona_data["title"],
                description=persona_data["description"],
                evidence_points=tuple(persona_data["evidence_points"]),  # type: ignore[arg-type]
            ),
            pain_point_cycle=tuple(  # type: ignore[arg-type]
                PainPointCycleStepResponse(
                    step=step["step"],
                    step_name=step["step_name"],
                    title=step["title"],
                    description=step["description"],
                    highlight_tag=step["highlight_tag"],
                )
                for step in pain_point_data
            ),
            ai_coaching=AICoaching(
                solution_evidence=elaboration.solution_evidence,
                feedback_review=elaboration.feedback_review,
            ),
            created_at=elaboration.created_at,
        )
