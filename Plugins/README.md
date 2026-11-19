# Plugins

This project needs the ScriptCore and UnrealPy plugins, which are distributed separately and are not part of this
repository. Put them here as `Plugins/ScriptCore` and `Plugins/UnrealPy` (both folders are git-ignored), or
install them into the engine. The plugin binaries load only in the engine version they were built for: use the
Unreal Engine 5.9 builds. The web build also needs UnrealPy's Wasm support, which only its Unreal Engine 5.9 build
has; that build downloads its web Python (CPython and NumPy for Wasm) by itself.
