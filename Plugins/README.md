# Plugins

This project needs the ScriptCore and UnrealPy plugins, which are distributed separately and are not part of this
repository. Put them here as `Plugins/ScriptCore` and `Plugins/UnrealPy` (both folders are git-ignored), or
install them into the engine. The plugin binaries load only in the engine version they were built for: use the
Unreal Engine 5.8 builds.

Use a build that supports the project's `Content/Python/unrealpy` import root.
