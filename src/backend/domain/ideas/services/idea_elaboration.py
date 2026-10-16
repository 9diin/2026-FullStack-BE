"""아이디어 구체화(Elaboration) 서비스 레이어

스펙 섹션 5(Next Action Items) 중 Backend API 엔드포인트 연계를 담당합니다.
POST /api/v1/idea-generations/{generation_id}/elaboration
"""

from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from backend.domain.ideas.llm.elaboration_generator import (
    ElaborationProblemContext,
    GeminiIdeaElaborationGenerator,
    GeneratedSolution,
    IdeaElaborationGenerator,
    ProblemContextPainPoint,
    normalize_evidence_point,
)
from backend.domain.ideas.llm.idea_generator import (
    IdeaGenerationTimeout,
    IdeaGeneratorConfigurationError,
    IdeaGeneratorRateLimited,
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
    SolutionResponse,
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

        # The solution is always model-generated; supplied problem data is passed as context.
        problem_context = None
        if (
            request.persona is not None
            and request.pain_point_cycle is not None
            and request.ai_coaching is not None
            and request.summary is not None
        ):
            problem_context = ElaborationProblemContext(
                summary=request.summary,
                persona_title=request.persona.title,
                persona_description=request.persona.description,
                persona_evidence_points=list(request.persona.evidence_points),
                pain_points=[
                    ProblemContextPainPoint(
                        order=order,
                        step_name=step.step_name,
                        title=step.title,
                        description=step.description,
                        highlight_tag=step.highlight_tag,
                    )
                    for order, step in enumerate(request.pain_point_cycle, start=1)
                ],
            )
        try:
            generated = self.generator.generate(
                generation.prompt,
                selected_suggestion.title,
                selected_suggestion.details,
                [],
                problem_context=problem_context,
            )
        except IdeaGeneratorConfigurationError as exc:
            raise IdeaAPIError(
                503,
                "LLM_CONFIGURATION_ERROR",
                "Gemini API 인증·모델·요청 형식이 올바른지 확인해 주세요. "
                "상세 오류는 백엔드 로그에서 확인할 수 있습니다.",
            ) from exc
        except IdeaGeneratorRateLimited as exc:
            raise IdeaAPIError(
                429,
                "LLM_QUOTA_EXCEEDED",
                "Gemini API 요청 한도를 초과했습니다. Google AI Studio에서 "
                "사용량·결제 설정을 확인하거나 한도 초기화 후 다시 시도해 주세요.",
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

        if (
            request.persona is None
            or request.pain_point_cycle is None
            or request.ai_coaching is None
            or request.summary is None
        ):
            title = generated.title
            summary = generated.summary
            persona_dict = {
                "title": generated.persona.title,
                "description": generated.persona.description,
                "evidence_points": [
                    normalize_evidence_point(pt)
                    for pt in generated.persona.evidence_points
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

        pain_point_ids = [uuid4() for _ in pain_point_list]
        for order, (pain_point, pain_point_id) in enumerate(
            zip(pain_point_list, pain_point_ids, strict=True), start=1
        ):
            pain_point["pain_point_id"] = str(pain_point_id)
            pain_point["order"] = order
        solution_dict = self._serialize_solution(generated.solution, pain_point_ids)

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
            existing.solution = solution_dict
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
            solution=solution_dict,
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
    def _serialize_solution(
        solution: GeneratedSolution,
        pain_point_ids: list[UUID],
    ) -> dict:
        solution_step_ids = {step.order: uuid4() for step in solution.pipeline}
        return {
            "summary": solution.summary,
            "validation": solution.validation.model_dump(mode="json"),
            "pipeline": [
                {
                    "solution_step_id": str(solution_step_ids[step.order]),
                    "order": step.order,
                    "category": step.category,
                    "title": step.title,
                    "subtitle": step.subtitle,
                    "description": step.description,
                    "technology_label": step.technology_label,
                    "addresses_pain_point_ids": [
                        str(pain_point_ids[order - 1])
                        for order in step.addresses_pain_point_orders
                    ],
                    "metrics": [
                        metric.model_dump(mode="json") for metric in step.metrics
                    ],
                }
                for step in solution.pipeline
            ],
            "comparison": {
                "as_is": {
                    "label": "AS-IS",
                    "metrics": [
                        metric.model_dump(mode="json")
                        for metric in solution.comparison.as_is.metrics
                    ],
                    "items": [
                        {
                            "item_id": str(uuid4()),
                            "text": item.text,
                            "pain_point_ids": [
                                str(pain_point_ids[order - 1])
                                for order in item.pain_point_orders
                            ],
                        }
                        for item in solution.comparison.as_is.items
                    ],
                },
                "to_be": {
                    "label": "TO-BE",
                    "metrics": [
                        metric.model_dump(mode="json")
                        for metric in solution.comparison.to_be.metrics
                    ],
                    "items": [
                        {
                            "item_id": str(uuid4()),
                            "text": item.text,
                            "pain_point_ids": [
                                str(pain_point_ids[order - 1])
                                for order in item.pain_point_orders
                            ],
                            "solution_step_ids": [
                                str(solution_step_ids[order])
                                for order in item.solution_step_orders
                            ],
                        }
                        for item in solution.comparison.to_be.items
                    ],
                },
            },
        }

    @staticmethod
    def _to_response(elaboration: IdeaElaboration) -> ElaborationResponse:
        """ORM 모델을 응답 스키마로 변환합니다."""
        if elaboration.solution is None:
            raise IdeaAPIError(
                409,
                "SOLUTION_REGENERATION_REQUIRED",
                "기존 구체화 데이터에 해결방안이 없습니다. 구체화를 다시 생성해 주세요.",
            )
        persona_data = elaboration.persona
        pain_point_data = elaboration.pain_point_cycle

        return ElaborationResponse(
            elaboration_id=elaboration.id,
            generation_id=elaboration.generation_id,
            selected_idea_id=elaboration.suggestion_id,
            schema_version="2.0",
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
                    pain_point_id=step["pain_point_id"],
                    order=step["order"],
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
            solution=SolutionResponse.model_validate(elaboration.solution),
            created_at=elaboration.created_at,
        )
