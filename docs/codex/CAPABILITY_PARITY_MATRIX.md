# Capability Parity Matrix - Phase A

Statuses describe the current Mining360 AI inventory, not the future Codex implementation.

| Domain | Existing source/service | Current evidence | New strategy |
|---|---|---|---|
| Capability discovery | `AIAgentCapability`, `ai_capability_discovery_service.py` | 24 records; 5 validated records are Ready/Limited | Read-only import with independent Codex revisions and tests |
| Fleet inventory | `EquipmentList_MiningProd` snapshot in `bm_equipment_fleet_analysis` | IMPLEMENTED in Codex: authorized MineSite inventory, model/family summaries, serial lookup, machine detail, field coverage, persisted evidence and private CSV export | Extend later with historical snapshots and performance measures; current inventory remains distinct from performance |
| Revenue | `BusinessCommandCenterService` over `bm_revenue_source_snapshot` | IMPLEMENTED in Codex: official Mining Revenue by Machine, Parts, Service, Rental and Unclassified; governed periods, published dimensions, reconciliation, confidence, rankings, persisted evidence and private CSV export | Add transaction-level drill-down only through a separately authorized bounded tool |
| Performance | semantic measures and `machine_performance_intent_service.py` | Validated/Limited capability | Adapter per official measure; no naive aggregation |
| Downtime | downtime explorer/services and SMCS classification | Validated/Limited capability | Compose bounded tools; label interpretation separately |
| Knowledge | resource knowledge and validated dictionaries | 15,231 items, all currently To Review; 575 validated synonyms | Import provenance first; do not treat corpus as globally validated |
| KPI definitions | `KnowledgeKPIDictionary` | 6 active records, all To Review | Exclude from published answer until reviewed or cite as pending |
| Reporting navigation | Power BI interaction models/services | Validated/Ready capability; multiple active reports | Reuse navigation contracts read-only after authorization test |
| Parts sales | parts sales services and mappings | Code/tests exist; not represented in validated capability list | Audit and certify before enabling in Codex catalog |
| Conversation persistence | `AIConversation*` models and APIs | 28 conversations, 278 messages, 32 executions | New tables and owner/module isolation; optional authorized import |
| Artifacts/exports | conversation artifacts and fleet/performance exports | Existing persisted snapshots and export endpoints | New artifact ownership; reuse format services only by contract |
| Voice | voice config/transcription services | UI controls exist conditionally | Out of first slice until provider and privacy tests pass |
| Multi-agent routing | agent router and two active agents | Most records To Review | Do not copy routing as truth; new orchestration catalog first |
| Provider gateway | provider routing, budget, circuit and usage services | Models and logs present | Evaluate reusable infrastructure without sharing prompts/history |
| Answerability | assessment service and events | Mixed modern and legacy status values | Adopt new stable contract and migrate only through import mapping |

## Initial parity target

The Fleet and Revenue families are implemented against real, read-only, scope-enforced snapshots with persisted evidence and private exports. All other rows remain explicit gaps until individually implemented and tested.
