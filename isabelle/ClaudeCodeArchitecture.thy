theory ClaudeCodeArchitecture
  imports AgentSpace
begin

definition coordinator_sub_agents :: "(prompt * context, code) agent_graph" where
  "coordinator_sub_agents = 
    Seq Copy (
      Seq (Par (Seq Id (CallModel ''Claude-3-Haiku-Explore'')) 
               (Seq Id (CallModel ''Claude-3-Opus-Plan'')))
          MergeStrings
    )"

definition kairos_daemon :: "(code, code) agent_graph" where
  "kairos_daemon = ApplySkill ''KAIROS_Background_Refactor''"

definition undercover_mode :: "(code, code) agent_graph" where
  "undercover_mode = ApplySkill ''Strip_CoAuthoredBy_Metadata''"

definition claude_code_workflow :: "(prompt * context, test_result) agent_graph" where
  "claude_code_workflow = 
    Seq coordinator_sub_agents (
      Seq kairos_daemon (
        Seq undercover_mode RunTests
      )
    )"

definition dreaming_loop :: "(code, test_result) agent_graph" where
  "dreaming_loop = Loop DreamSkill"

end
