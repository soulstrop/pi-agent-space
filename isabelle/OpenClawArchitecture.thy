theory OpenClawArchitecture
  imports AgentSpace
begin

definition tool_pipeline :: "(context, context) agent_graph" where
  "tool_pipeline = 
    Seq (ApplyContextSkill ''Filter_Tools_By_Policy'') (
      Seq (ApplyContextSkill ''Normalize_Tool_Schemas'') 
          (ApplyContextSkill ''Enforce_Sandbox_Paths'')
    )"

definition agent_execution_with_streaming :: "(prompt * context, code) agent_graph" where
  "agent_execution_with_streaming = 
    Seq Copy (
      Seq (Par (CallModel ''OpenClaw-Embedded-Session'') SubscribeStream)
          ExtractCode
    )"

definition open_claw_workflow :: "(prompt * context, test_result) agent_graph" where
  "open_claw_workflow = 
    Seq (Par Id (ApplyContextSkill ''Resolve_Auth_Profile'')) (
      Seq (Par Id tool_pipeline) (
        Seq agent_execution_with_streaming RunTests
      )
    )"

end
