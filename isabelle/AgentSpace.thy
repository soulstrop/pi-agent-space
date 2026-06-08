theory AgentSpace
  imports Main
begin

section ‹Core Types›

type_synonym prompt = string
type_synonym context = "string list"
type_synonym code = string

datatype test_result = Pass | Fail string

record metrics =
  tokens_consumed     :: nat
  cost_dollars        :: real
  validation_pass_rate :: real
  quality_score       :: real
  scaling_slope       :: real

datatype outcome =
  Completed metrics
| BoundaryViolation metrics
| ErrorEscalated

definition metrics_of :: "outcome ⇒ metrics option" where
  "metrics_of o = (case o of
    Completed m ⇒ Some m
  | BoundaryViolation m ⇒ Some m
  | ErrorEscalated ⇒ None)"

record ('a, 'b) trial =
  config  :: "'a"
  outcome :: outcome

section ‹Pareto Dominance (ADR 0005 / 0012)›

definition metrics_dominate :: "metrics ⇒ metrics ⇒ bool" where
  "metrics_dominate a b ⟷
    (tokens_consumed a ≤ tokens_consumed b ∧
     cost_dollars a ≤ cost_dollars b ∧
     scaling_slope a ≤ scaling_slope b ∧
     quality_score a ≥ quality_score b) ∧
    (tokens_consumed a < tokens_consumed b ∨
     cost_dollars a < cost_dollars b ∨
     scaling_slope a < scaling_slope b ∨
     quality_score a > quality_score b)"

definition dominates :: "('a, 'b) trial ⇒ ('a, 'b) trial ⇒ bool" where
  "dominates t1 t2 ⟷ (
    case (metrics_of (outcome t1), metrics_of (outcome t2)) of
      (Some m1, Some m2) ⇒ metrics_dominate m1 m2
    | _ ⇒ False)"

definition pareto_frontier :: "('a, 'b) trial list ⇒ ('a, 'b) trial list" where
  "pareto_frontier trials = [t ← trials. 
    metrics_of (outcome t) ≠ None ∧ 
    ¬ (∃other ∈ set trials. dominates other t)]"

section ‹The AgentGraph DSL›

datatype ('a, 'b) agent_graph =
    Id
  | Seq "('a, 'x) agent_graph" "('x, 'b) agent_graph"
  | Par "('a1, 'b1) agent_graph" "('a2, 'b2) agent_graph"
  | Copy
  | Drop
  | Choice "('a1, 'b1) agent_graph" "('a2, 'b2) agent_graph"
  | Loop "('b * 'd, 'c * 'd) agent_graph"
  | ApplySkill string
  | ApplyContextSkill string
  | ExtractCode
  | QueryMCP string
  | CallModel string
  | RunTests
  | MergeStrings
  | DreamSkill
  | SubscribeStream

end
