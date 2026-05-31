# Studio to Agent1 Core Contract

## Intent
This contract is the stable plug between the Studio shell and the future Agent1 core. Studio owns web input, attachments, queueing, process lifecycle, and display. Agent1 owns reasoning, clarification, architecture plan generation, signoff evidence, and Agent2 handoff artifacts.

## Start Payload
Studio launches Agent1 through `python -m coreweaver.studio_runner start`.

Required fields:
- `requirement`: user chip/IP request, max 2000 characters from Studio UI.
- `project_name`: public project slug used for output path and run labels.
- `planning_mode`: `normal` or `deep_planning`.
- `run_id`: immutable run identifier from Studio.
- `thread_id`: Studio conversation/run thread identifier.
- `output_dir`: run output root.

Optional fields:
- `checkpoint_db`
- `attachment_manifest`
- `attachment_context`

The code contract lives in `src/coreweaver/contracts/studio_agent1.py`.

## Event Contract
Agent1 emits JSON lines on stdout. Studio reads each line as one event.

Allowed event types:
- `agent_action`
- `agent_handoff`
- `artifact`
- `debug_issue`
- `done`
- `error`
- `metric`
- `pause`
- `stage`
- `agent1_topology_loaded`
- `agent1_cluster_assignment`
- `agent1_group_session_start`
- `agent1_group_session_done`
- `agent1_group_session_failed`
- `agent1_group_retry`
- `agent1_cross_group_challenge`
- `agent1_principal_group_review`
- `agent1_clarification_question`
- `agent1_clarification_answer`
- `agent1_council_mode_selected`
- Additional `agent1_*` runtime events for leaf experts, plan DAG nodes, model/tool routing, safety decisions, rollback/proposal, blackboard writes, signoff gates, and handoff readiness are defined in `src/coreweaver/contracts/studio_agent1.py`.

Rules:
- Every non-metric event must include `run_id`.
- `agent_action` from Agent1 must set `agent=agent1`.
- `pause` must include `action_required` and `message`.
- `artifact` must include `path`.
- `debug_issue` must include `severity`, `source`, `code`, and `message`.
- Events must not contain raw prompts, API keys, bearer tokens, or secrets.

## Pause Types
Agent1 may stop Studio at these pause gates:
- `CORE_SKELETON_READY`
- `REQUIREMENT_CLARIFICATION`
- `PLAN_REVIEW`
- `HITL_REQUIRED`
- `CONFLICT_REQUIRED`
- `NON_DESIGN_CONVERSATION`
- `HUMAN_REVIEW`

## Artifact Contract
Agent1 should eventually produce these stable artifacts before Agent2 handoff:
- `reports/architecture_plan.md`
- `contracts/agent1_to_agent2.json`
- `reports/agent1/agent1_final_signoff_certificate.json`

Missing artifacts must become `debug_issue` entries instead of silent failure.
Agent2 consumers must validate `contracts/agent1_to_agent2.json` for `ready == true`, empty blockers, and a passing referenced signoff certificate before starting Agent2 work.

## Run Profiles
`COREWEAVER_RUN_PROFILE` selects the runtime profile:
- `local_skeleton`: default, no credential required, no LLM call.
- `local_llm`: future local LLM-backed core, credential required.
- `ci_no_llm`: CI-safe checks without LLM calls.

Studio reads `CoreWeaverRuntime.capabilities()` to decide whether START needs a configured credential.
