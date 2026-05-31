from __future__ import annotations

from .models import Challenge, ChallengeSeverity, ManagerSummary, PrincipalReview, RequirementPack


class ChallengeMatrix:
    def __init__(self, *, max_rounds: int = 3) -> None:
        self.max_rounds = max_rounds

    def build(self, pack: RequirementPack, summaries: tuple[ManagerSummary, ...]) -> tuple[Challenge, ...]:
        text = pack.raw_text.lower()
        challenges: list[Challenge] = []
        if "force_m06_m07_conflict" in text:
            challenges.append(
                Challenge(
                    challenge_id="challenge:M06:M07:forced",
                    source_group_id="group:M06",
                    target_group_id="group:M07",
                    severity=ChallengeSeverity.BLOCKER,
                    message="Forced test conflict between PPA/Physical and Integration/Contract groups.",
                )
            )
        if ("key" in text or "aes" in text) and ("readable key" in text or "readback key" in text):
            challenges.append(
                Challenge(
                    challenge_id="challenge:M04:M07:key_readback",
                    source_group_id="group:M04",
                    target_group_id="group:M07",
                    severity=ChallengeSeverity.BLOCKER,
                    message="Security group rejects any readable key register in handoff contract.",
                )
            )
        for summary in summaries:
            if summary.failed_expert_ids:
                challenges.append(
                    Challenge(
                        challenge_id=f"challenge:{summary.manager_id}:failed_experts",
                        source_group_id=summary.group_id,
                        target_group_id="principal",
                        severity=ChallengeSeverity.WARN,
                        message=f"{summary.manager_id} has failed experts: {', '.join(summary.failed_expert_ids)}.",
                        resolved=True,
                    )
                )
        return tuple(challenges)

    def review(self, challenges: tuple[Challenge, ...], *, iteration: int) -> PrincipalReview:
        blockers = tuple(challenge for challenge in challenges if challenge.severity == ChallengeSeverity.BLOCKER and not challenge.resolved)
        if blockers and iteration >= self.max_rounds:
            return PrincipalReview(approved=False, iteration=iteration, unresolved_challenges=blockers, action_required="HITL_REQUIRED")
        if blockers:
            return PrincipalReview(approved=False, iteration=iteration, unresolved_challenges=blockers, action_required="RETRY")
        return PrincipalReview(approved=True, iteration=iteration, unresolved_challenges=())
