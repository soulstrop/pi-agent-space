theory Ports
  imports AgentSpace
begin

(* 
   In Isabelle, we use locales to model abstract ports. 
   This allows us to reason about the trial runner without 
   committing to a specific implementation.
*)

typedecl package
typedecl graduated_problem
typedecl raw_telemetry
typedecl subjective_score

locale agent_system =
  fixes run_harness :: "package ⇒ graduated_problem ⇒ raw_telemetry"
  fixes score_objective :: "raw_telemetry ⇒ metrics"
  fixes score_subjective :: "outcome ⇒ subjective_score option"
begin

(* run_trial would be a recursive function over the problem list *)
fun run_trial :: "package ⇒ graduated_problem list ⇒ outcome list" where
  "run_trial pkg [] = []"
| "run_trial pkg (p # ps) = (Completed (score_objective (run_harness pkg p))) # run_trial pkg ps"

end

end
