using UnrealBuildTool;

public class Brickflow : ModuleRules
{
    public Brickflow(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        CppStandard = CppStandardVersion.Cpp20;
        bEnableExceptions = true;
        bUseUnity = false;
        PublicDependencyModuleNames.AddRange(new string[] {
            "Core", "CoreUObject", "Engine", "InputCore", "Json", "JsonUtilities",
            "Slate", "SlateCore", "MeshDescription", "StaticMeshDescription",
            "RenderCore", "RHI", "ImageWrapper"
        });
        RuntimeDependencies.Add("$(ProjectDir)/Content/Data/...", StagedFileType.NonUFS);
    }
}
