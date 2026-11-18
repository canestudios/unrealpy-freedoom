using UnrealBuildTool;

// The game is Python (Python/doom); this empty module exists because the Wasm target packages C++ projects only.
public class UnrealPyDoom : ModuleRules
{
	public UnrealPyDoom(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
	}
}
