using UnrealBuildTool;
using System.Collections.Generic;

public class BrickflowEditorTarget : TargetRules
{
    public BrickflowEditorTarget(TargetInfo Target) : base(Target)
    {
        Type = TargetType.Editor;
        DefaultBuildSettings = BuildSettingsVersion.V7;
        IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
        ExtraModuleNames.Add("Brickflow");
    }
}
