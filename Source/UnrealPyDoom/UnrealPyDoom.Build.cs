using System;
using System.IO;
using EpicGames.Core;
using UnrealBuildTool;

// The project module owns the game-specific static Python library on Wasm.
public class UnrealPyDoom : ModuleRules
{
	public UnrealPyDoom(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
		if (Target.Platform.ToString() == "Wasm")
		{
			string Cache = Path.Combine(Target.ProjectFile.Directory.FullName, "Intermediate", "UnrealPy",
				"Compiled", "Wasm", "wasm64", Target.Configuration.ToString(), "Package", "Link");
			string Current = Path.Combine(Cache, "current");
			if (!File.Exists(Current) || !Guid.TryParseExact(File.ReadAllText(Current).Trim(), "N", out Guid Id))
			{
				throw new BuildException("Prepare the Wasm Python archive with tools/package-web.ps1.");
			}
			string Generation = Path.Combine(Cache, "generations", Id.ToString("N"));
			string Manifest = Path.Combine(Generation, "manifest.json");
			string Library = Path.Combine(Generation, "libunrealpy_modules.a");
			JsonObject Metadata = JsonObject.Read(new FileReference(Manifest));
			AdditionalPropertiesForReceipt.Add("UnrealPyWasmLibrary", Metadata.GetStringField("sha256"));
			ExternalDependencies.Add(Current);
			ExternalDependencies.Add(Manifest);
			PublicAdditionalLibraries.Add(Library);
		}
	}
}
