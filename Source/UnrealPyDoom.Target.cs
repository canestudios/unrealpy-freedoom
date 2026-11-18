using UnrealBuildTool;

public class UnrealPyDoomTarget : TargetRules
{
	public UnrealPyDoomTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("UnrealPyDoom");
	}
}
